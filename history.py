"""Track the wallet's public address using a Bitcoin Core watch-only wallet."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from sending import decode_amount


@dataclass(frozen=True)
class HistoryEntry:
    txid: str
    kind: str
    amount: int
    fee: int | None
    status: str
    confirmations: int
    addresses: tuple[str, ...]


def watch_wallet(rpc, address):
    name = "carteira-observacao-" + hashlib.sha256(address.encode("ascii")).hexdigest()[:24]
    if name not in json.loads(rpc("listwallets")):
        existing = json.loads(rpc("listwalletdir"))["wallets"]
        if any(wallet["name"] == name for wallet in existing):
            rpc("loadwallet", name, timeout=30)
        else:
            rpc(
                "createwallet", f"wallet_name={name}", "disable_private_keys=true",
                "blank=true", "load_on_startup=false",
                named=True, timeout=30,
            )

    info = json.loads(rpc("getwalletinfo", wallet=name))
    if info["private_keys_enabled"]:
        raise RuntimeError("A carteira de observação precisa estar com chaves privadas desativadas.")
    if info["scanning"]:
        raise RuntimeError("O Bitcoin Core ainda está pesquisando os blocos. Aguarde a atualização.")

    descriptor = json.loads(rpc("getdescriptorinfo", f"addr({address})"))["descriptor"]
    descriptors = json.loads(rpc("listdescriptors", wallet=name))["descriptors"]
    if not any(item["desc"] == descriptor for item in descriptors):
        request = json.dumps([{"desc": descriptor, "timestamp": 0}])
        result, = json.loads(rpc("importdescriptors", request, wallet=name, timeout=120))
        if not result.get("success"):
            reason = result.get("error", {}).get("message", "motivo indisponível")
            raise RuntimeError(f"Não foi possível pesquisar o histórico: {reason}")
    return name


def build_history(rows, own_address, mempool):
    transactions = {}
    for row in rows:
        transactions.setdefault(row["txid"], []).append(row)

    history = []
    for txid, entries in transactions.items():
        sent = [item for item in entries if item["category"] == "send"]
        external = [item for item in sent if item.get("address") != own_address]
        received = [
            item for item in entries if item["category"] in {"receive", "generate", "immature", "orphan"}
        ]
        selected = external if sent else received
        if not selected:
            continue

        first = selected[0]
        confirmations = first["confirmations"]
        if (
            first.get("abandoned") or confirmations < 0 or first["category"] == "orphan"
            or first.get("mempoolconflicts")
        ):
            status = "Cancelado" if first.get("abandoned") else "Conflito"
        elif first["category"] == "immature":
            status = "Recompensa imatura"
        elif confirmations > 0:
            status = "Confirmado no destino" if sent else "Confirmado"
        elif txid in mempool:
            status = "Pendente"
        else:
            status = "Sem confirmação"

        addresses = tuple(dict.fromkeys(item.get("address", "") for item in selected))
        fee = next((-decode_amount(item["fee"]) for item in sent if "fee" in item), None)
        amount = sum(decode_amount(item["amount"]) for item in selected)
        history.append(HistoryEntry(
            txid, "Enviado" if sent else "Recebido", abs(amount), fee, status,
            max(0, confirmations), addresses,
        ))
    return history


def read_history(rpc, address):
    wallet = watch_wallet(rpc, address)
    rows = json.loads(
        rpc("listsinceblock", "include_watchonly=true", "include_removed=false",
            named=True, wallet=wallet, timeout=15),
        parse_float=Decimal,
    )["transactions"]
    mempool = set(json.loads(rpc("getrawmempool"))) if any(
        row["confirmations"] == 0 for row in rows
    ) else set()
    rows.sort(key=lambda row: (row["time"], row.get("blockheight", 0), row.get("blockindex", 0)),
              reverse=True)
    return build_history(rows, address, mempool)
