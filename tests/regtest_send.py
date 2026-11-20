"""Exercise the send flow against an isolated Bitcoin Core regtest node."""

import json
import socket
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app
from addresses import receiving_address
from history import read_history, watch_wallet
from recovery import create_recovery
from sending import prepare_send
from signing import check_acceptance, sign_send


def available_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def confirmed_sats(address):
    _, receipts = app.scan_receipts(address)
    return sum(amount for _, amount, _ in receipts)


def exercise(rpc, directory):
    password = "senha-local-apenas-para-teste"
    phrases = [
        create_recovery(12, password, directory / f"wallet-{index}.json")
        for index in range(3)
    ]
    source, destination, miner = map(receiving_address, phrases)
    amount = 100_000

    with patch.object(app, "rpc", rpc):
        assert app.check_network() == 0
        rpc("generatetoaddress", "101", source, timeout=30)
        initial_balance = confirmed_sats(source)
        assert confirmed_sats(destination) == 0
        watch_wallet(rpc, source)

        draft = prepare_send(rpc, app.scan_address, source, destination, amount)
        signed = sign_send(rpc, draft, source, phrases[0])
        check_acceptance(rpc, signed)
        assert json.loads(rpc("getrawmempool")) == [], "A revisão inseriu uma transação na mempool."
        assert confirmed_sats(source) == initial_balance
        print("Revisão sem transmissão verificada.")

        # Discard the first review, then prepare and explicitly submit a new one.
        draft = prepare_send(rpc, app.scan_address, source, destination, amount)
        signed = sign_send(rpc, draft, source, phrases[0])
        check_acceptance(rpc, signed)
        assert rpc("sendrawtransaction", signed.raw) == signed.txid
        assert signed.txid in json.loads(rpc("getrawmempool"))
        pending = next(entry for entry in read_history(rpc, source) if entry.txid == signed.txid)
        assert pending.status == "Pendente"
        assert (pending.amount, pending.fee, pending.addresses) == (amount, draft.fee, (destination,))

        block_hash, = json.loads(rpc("generatetoaddress", "1", miner, timeout=30))
        assert signed.txid in json.loads(rpc("getblock", block_hash))["tx"]
        assert signed.txid not in json.loads(rpc("getrawmempool"))
        assert confirmed_sats(destination) == amount, "O valor no destino divergiu da revisão."
        assert initial_balance - confirmed_sats(source) == draft.total, (
            "O débito na origem divergiu do valor mais a taxa."
        )
        confirmed = next(entry for entry in read_history(rpc, source) if entry.txid == signed.txid)
        assert (confirmed.status, confirmed.confirmations) == ("Confirmado no destino", 1)
        # A new watch wallet must find the already-mined payment by rescanning.
        received = next(entry for entry in read_history(rpc, destination) if entry.txid == signed.txid)
        assert (received.kind, received.amount, received.confirmations) == ("Recebido", amount, 1)
        print(f"Envio minerado. Valor: {amount} sats. Taxa: {draft.fee} sats. TXID: {signed.txid}")


def main():
    try:
        port = available_port()
    except PermissionError as error:
        raise SystemExit(f"O ambiente bloqueou a abertura de uma porta local para o regtest: {error}")

    with TemporaryDirectory(prefix="bitcoin-carteira-regtest-") as path:
        directory = Path(path)
        common = ["-regtest", f"-datadir={path}", f"-rpcport={port}"]
        with (directory / "node.log").open("w+", encoding="utf-8") as log:
            node = subprocess.Popen(
                ["bitcoind", *common, "-server=1", "-listen=0", "-connect=0",
                 "-rpcbind=127.0.0.1", "-printtoconsole=1"],
                stdout=log, stderr=subprocess.STDOUT,
            )

            def rpc(method, *args, timeout=5, wait=False, wallet=None, named=False):
                command = ["bitcoin-cli", *common, "-rpcconnect=127.0.0.1", f"-rpcclienttimeout={timeout}"]
                if wallet is not None:
                    command.append(f"-rpcwallet={wallet}")
                if named:
                    command.append("-named")
                if wait:
                    command.extend(["-rpcwait", f"-rpcwaittimeout={timeout}"])
                result = subprocess.run(
                    [*command, method, *args], capture_output=True, text=True, timeout=timeout + 2
                )
                if result.returncode:
                    raise RuntimeError(f"{method}: {result.stderr.strip()}")
                return result.stdout.strip()

            try:
                rpc("getblockcount", timeout=15, wait=True)
                exercise(rpc, directory)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                log.seek(0)
                print("Últimas mensagens do nó temporário:")
                print("".join(log.readlines()[-15:]))
                raise
            finally:
                if node.poll() is None:
                    node.terminate()
                    try:
                        node.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        node.kill()
                        node.wait()


if __name__ == "__main__":
    main()
