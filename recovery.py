"""Generate and encrypt a local BIP39 recovery phrase for the regtest prototype."""

import base64
import json
import os
import secrets
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from mnemonic import Mnemonic

STRENGTH = {12: 128, 15: 160, 18: 192, 21: 224, 24: 256}
WORD_COUNTS = tuple(STRENGTH)
CONTEXT = b"bitcoin-carteira:regtest:recovery:v1"
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
RECOVERY_FILE = DATA_HOME / "bitcoin-carteira" / "regtest-recovery.json"


def derive_key(password, salt):
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode("utf-8"))


def create_recovery(words, password, path=RECOVERY_FILE):
    if words not in STRENGTH:
        sizes = ", ".join(map(str, WORD_COUNTS))
        raise ValueError(f"Escolha uma destas quantidades de palavras: {sizes}.")
    if len(password) < 12:
        raise ValueError("Use uma senha com pelo menos 12 caracteres.")

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Já existe uma frase de recuperação criptografada.")
    phrase = Mnemonic("english").generate(strength=STRENGTH[words])
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(derive_key(password, salt)).encrypt(
        nonce, phrase.encode("utf-8"), CONTEXT
    )
    record = {"version": 1}
    for name, value in (("salt", salt), ("nonce", nonce), ("ciphertext", encrypted)):
        record[name] = base64.b64encode(value).decode("ascii")

    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(record, file)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    return phrase


def read_recovery(password, path=RECOVERY_FILE):
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["version"] != 1:
        raise ValueError("Formato de recuperação incompatível.")
    salt, nonce, encrypted = (
        base64.b64decode(record[name], validate=True)
        for name in ("salt", "nonce", "ciphertext")
    )
    return AESGCM(derive_key(password, salt)).decrypt(nonce, encrypted, CONTEXT).decode("utf-8")
