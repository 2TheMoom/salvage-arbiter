"""Shared helpers for direct mode tests."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

VERIFIER_CONTRACT = "contracts/signature_verifier.py"


@pytest.fixture
def arbiter_deploy(direct_vm, direct_deploy):
    """Deploys RecoveryArbiter wired to a real, locally-deployed
    SignatureVerifier via gltest's cross-contract call hook
    (VMContext._gl_call_hook, documented in gltest/direct/vm.py but not
    otherwise used by this project before now).

    In production, submit_claim's ownership check is a genuine
    cross-contract call (gl.get_contract_at(...).view().verify_ownership),
    since the signature-verification code was extracted out of
    RecoveryArbiter purely to clear Bradbury's ~20-22KB deploy gas ceiling
    (see project memory / genvm-manager#46). gltest's direct-mode harness
    has no built-in cross-contract dispatch (confirmed by inspecting
    wasi_mock.py - CallContract/PostMessage/DeployContract all fall through
    to an optional vm._gl_call_hook, otherwise silently return None), so
    without this fixture every test that reaches submit_claim would need
    to move to live-only verification. Instead, this hook intercepts the
    exact CallContract request submit_claim issues and routes it to the
    real, locally-deployed SignatureVerifier instance - genuine ECDSA
    recovery runs, not a stub, so valid/invalid signature tests stay
    meaningful in direct mode.
    """
    verifier = direct_deploy(VERIFIER_CONTRACT)
    verifier_addr_bytes = bytes(direct_vm._contract_address)
    verifier_hex = "0x" + verifier_addr_bytes.hex()

    # genlayer.gl.genvm_contracts tracks a process-global __known_contract__
    # (Contract.__init_subclass__ enforces "only one Contract subclass per
    # module"), which isn't reset between two sequential deploys within the
    # same vm.activate() session - the second deploy's class definition
    # would otherwise raise TypeError("only one contract is allowed").
    # Resetting it here only affects future class definitions, not the
    # already-constructed verifier instance above.
    import genlayer.gl.genvm_contracts as _genvm_contracts

    _genvm_contracts.__known_contract__ = None

    def _hook(vm, request):
        call = request.get("CallContract") if isinstance(request, dict) else None
        if call is None:
            return None
        addr = call.get("address")
        addr_bytes = addr.as_bytes if hasattr(addr, "as_bytes") else bytes(addr)
        if addr_bytes != verifier_addr_bytes:
            return None

        cd = call.get("calldata") or {}
        method = cd.get("method")
        args = cd.get("args", [])
        kwargs = cd.get("kwargs", {})
        fn = getattr(verifier, method, None)
        if fn is None:
            return None

        result = fn(*args, **kwargs)
        from genlayer.py import calldata

        return bytes([0]) + calldata.encode(result)  # ResultCode.RETURN = 0

    direct_vm._gl_call_hook = _hook

    def _deploy(contract_path, *args, **kwargs):
        return direct_deploy(contract_path, verifier_hex, *args, **kwargs)

    return _deploy


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


def to_address(addr_bytes):
    """Wrap raw address bytes as a genlayer Address, for passing a test
    address as an Address-typed method argument directly (as opposed to
    via direct_vm.sender = ..., which converts internally). Call after
    direct_deploy so the SDK is on sys.path."""
    if hasattr(addr_bytes, "as_hex"):
        return addr_bytes
    from genlayer.py.types import Address

    return Address(addr_bytes)


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
