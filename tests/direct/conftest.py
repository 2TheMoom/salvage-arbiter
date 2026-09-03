"""Shared helpers for direct mode tests."""

from eth_account import Account
from eth_account.messages import encode_defunct


def to_hex(addr_bytes):
    """Convert address bytes to checksummed hex matching contract output.

    The contract's get_bets()/get_points() return keys via Address.as_hex,
    which produces EIP-55 checksummed hex. Call after direct_deploy so the
    SDK is on sys.path.
    """
    if hasattr(addr_bytes, "as_hex"):
        return addr_bytes.as_hex
    from genlayer.py.types import Address

    return Address(addr_bytes).as_hex


# Fixed test keypair standing in for a "drained wallet" - not a real wallet,
# never holds funds, exists only so tests can produce genuine EIP-191
# signatures that recovery_arbiter.py's _recover_signer_hex can be tested
# against without hitting a real network.
DRAINED_WALLET_PRIVATE_KEY = "0x" + "42" * 32
DRAINED_WALLET_ADDRESS = Account.from_key(DRAINED_WALLET_PRIVATE_KEY).address

# A second, unrelated keypair for "wrong signer" negative tests.
OTHER_PRIVATE_KEY = "0x" + "24" * 32
OTHER_ADDRESS = Account.from_key(OTHER_PRIVATE_KEY).address


def ownership_message(drained_wallet: str, claimant_hex: str) -> str:
    """Must match RecoveryArbiter._ownership_message exactly."""
    return (
        f"I authorize {claimant_hex} to submit a Salvage Arbiter "
        f"recovery claim on behalf of {drained_wallet}."
    )


def sign_ownership_message(private_key: str, drained_wallet: str, claimant_hex: str) -> str:
    """Signs the ownership message with the given key, EIP-191 personal-sign style."""
    message = ownership_message(drained_wallet, claimant_hex)
    signable = encode_defunct(text=message)
    signed = Account.sign_message(signable, private_key=private_key)
    return "0x" + bytes(signed.signature).hex()
