"""Set up and use the public Bitcoin Core descriptor wallet."""

import hashlib
import json
import re
from threading import Lock

from addresses import ADDRESS_LIMIT, PublicAccount

WATCH_LOCK = Lock()


def watch_wallet(rpc, account):
    with WATCH_LOCK:
        return ensure_watch_wallet(rpc, account)


def ensure_watch_wallet(rpc, account):
    identifier = account.tpub if isinstance(account, PublicAccount) else account
    name = "carteira-observacao-" + hashlib.sha256(identifier.encode("ascii")).hexdigest()[:24]
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

    if isinstance(account, PublicAccount):
        imports = [
            dict(item, timestamp=0, active=True, internal=bool(branch), next_index=1 - branch)
            for branch, item in enumerate(account.scan_objects())
        ]
    else:
        imports = [{"desc": f"addr({account})", "timestamp": 0}]
    known = {item["desc"] for item in json.loads(rpc("listdescriptors", wallet=name))["descriptors"]}
    missing = []
    for item in imports:
        item["desc"] = json.loads(rpc("getdescriptorinfo", item["desc"]))["descriptor"]
        if item["desc"] not in known:
            missing.append(item)
    if missing:
        if isinstance(account, PublicAccount):
            first, = json.loads(rpc("deriveaddresses", imports[0]["desc"], "[0,0]"))
            if first != account.first_address:
                raise RuntimeError("O descritor público diverge do endereço de recuperação.")
        results = json.loads(rpc("importdescriptors", json.dumps(missing), wallet=name, timeout=120))
        for result in results:
            if not result.get("success"):
                reason = result.get("error", {}).get("message", "motivo indisponível")
                raise RuntimeError(f"Não foi possível pesquisar o histórico: {reason}")
    return name


def address_path(rpc, wallet, address):
    info = json.loads(rpc("getaddressinfo", address, wallet=wallet))
    path = info.get("hdkeypath", "").replace("h", "'")
    match = re.fullmatch(r"m/84'/1'/0'/([01])/(0|[1-9][0-9]*)", path)
    if not match or int(match[2]) >= ADDRESS_LIMIT:
        raise ValueError("O endereço está fora da faixa monitorada da carteira.")
    return int(match[1]), int(match[2])


def next_wallet_address(rpc, wallet, branch):
    if branch == 0:
        address = rpc("getnewaddress", "", "bech32", wallet=wallet)
    else:
        address = rpc("getrawchangeaddress", "bech32", wallet=wallet)
    path = address_path(rpc, wallet, address)
    if path[0] != branch:
        raise RuntimeError("O Bitcoin Core retornou um endereço do ramo incorreto.")
    return address, path
