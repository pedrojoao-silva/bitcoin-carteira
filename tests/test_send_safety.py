import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.exceptions import InvalidTag

import app
from recovery import forget_pending_txid, read_pending_txid, remember_pending_txid
from signing import SignedSend

TXID = "ab" * 32
SIGNED = SignedSend(TXID, "0011")


class SendSafetyTests(unittest.TestCase):
    def review(self, *, review_accepted=True, wrong_password=False, accept=False, node_error=None):
        wallet = Mock()
        wallet.review_payment.return_value = review_accepted
        wallet.unlock_phrase.side_effect = lambda parent: app.WalletApp.unlock_phrase(wallet, parent)
        draft = Mock(destination="test-destination", amount=100_000, change=50_000, fee=142, total=100_142)
        buttons = {}

        def button(_parent, *, text, command, **_options):
            buttons[text] = command
            return Mock()

        def run_task(_window, calculate, show):
            try:
                result = calculate()
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                result = error
            show(result)

        with (
            patch("app.tk.Toplevel"),
            patch("app.tk.StringVar"),
            patch("app.ttk.Frame"),
            patch("app.ttk.Label"),
            patch("app.ttk.Entry", side_effect=[Mock(get=Mock(return_value="target")),
                                              Mock(get=Mock(return_value="100000"))]),
            patch("app.ttk.Button", side_effect=button),
            patch("app.read_pending_txid", return_value=None),
            patch("app.run_node_task", side_effect=run_task),
            patch("app.messagebox.showerror") as show_error,
            patch("app.messagebox.askyesno", return_value=accept) as confirm,
            patch("app.read_recovery", return_value="phrase",
                  side_effect=InvalidTag if wrong_password else None),
            patch("app.check_network"),
            patch("app.prepare_send", return_value=draft),
            patch("app.sign_send", return_value=SIGNED) as sign,
            patch("app.check_acceptance", side_effect=node_error),
            patch("app.broadcast_send") as broadcast,
        ):
            app.WalletApp.open_send(wallet)
            buttons["Revisar envio"]()
            wallet.review_payment.assert_called_once()
            broadcast.assert_not_called()
            if not review_accepted:
                wallet.unlock_phrase.assert_not_called()
                sign.assert_not_called()
                confirm.assert_not_called()
            elif wrong_password:
                show_error.assert_called_once()
                sign.assert_not_called()
                confirm.assert_not_called()
            elif node_error:
                sign.assert_called_once()
                confirm.assert_not_called()
            else:
                sign.assert_called_once()
                confirm.assert_called_once()
                self.assertEqual(confirm.call_args.kwargs["default"], app.messagebox.NO)

    def test_wrong_password_never_signs_or_broadcasts(self):
        self.review(wrong_password=True)

    def test_back_from_review_does_not_request_password(self):
        self.review(review_accepted=False)

    def test_rejecting_final_confirmation_never_broadcasts(self):
        self.review(accept=False)

    def test_lost_connection_during_check_never_broadcasts(self):
        self.review(accept=True, node_error=RuntimeError("Nó indisponível"))

    def test_loss_during_broadcast_keeps_txid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wallet.json"
            path.write_bytes(b"encrypted wallet")
            with (
                patch("app.check_network", return_value=102),
                patch("app.remember_pending_txid", side_effect=lambda txid, **_: remember_pending_txid(txid, path)),
                patch("app.rpc", side_effect=subprocess.TimeoutExpired("bitcoin-cli", 2)) as rpc,
            ):
                with self.assertRaises(app.BroadcastUncertain):
                    app.broadcast_send(SIGNED)
            rpc.assert_called_once_with("sendrawtransaction", SIGNED.raw)
            self.assertEqual(read_pending_txid(path), TXID)
            self.assertEqual(path.with_suffix(".pending.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                set(json.loads(path.with_suffix(".pending.json").read_text())),
                {"txid", "recovery_hash"},
            )
            forget_pending_txid("cd" * 32, path)
            self.assertEqual(read_pending_txid(path), TXID)
            forget_pending_txid(TXID, path)
            self.assertIsNone(read_pending_txid(path))

    def test_network_failure_before_broadcast_records_nothing(self):
        with (
            patch("app.check_network", side_effect=RuntimeError("Nó indisponível")),
            patch("app.remember_pending_txid") as remember,
            patch("app.rpc") as rpc,
        ):
            with self.assertRaisesRegex(RuntimeError, "Nó indisponível") as error:
                app.broadcast_send(SIGNED)
        self.assertNotIsInstance(error.exception, app.BroadcastUncertain)
        remember.assert_not_called()
        rpc.assert_not_called()
