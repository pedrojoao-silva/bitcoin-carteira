import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from mnemonic import Mnemonic

import app
from addresses import public_account
from networks import REGTEST, SIGNET
from recovery import (
    has_open_session, profile_path, read_pending_txid, read_public_view, read_recovery,
    remember_pending_txid, remember_session, save_public_account, save_recovery,
)
from signing import SignedSend


class NetworkTests(unittest.TestCase):
    def test_signet_rpc_uses_local_signet_port(self):
        with (
            patch.object(app, "NETWORK", SIGNET),
            patch("app.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run,
        ):
            self.assertEqual(app.rpc("getblockchaininfo"), "{}")
        self.assertEqual(
            run.call_args.args[0][:4],
            ["bitcoin-cli", "-signet", "-rpcconnect=127.0.0.1", "-rpcport=38332"],
        )

    def test_mainnet_is_rejected_by_argument_parser(self):
        result = subprocess.run(
            [sys.executable, "app.py", "--network", "mainnet"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_signet_rejects_wrong_network_and_node_not_ready_before_broadcast(self):
        for description in (
            {"chain": "main"},
            {"chain": "regtest"},
            {"chain": "signet", "initialblockdownload": True},
            {"chain": "signet", "initialblockdownload": False, "pruned": True},
        ):
            with (
                self.subTest(description=description),
                patch.object(app, "NETWORK", SIGNET),
                patch("app.rpc", return_value=json.dumps(description)) as rpc,
                patch("app.remember_pending_txid") as remember,
                self.assertRaises(RuntimeError),
            ):
                app.broadcast_send(SignedSend("ab" * 32, "00"))
            rpc.assert_called_once_with("getblockchaininfo")
            remember.assert_not_called()

    def test_signet_and_regtest_keep_wallet_session_and_pending_txid_separate(self):
        phrase = Mnemonic("english").to_mnemonic(bytes(16))
        password = "senha-apenas-para-teste"
        txid = "ab" * 32
        with tempfile.TemporaryDirectory() as directory, patch("recovery.DATA_HOME", Path(directory)):
            regtest_path = profile_path(REGTEST)
            signet_path = profile_path(SIGNET)
            self.assertNotEqual(signet_path, regtest_path)
            save_recovery(phrase, password, network=REGTEST)
            save_recovery(phrase, password, network=SIGNET)
            regtest = public_account(phrase, REGTEST)
            signet = public_account(phrase, SIGNET)
            self.assertTrue(regtest.first_address.startswith("bcrt1q"))
            self.assertTrue(signet.first_address.startswith("tb1q"))
            save_public_account(regtest)
            save_public_account(signet)
            self.assertEqual(read_public_view(network=REGTEST), (regtest.first_address, regtest))
            self.assertEqual(read_public_view(network=SIGNET), (signet.first_address, signet))
            self.assertIsNone(read_public_view(signet_path, network=REGTEST))
            self.assertEqual(read_recovery(password, network=SIGNET), phrase)
            with self.assertRaises(InvalidTag):
                read_recovery(password, signet_path, network=REGTEST)
            remember_session(signet_path)
            remember_pending_txid(txid, signet_path)
            self.assertTrue(has_open_session(signet_path))
            self.assertFalse(has_open_session(regtest_path))
            self.assertEqual(read_pending_txid(signet_path), txid)
            self.assertIsNone(read_pending_txid(regtest_path))

    def test_balance_is_not_rescanned_until_tip_changes(self):
        with (
            patch("app.check_network"),
            patch("app.rpc", return_value="same-block"),
            patch("app.scan_address") as scan,
        ):
            self.assertIsNone(app.query_balance("address", "same-block"))
        scan.assert_not_called()
