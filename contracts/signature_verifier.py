# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

# secp256k1 curve parameters, for pure-Python ECDSA public-key recovery.
_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP256K1_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_SECP256K1_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _extract_address_hex(wallet: str) -> str:
    """Strips an optional chain prefix (e.g. "eth:") and "0x", lowercased."""
    w = wallet.lower()
    if ":" in w:
        w = w.split(":", 1)[1]
    if w.startswith("0x"):
        w = w[2:]
    return w


def _ec_inv(a: int, m: int) -> int:
    return pow(a, m - 2, m)


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _SECP256K1_P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * _ec_inv(2 * y1, _SECP256K1_P) % _SECP256K1_P
    else:
        lam = (y2 - y1) * _ec_inv((x2 - x1) % _SECP256K1_P, _SECP256K1_P) % _SECP256K1_P
    x3 = (lam * lam - x1 - x2) % _SECP256K1_P
    y3 = (lam * (x1 - x3) - y1) % _SECP256K1_P
    return (x3, y3)


def _ec_mul(k: int, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_add(addend, addend)
        k >>= 1
    return result


def _ecrecover(digest: bytes, v: int, r: int, s: int) -> bytes:
    """Recovers the 20-byte signer address via pure-Python secp256k1 -
    deliberately not an RPC ecrecover call, since different validators can
    land on different backend nodes and disagree even on this deterministic
    a computation, causing spurious consensus failures."""
    if r <= 0 or r >= _SECP256K1_N or s <= 0 or s >= _SECP256K1_N:
        raise ValueError("invalid signature component")

    recovery_id = v - 27
    x = r
    y_squared = (pow(x, 3, _SECP256K1_P) + 7) % _SECP256K1_P
    y = pow(y_squared, (_SECP256K1_P + 1) // 4, _SECP256K1_P)
    if y % 2 != recovery_id % 2:
        y = _SECP256K1_P - y

    point_r = (x, y)
    e = int.from_bytes(digest, "big") % _SECP256K1_N
    r_inv = _ec_inv(r, _SECP256K1_N)
    generator = (_SECP256K1_GX, _SECP256K1_GY)

    s_r = _ec_mul(s, point_r)
    e_g = _ec_mul(e, generator)
    neg_e_g = (e_g[0], (_SECP256K1_P - e_g[1]) % _SECP256K1_P)
    public_key = _ec_mul(r_inv, _ec_add(s_r, neg_e_g))

    pubkey_bytes = public_key[0].to_bytes(32, "big") + public_key[1].to_bytes(32, "big")
    return Keccak256(pubkey_bytes).digest()[-20:]


def _recover_signer_hex(message: str, signature: str) -> str:
    """Recovers the signer of an EIP-191 personal-sign signature and
    returns it as lowercase hex (no 0x), or "" if the signature is
    malformed."""
    message_bytes = message.encode("utf-8")
    prefix = f"\x19Ethereum Signed Message:\n{len(message_bytes)}".encode("utf-8")
    digest = Keccak256(prefix + message_bytes).digest()

    sig_hex = signature.lower()
    if sig_hex.startswith("0x"):
        sig_hex = sig_hex[2:]
    if len(sig_hex) != 130:
        return ""

    try:
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError:
        return ""

    r = int.from_bytes(sig_bytes[:32], "big")
    s = int.from_bytes(sig_bytes[32:64], "big")
    v = sig_bytes[64]
    if v < 27:
        v += 27
    if v not in (27, 28):
        return ""

    try:
        recovered = _ecrecover(digest, v, r, s)
    except (ValueError, ZeroDivisionError):
        return ""
    return recovered.hex()


class SignatureVerifier(gl.Contract):
    """Verifies EIP-191 ownership-proof signatures for a claimed wallet.

    Extracted from RecoveryArbiter (see [[project-salvage-arbiter-genlayer]])
    purely to clear Bradbury's undocumented ~20-22KB source-size deploy
    ceiling (a fixed 16,777,216 gas-per-transaction cap; Python contracts
    need ~730 gas/byte to deploy - see genvm-manager#46). This contract has
    no storage and no dependency on any other contract's state: given a
    claimed wallet, a claimant address, and a signature, it recovers who
    actually signed the exact ownership message RecoveryArbiter expects
    ("I authorize <claimant> to submit a Salvage Arbiter recovery claim on
    behalf of <wallet>.") via pure-Python secp256k1 ECDSA recovery, and
    reports whether that signer matches the claimed wallet.

    Called as a plain cross-contract `.view()` from RecoveryArbiter's
    submit_claim - a normal write method, not from within a nondet/
    equivalence-principle block (GenVM forbids cross-contract calls inside
    run_nondet_unsafe: SystemError 6). Every validator computes this
    deterministically, so consensus on the caller's own transaction is
    unaffected by adding this call.
    """

    def __init__(self):
        pass

    @gl.public.view
    def verify_ownership(self, drained_wallet: str, claimant: Address, signature: str) -> bool:
        wallet_hex = _extract_address_hex(drained_wallet)
        if len(wallet_hex) != 40:
            return False

        message = (
            f"I authorize {claimant.as_hex} to submit a Salvage Arbiter "
            f"recovery claim on behalf of {drained_wallet}."
        )
        recovered = _recover_signer_hex(message, signature)
        return bool(recovered) and recovered == wallet_hex
