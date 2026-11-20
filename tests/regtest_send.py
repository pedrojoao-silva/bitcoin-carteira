"""Exercise the send flow against an isolated Bitcoin Core regtest node."""

import json
import socket
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app
from addresses import public_account
from history import read_history
from recovery import create_recovery, read_public_view, read_recovery, save_public_account, save_recovery
from sending import prepare_send
from signing import check_acceptance, sign_send
from watching import next_wallet_address, watch_wallet


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
    source, recipient, miner = map(public_account, phrases)
    destination = recipient.first_address
    amount = 5_000_100_000

    with patch.object(app, "rpc", rpc):
        assert app.check_network() == 0
        wallet = watch_wallet(rpc, source)
        next_address, path = next_wallet_address(rpc, wallet, 0)
        assert next_address != source.first_address and path == (0, 1)
        rpc("generatetoaddress", "1", source.first_address)
        rpc("generatetoaddress", "1", next_address)
        rpc("generatetoaddress", "100", miner.first_address, timeout=30)
        initial_balance = confirmed_sats(source)
        assert initial_balance == 10_000_000_000
        assert confirmed_sats(recipient) == 0

        draft = prepare_send(rpc, app.scan_address, source, destination, amount)
        assert {item.path for item in draft.inputs} == {(0, 0), (0, 1)}
        assert draft.change_address not in {source.first_address, next_address}
        assert draft.change_path[0] == 1
        signed = sign_send(rpc, draft, phrases[0])
        check_acceptance(rpc, signed)
        assert json.loads(rpc("getrawmempool")) == [], "A revisão inseriu uma transação na mempool."
        assert confirmed_sats(source) == initial_balance
        print("Revisão sem transmissão verificada.")

        # Discard the first review, then prepare and explicitly submit a new one.
        draft = prepare_send(rpc, app.scan_address, source, destination, amount)
        assert {item.path for item in draft.inputs} == {(0, 0), (0, 1)}
        assert draft.change_address not in {source.first_address, next_address}
        assert draft.change_path[0] == 1
        signed = sign_send(rpc, draft, phrases[0])
        check_acceptance(rpc, signed)
        assert rpc("sendrawtransaction", signed.raw) == signed.txid
        assert signed.txid in json.loads(rpc("getrawmempool"))
        pending = next(entry for entry in read_history(rpc, source) if entry.txid == signed.txid)
        assert pending.status == "Pendente"
        assert (pending.amount, pending.fee, pending.addresses) == (amount, draft.fee, (destination,))

        block_hash, = json.loads(rpc("generatetoaddress", "1", miner.first_address, timeout=30))
        assert signed.txid in json.loads(rpc("getblock", block_hash))["tx"]
        assert signed.txid not in json.loads(rpc("getrawmempool"))
        assert confirmed_sats(recipient) == amount, "O valor no destino divergiu da revisão."
        assert initial_balance - confirmed_sats(source) == draft.total, (
            "O débito na origem divergiu do valor mais a taxa."
        )
        confirmed = next(entry for entry in read_history(rpc, source) if entry.txid == signed.txid)
        assert (confirmed.status, confirmed.confirmations) == ("Confirmado no destino", 1)
        # A new watch wallet must find the already-mined payment by rescanning.
        received = next(entry for entry in read_history(rpc, recipient) if entry.txid == signed.txid)
        assert (received.kind, received.amount, received.confirmations) == ("Recebido", amount, 1)
        restored_path = directory / "restored.json"
        save_recovery(phrases[0], password, restored_path)
        restored = public_account(read_recovery(password, restored_path))
        save_public_account(restored, path=restored_path)
        assert read_public_view(restored_path) == (source.first_address, source)
        rpc("unloadwallet", wallet)
        (directory / "wallets" / wallet).rename(directory / "original-watch-wallet")
        restored_history = read_history(rpc, restored)
        assert any(entry.txid == signed.txid and entry.status == "Confirmado no destino"
                   for entry in restored_history)
        assert confirmed_sats(restored) == draft.change
        assert confirmed_sats(draft.change_address) == draft.change
        restored_watch = watch_wallet(rpc, restored)
        assert next_wallet_address(rpc, restored_watch, 0)[1][1] > path[1]
        assert next_wallet_address(rpc, restored_watch, 1)[1][1] > draft.change_path[1]
        print("Restauração recuperou o histórico e o troco sem reutilizar endereços usados.")
        print(f"Envio minerado. Valor: {amount} sats. Taxa: {draft.fee} sats. TXID: {signed.txid}")


def main():
    try:
        port = available_port()
    except PermissionError as error:
        raise SystemExit(f"O ambiente bloqueou a abertura de uma porta local para o regtest: {error}")

    with TemporaryDirectory(prefix="bitcoin-carteira-regtest-") as path:
        directory = Path(path)
        wallet_directory = directory / "wallets"
        wallet_directory.mkdir()
        common = ["-regtest", f"-datadir={path}", f"-rpcport={port}"]
        with (directory / "node.log").open("w+", encoding="utf-8") as log:
            node = subprocess.Popen(
                ["bitcoind", *common, "-server=1", "-listen=0", "-connect=0",
                 "-rpcbind=127.0.0.1", f"-walletdir={wallet_directory}", "-printtoconsole=1"],
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
