"""Track the wallet's public address using a Bitcoin Core watch-only wallet."""

import json
from dataclasses import dataclass
from decimal import Decimal

from addresses import PublicAccount
from sending import decode_amount
from watching import watch_wallet


@dataclass(frozen=True)
class HistoryEntry:
    txid: str
    kind: str
    amount: int
    fee: int | None
    status: str
    confirmations: int
    addresses: tuple[str, ...]


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


def read_history(rpc, account):
    wallet = watch_wallet(rpc, account)
    first_address = account.first_address if isinstance(account, PublicAccount) else account
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
    return build_history(rows, first_address, mempool)
