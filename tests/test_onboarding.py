import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
from addresses import public_account
from recovery import (
    forget_session, generate_phrase, has_open_session, read_public_view, read_recovery,
    remember_session, save_public_account, save_recovery,
)


class OnboardingTests(unittest.TestCase):
    def test_wrong_words_then_cancel_leaves_no_wallet(self):
        phrase = generate_phrase(12)
        window = Mock()
        with (
            patch("app.simpledialog.askinteger", return_value=12),
            patch("app.simpledialog.askstring", side_effect=["palavras incorretas", None]),
            patch("app.messagebox.showerror") as error,
            patch("app.generate_phrase", return_value=phrase),
            patch("app.save_recovery") as save,
        ):
            app.WalletApp.create_phrase(window)
        window.display_phrase.assert_called_once_with(phrase)
        error.assert_called_once()
        save.assert_not_called()
        window.start_session.assert_not_called()

    def test_confirmed_words_are_saved_before_opening_session(self):
        phrase = generate_phrase(24)
        password = "senha-local-de-teste"
        window = Mock()
        window.new_password.return_value = password
        account = public_account(phrase)
        actions = Mock()
        window.start_session = actions.start_session
        with (
            patch("app.simpledialog.askinteger", return_value=24),
            patch("app.simpledialog.askstring", return_value=f"  {phrase}  "),
            patch("app.generate_phrase", return_value=phrase),
            patch("app.save_recovery", actions.save_recovery),
        ):
            app.WalletApp.create_phrase(window)
        self.assertEqual(
            [("save_recovery", (phrase, password), {}),
             ("start_session", (account.first_address, account), {})],
            actions.mock_calls,
        )

    def test_signing_out_removes_session_and_keeps_encrypted_wallet(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wallet.json"
            phrase = generate_phrase(12)
            password = "senha-local-de-teste"
            save_recovery(phrase, password, path)
            account = public_account(phrase)
            save_public_account(account, path=path)
            original = path.read_bytes()
            remember_session(path)
            self.assertTrue(has_open_session(path))
            self.assertEqual(read_public_view(path), (account.first_address, account))
            forget_session(path)
            self.assertFalse(has_open_session(path))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(read_recovery(password, path), phrase)

    def test_resume_session_opens_only_public_view(self):
        account = public_account(generate_phrase(12))
        window = Mock()
        with (
            patch("app.has_open_session", return_value=True),
            patch("app.read_public_view", return_value=(account.first_address, account)),
        ):
            app.WalletApp.resume_session(window)
        window.show_wallet.assert_called_once_with(account.first_address, account)
        window.unlock_phrase.assert_not_called()
