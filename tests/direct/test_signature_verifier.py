"""Direct-mode tests for the SignatureVerifier contract, in isolation.

RecoveryArbiter's own tests (test_recovery_arbiter.py, via the arbiter_deploy
fixture in conftest.py) already exercise this contract through a real
cross-contract call for every submit_claim scenario. These tests cover the
verifier's own interface directly, plus edge cases that don't need a whole
Claim/RecoveryArbiter setup to check.
"""

from tests.direct.conftest import (
    to_address,
    to_hex,
    DRAINED_WALLET_PRIVATE_KEY,
    DRAINED_WALLET_ADDRESS,
    OTHER_PRIVATE_KEY,
    ownership_message,
    sign_ownership_message,
)

CONTRACT = "contracts/signature_verifier.py"
WALLET = f"eth:{DRAINED_WALLET_ADDRESS}"


def test_verify_ownership_valid_signature(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, WALLET, alice.as_hex)

    assert contract.verify_ownership(WALLET, alice, signature) is True


def test_verify_ownership_wrong_signer_fails(direct_vm, direct_deploy, direct_alice):
    """A well-formed signature, but signed by a key that isn't the
    claimed wallet's - must not verify."""
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    signature = sign_ownership_message(OTHER_PRIVATE_KEY, WALLET, alice.as_hex)

    assert contract.verify_ownership(WALLET, alice, signature) is False


def test_verify_ownership_malformed_signature_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    assert contract.verify_ownership(WALLET, alice, "0xnotasignature") is False


def test_verify_ownership_empty_signature_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    assert contract.verify_ownership(WALLET, alice, "") is False


def test_verify_ownership_signature_for_different_wallet_fails(direct_vm, direct_deploy, direct_alice):
    """A genuine signature over the RIGHT wallet's ownership message, but
    checked against a DIFFERENT claimed wallet - must not verify."""
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, WALLET, alice.as_hex)

    other_wallet = f"eth:{'0x' + '11' * 20}"
    assert contract.verify_ownership(other_wallet, alice, signature) is False


def test_verify_ownership_signature_for_different_claimant_fails(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """The signed message names a specific claimant address - a signature
    authorizing Alice must not also verify for Bob."""
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    bob = to_address(direct_bob)
    signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, WALLET, alice.as_hex)

    assert contract.verify_ownership(WALLET, bob, signature) is False


def test_verify_ownership_wallet_format_agnostic(direct_vm, direct_deploy, direct_alice):
    """The signed message embeds the wallet string verbatim, so a
    signature is only valid for the exact string it was signed against -
    but "eth:0x..." vs bare "0x..." vs mixed-case must each independently
    verify their own matching signature (the wallet_hex comparison itself
    is canonicalized, format doesn't make verification silently fail)."""
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)

    for wallet_variant in (DRAINED_WALLET_ADDRESS, WALLET, WALLET.upper().replace("ETH:", "eth:")):
        signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, wallet_variant, alice.as_hex)
        assert contract.verify_ownership(wallet_variant, alice, signature) is True


def test_verify_ownership_unrecognized_wallet_format_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    alice = to_address(direct_alice)
    signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, WALLET, alice.as_hex)

    assert contract.verify_ownership("not-a-wallet", alice, signature) is False


def test_ownership_message_matches_recovery_arbiter_format(direct_vm, direct_deploy, direct_alice):
    """Sanity check: conftest's ownership_message() helper (used to sign
    test fixtures for BOTH this contract and RecoveryArbiter) must match
    the exact message SignatureVerifier itself constructs, since a
    mismatch here would make every other test in this file pass for the
    wrong reason."""
    direct_deploy(CONTRACT)  # only to set up the SDK path for to_hex()
    alice = to_hex(direct_alice)
    expected = (
        f"I authorize {alice} to submit a Salvage Arbiter "
        f"recovery claim on behalf of {WALLET}."
    )
    assert ownership_message(WALLET, alice) == expected
