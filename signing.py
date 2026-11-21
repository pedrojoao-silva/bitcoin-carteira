"""Sign the prototype's native P2WPKH inputs locally using BIP143."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from mnemonic import Mnemonic

from addresses import (
    ACCOUNT_PATH, ADDRESS_LIMIT, CURVE_ORDER, compressed_public_key, derive_private_key,
    encode_p2wpkh, public_key_hash,
)
from networks import REGTEST
from sending import decode_amount


@dataclass(frozen=True)
class SignedSend:
    txid: str
    raw: str


def hash256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def compact_size(value):
    if value < 253:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    return b"\xfe" + value.to_bytes(4, "little")


def vector(data):
    return compact_size(len(data)) + data


def sign_send(rpc, draft, phrase, *, network=REGTEST):
    decoded = json.loads(rpc("decoderawtransaction", draft.unsigned_hex), parse_float=Decimal)
    inputs = decoded["vin"]
    outputs = decoded["vout"]
    if (
        not inputs
        or [(item["txid"], item["vout"]) for item in inputs]
        != [(item.txid, item.output_index) for item in draft.inputs]
    ):
        raise ValueError("As entradas da transação divergem da revisão.")
    expected = {draft.destination: draft.amount}
    if draft.change:
        expected[draft.change_address] = draft.change
    actual = {out["scriptPubKey"]["address"]: decode_amount(out["value"]) for out in outputs}
    if len(outputs) != len(expected) or actual != expected:
        raise ValueError("As saídas da transação divergem da revisão.")
    if sum(item.amount for item in draft.inputs) - sum(actual.values()) != draft.fee:
        raise ValueError("A taxa da transação diverge da revisão.")

    seed = Mnemonic.to_seed(phrase)
    if draft.change:
        branch, index = draft.change_path
        if branch != 1 or not 0 <= index < ADDRESS_LIMIT:
            raise ValueError("O caminho do troco não pertence à carteira.")
        change_key = compressed_public_key(derive_private_key(seed, (*ACCOUNT_PATH, branch, index)))
        change_script = "0014" + public_key_hash(change_key).hex()
        if (
            encode_p2wpkh(change_key, network.bech32_prefix) != draft.change_address
            or not any(out["scriptPubKey"]["hex"] == change_script for out in outputs
                       if out["scriptPubKey"]["address"] == draft.change_address)
        ):
            raise ValueError("O endereço do troco não pertence à carteira desbloqueada.")
    version = decoded["version"].to_bytes(4, "little", signed=True)
    locktime = decoded["locktime"].to_bytes(4, "little")
    outpoints = [
        bytes.fromhex(item["txid"])[::-1] + item["vout"].to_bytes(4, "little")
        for item in inputs
    ]
    sequences = [item["sequence"].to_bytes(4, "little") for item in inputs]
    serialized_inputs = compact_size(len(inputs)) + b"".join(
        outpoint + b"\x00" + sequence for outpoint, sequence in zip(outpoints, sequences)
    )
    output_bytes = b"".join(
        decode_amount(out["value"]).to_bytes(8, "little")
        + vector(bytes.fromhex(out["scriptPubKey"]["hex"]))
        for out in outputs
    )
    body = serialized_inputs + compact_size(len(outputs)) + output_bytes
    unsigned = version + body + locktime
    if unsigned != bytes.fromhex(draft.unsigned_hex):
        raise ValueError("A transação não corresponde ao formato SegWit esperado.")

    prefix = version + hash256(b"".join(outpoints)) + hash256(b"".join(sequences))
    suffix = hash256(output_bytes) + locktime + b"\x01\x00\x00\x00"  # SIGHASH_ALL
    witnesses = []
    for outpoint, sequence, item in zip(outpoints, sequences, draft.inputs):
        branch, index = item.path
        if branch not in (0, 1) or not 0 <= index < ADDRESS_LIMIT:
            raise ValueError("Uma entrada usa um caminho fora da faixa monitorada.")
        secret = derive_private_key(seed, (*ACCOUNT_PATH, branch, index))
        public_key = compressed_public_key(secret)
        key_hash = public_key_hash(public_key)
        if item.script != "0014" + key_hash.hex():
            raise ValueError("Uma entrada não pertence à carteira desbloqueada.")
        key = ec.derive_private_key(secret, ec.SECP256K1())
        script_code = vector(b"\x76\xa9\x14" + key_hash + b"\x88\xac")
        preimage = prefix + outpoint + script_code + item.amount.to_bytes(8, "little") + sequence + suffix
        signature = key.sign(hash256(preimage), ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(signature)
        signature = utils.encode_dss_signature(r, min(s, CURVE_ORDER - s)) + b"\x01"
        witnesses.append(b"\x02" + vector(signature) + vector(public_key))
    signed = version + b"\x00\x01" + body + b"".join(witnesses) + locktime
    return SignedSend(hash256(unsigned)[::-1].hex(), signed.hex())


def check_acceptance(rpc, signed):
    result, = json.loads(rpc("testmempoolaccept", json.dumps([signed.raw])))
    if result.get("txid") != signed.txid:
        raise RuntimeError("O nó retornou um identificador diferente da transação assinada.")
    if not result.get("allowed"):
        reason = result.get("reject-details") or result.get("reject-reason") or "motivo indisponível"
        raise RuntimeError(f"O Bitcoin Core rejeitou a transação: {reason}")
