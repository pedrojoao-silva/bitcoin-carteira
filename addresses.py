"""Derive the first BIP84 receiving address for the regtest prototype."""

import hashlib
import hmac
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from mnemonic import Mnemonic

CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
HARDENED = 1 << 31
ACCOUNT_PATH = (84 + HARDENED, 1 + HARDENED, HARDENED)
RECEIVING_PATH = (*ACCOUNT_PATH, 0, 0)
ADDRESS_LIMIT = 1000
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def compressed_public_key(private_key):
    return ec.derive_private_key(private_key, ec.SECP256K1()).public_key().public_bytes(
        Encoding.X962, PublicFormat.CompressedPoint
    )


def derive_node(seed, path):
    digest = hmac.digest(b"Bitcoin seed", seed, "sha512")
    private_key = int.from_bytes(digest[:32], "big")
    chain_code = digest[32:]
    parent_key = None
    if not 0 < private_key < CURVE_ORDER:
        raise ValueError("A frase não produziu uma chave mestra válida.")

    for index in path:
        parent_key = private_key
        if index >= HARDENED:
            parent = b"\x00" + private_key.to_bytes(32, "big")
        else:
            parent = compressed_public_key(private_key)
        digest = hmac.digest(chain_code, parent + index.to_bytes(4, "big"), "sha512")
        tweak = int.from_bytes(digest[:32], "big")
        private_key = (private_key + tweak) % CURVE_ORDER
        if tweak >= CURVE_ORDER or private_key == 0:
            raise ValueError("Não foi possível derivar a chave no caminho BIP84.")
        chain_code = digest[32:]
    return private_key, chain_code, parent_key


def derive_private_key(seed, path):
    return derive_node(seed, path)[0]


def derive_public_key(seed, path):
    return compressed_public_key(derive_private_key(seed, path))


def public_key_hash(public_key):
    return hashlib.new("ripemd160", hashlib.sha256(public_key).digest()).digest()


def encode_p2wpkh(public_key, prefix):
    witness_program = public_key_hash(public_key)
    # A 160-bit witness program divides into exactly 32 groups of five bits.
    value = int.from_bytes(witness_program, "big")
    payload = [0, *((value >> shift) & 31 for shift in range(155, -1, -5))]
    expanded_prefix = [ord(character) >> 5 for character in prefix]
    expanded_prefix += [0, *(ord(character) & 31 for character in prefix)]
    checksum = 1
    for group in [*expanded_prefix, *payload, *([0] * 6)]:
        high = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ group
        for bit, generator in enumerate(BECH32_GENERATORS):
            if high & (1 << bit):
                checksum ^= generator
    checksum ^= 1
    payload.extend((checksum >> shift) & 31 for shift in range(25, -1, -5))
    return prefix + "1" + "".join(BECH32_ALPHABET[group] for group in payload)


def receiving_public_key(phrase):
    seed = Mnemonic.to_seed(phrase)
    return derive_public_key(seed, RECEIVING_PATH)


def receiving_address(phrase):
    return encode_p2wpkh(receiving_public_key(phrase), "bcrt")


@dataclass(frozen=True)
class PublicAccount:
    first_address: str
    tpub: str
    fingerprint: str

    def descriptor(self, branch):
        return f"wpkh([{self.fingerprint}/84h/1h/0h]{self.tpub}/{branch}/*)"

    def scan_objects(self):
        return [
            {"desc": self.descriptor(branch), "range": [0, ADDRESS_LIMIT - 1]}
            for branch in (0, 1)
        ]


def public_account(phrase):
    seed = Mnemonic.to_seed(phrase)
    master_key = derive_public_key(seed, ())
    private_key, chain_code, parent_key = derive_node(seed, ACCOUNT_PATH)
    parent_fingerprint = public_key_hash(compressed_public_key(parent_key))[:4]
    payload = (
        bytes.fromhex("043587cf03") + parent_fingerprint + HARDENED.to_bytes(4, "big")
        + chain_code + compressed_public_key(private_key)
    )
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(payload + checksum, "big")
    encoded = []
    while number:
        number, digit = divmod(number, 58)
        encoded.append(BASE58_ALPHABET[digit])
    return PublicAccount(
        receiving_address(phrase), "".join(reversed(encoded)), public_key_hash(master_key)[:4].hex()
    )
