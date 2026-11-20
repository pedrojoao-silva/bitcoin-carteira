"""Generate and encrypt a local BIP39 recovery phrase for the regtest prototype."""

import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from mnemonic import Mnemonic

from addresses import PublicAccount, encode_p2wpkh

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
    phrase = Mnemonic("english").generate(strength=STRENGTH[words])
    save_recovery(phrase, password, path)
    return phrase


def validate_phrase(phrase):
    phrase = " ".join(phrase.split()).lower()
    if len(phrase.split()) not in WORD_COUNTS or not Mnemonic("english").check(phrase):
        raise ValueError("Digite uma frase BIP39 válida da lista inglesa.")
    return phrase


def save_recovery(phrase, password, path=RECOVERY_FILE):
    phrase = validate_phrase(phrase)
    if len(password) < 12:
        raise ValueError("Use uma senha com pelo menos 12 caracteres.")

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Já existe uma frase de recuperação criptografada.")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(derive_key(password, salt)).encrypt(
        nonce, phrase.encode("utf-8"), CONTEXT
    )
    record = {"version": 1}
    for name, value in (("salt", salt), ("nonce", nonce), ("ciphertext", encrypted)):
        record[name] = base64.b64encode(value).decode("ascii")

    write_record(path, record)


def write_record(path, record, replace=False):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(record, file)
            file.flush()
            os.fsync(file.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_public_account(account, address=None, path=RECOVERY_FILE):
    record = {
        "recovery_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "first_address": account.first_address,
        "tpub": account.tpub,
        "fingerprint": account.fingerprint,
        "address": address or account.first_address,
    }
    write_record(path.with_suffix(".public.json"), record, replace=True)


def read_public_view(path=RECOVERY_FILE):
    try:
        record = json.loads(path.with_suffix(".public.json").read_text(encoding="utf-8"))
        recovery_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if record["recovery_hash"] != recovery_hash:
            return None
        if "tpub" in record:
            account = PublicAccount(record["first_address"], record["tpub"], record["fingerprint"])
            address = record["address"]
            pattern = r"bcrt1q[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38}"
            if (
                not re.fullmatch(pattern, address) or not re.fullmatch(pattern, account.first_address)
                or not re.fullmatch(r"tpub[1-9A-HJ-NP-Za-km-z]{107}", account.tpub)
                or not re.fullmatch(r"[0-9a-f]{8}", account.fingerprint)
            ):
                return None
            return address, account
        public_key = bytes.fromhex(record["public_key"])
        if len(public_key) != 33 or public_key[0] not in (2, 3):
            return None
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), public_key)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return encode_p2wpkh(public_key, "bcrt"), None


def read_recovery(password, path=RECOVERY_FILE):
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["version"] != 1:
        raise ValueError("Formato de recuperação incompatível.")
    salt, nonce, encrypted = (
        base64.b64decode(record[name], validate=True)
        for name in ("salt", "nonce", "ciphertext")
    )
    plaintext = AESGCM(derive_key(password, salt)).decrypt(nonce, encrypted, CONTEXT)
    return validate_phrase(plaintext.decode("utf-8"))
