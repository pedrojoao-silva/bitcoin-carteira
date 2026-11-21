"""Estimate and prepare unsigned transactions on the configured test network."""

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from watching import address_path, next_wallet_address, watch_wallet

COIN = 100_000_000
MAX_AMOUNT = 21_000_000 * COIN
CHANGE_DUST = 294
MIN_PAYMENT = 546


@dataclass(frozen=True)
class SendInput:
    txid: str
    output_index: int
    amount: int
    script: str
    path: tuple[int, int]


@dataclass(frozen=True)
class SendDraft:
    destination: str
    amount: int
    change: int
    fee: int
    unsigned_hex: str
    inputs: tuple[SendInput, ...]
    change_address: str | None
    change_path: tuple[int, int] | None

    @property
    def total(self):
        return self.amount + self.fee


def decode_amount(value):
    sats = value * COIN
    if sats != int(sats):
        raise ValueError("O nó retornou um valor com fração de satoshi.")
    return int(sats)


def parse_amount(text):
    text = text.strip()
    if not text.isascii() or not text.isdecimal() or len(text) > len(str(MAX_AMOUNT)):
        raise ValueError("Digite o valor em sats inteiros.")
    amount = int(text)
    if not MIN_PAYMENT <= amount <= MAX_AMOUNT:
        raise ValueError(f"Digite um valor entre {MIN_PAYMENT} e {MAX_AMOUNT} sats.")
    return amount


def fee_rate(rpc):
    estimate = json.loads(rpc("estimatesmartfee", "6"), parse_float=Decimal)
    mempool = json.loads(rpc("getmempoolinfo"), parse_float=Decimal)
    btc_per_kvb = max(estimate.get("feerate", 0), mempool["mempoolminfee"])
    return max(Decimal(1), Decimal(btc_per_kvb) * COIN / 1000)


def estimated_fee(rate, input_count, destination_script, with_change=True):
    # Conservative size for signed native P2WPKH inputs and up to two outputs.
    if input_count >= 65_536:
        raise ValueError("A transação exige entradas demais.")
    overhead = 8 + 2 + (1 if input_count < 253 else 3)
    size = overhead + 69 * input_count + 9 + len(destination_script) // 2
    if with_change:
        size += 31
    return int((rate * size).to_integral_value(rounding=ROUND_CEILING))


def validate_destination(rpc, source, destination):
    info = json.loads(rpc("validateaddress", destination))
    if not info["isvalid"]:
        raise ValueError("Digite um endereço válido para a rede selecionada.")
    normalized = info["address"]
    if normalized == source:
        raise ValueError("O endereço de destino deve ser diferente do endereço de origem.")
    return normalized, info["scriptPubKey"]


def prepare_send(rpc, scan, account, destination, amount):
    destination, script = validate_destination(rpc, account.first_address, destination)
    wallet = watch_wallet(rpc, account)
    info = json.loads(rpc("getaddressinfo", destination, wallet=wallet))
    if info.get("ismine") or info.get("iswatchonly"):
        raise ValueError("Escolha um endereço de destino de outra carteira.")
    rate = fee_rate(rpc)
    snapshot = scan(account)
    candidates = sorted(snapshot["unspents"], key=lambda output: output["amount"], reverse=True)
    inputs = []
    input_total = 0
    for output in candidates:
        current = json.loads(
            rpc("gettxout", output["txid"], str(output["vout"]), "true") or "null",
            parse_float=Decimal,
        )
        if current is None or current["confirmations"] < (100 if current["coinbase"] else 1):
            continue
        if current["scriptPubKey"]["hex"] != output["scriptPubKey"]:
            raise RuntimeError("A saída disponível diverge da saída encontrada na consulta.")
        amount_in = decode_amount(current["value"])
        path = address_path(rpc, wallet, current["scriptPubKey"]["address"])
        inputs.append(SendInput(output["txid"], output["vout"], amount_in, output["scriptPubKey"], path))
        input_total += amount_in
        change = input_total - amount - estimated_fee(rate, len(inputs), script)
        if change >= CHANGE_DUST:
            break
        if input_total - amount >= estimated_fee(rate, len(inputs), script, with_change=False):
            change = 0
            break
    else:
        raise ValueError("Saldo confirmado disponível insuficiente para o valor e a taxa.")

    outputs = {destination: amount}
    change_address = None
    change_path = None
    if change:
        change_address, change_path = next_wallet_address(rpc, wallet, 1)
        outputs[change_address] = change
    # Send fixed-point BTC amounts as strings to preserve exact satoshis.
    amounts = {address: f"{Decimal(sats) / COIN:.8f}" for address, sats in outputs.items()}
    outpoints = [(item.txid, item.output_index) for item in inputs]
    raw_inputs = [{"txid": txid, "vout": index} for txid, index in outpoints]
    raw = rpc("createrawtransaction", json.dumps(raw_inputs), json.dumps(amounts))
    decoded = json.loads(rpc("decoderawtransaction", raw), parse_float=Decimal)
    actual_inputs = [(item["txid"], item["vout"]) for item in decoded["vin"]]
    actual_outputs = {
        item["scriptPubKey"]["address"]: decode_amount(item["value"]) for item in decoded["vout"]
    }
    destination_script_matches = any(
        item["scriptPubKey"]["address"] == destination and item["scriptPubKey"]["hex"] == script
        for item in decoded["vout"]
    )
    if (
        actual_inputs != outpoints
        or len(decoded["vout"]) != len(outputs)
        or actual_outputs != outputs
        or not destination_script_matches
    ):
        raise RuntimeError("A transação preparada diverge das entradas ou saídas esperadas.")
    fee = input_total - sum(actual_outputs.values())
    return SendDraft(destination, amount, change, fee, raw, tuple(inputs), change_address, change_path)
