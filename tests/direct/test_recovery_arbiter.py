"""Direct-mode tests for the RecoveryArbiter contract."""

import json

from tests.direct.conftest import (
    to_hex,
    DRAINED_WALLET_PRIVATE_KEY,
    DRAINED_WALLET_ADDRESS,
    OTHER_PRIVATE_KEY,
    OTHER_ADDRESS,
    sign_ownership_message,
)

CONTRACT = "contracts/recovery_arbiter.py"
WALLET = f"eth:{DRAINED_WALLET_ADDRESS}"


def _mock_chain_balance(vm, balance_wei: int = 0):
    vm.mock_web(
        r"publicnode\.com",
        {
            "method": "POST",
            "status": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": 1, "result": hex(balance_wei)}),
        },
    )


def _valid_signature(claimant_hex: str, wallet: str = WALLET) -> str:
    return sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, wallet, claimant_hex)


def _setup_verdict_mock(vm, evidence_body, verdict, confidence, reasoning, balance_wei=0):
    vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": evidence_body})
    _mock_chain_balance(vm, balance_wei)
    vm.mock_llm(
        r".*adjudicating a cryptocurrency fund-recovery claim.*",
        json.dumps(
            {"verdict": verdict, "confidence": confidence, "reasoning": reasoning}
        ),
    )


def test_submit_claim(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET,
        "https://evidence.example/proof",
        "I own this wallet, see proof.",
        _valid_signature(alice),
    )

    claim = contract.get_claim(claim_id)
    assert claim.claimant.as_hex == alice
    assert claim.drained_wallet == WALLET
    assert claim.status == "pending"
    assert claim.verdict_confidence == 0
    assert claim.verdict_reasoning == ""
    assert claim.appeal_count == 0


def test_submit_claim_with_invalid_signature_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    with direct_vm.expect_revert("Signature does not prove control of the drained wallet"):
        contract.submit_claim(
            WALLET, "https://evidence.example/proof", "statement", "0xnotasignature"
        )


def test_submit_claim_with_wrong_signer_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    # Well-formed signature, but signed by an unrelated key - not the drained wallet.
    wrong_signature = sign_ownership_message(OTHER_PRIVATE_KEY, WALLET, alice)

    with direct_vm.expect_revert("Signature does not prove control of the drained wallet"):
        contract.submit_claim(
            WALLET, "https://evidence.example/proof", "statement", wrong_signature
        )


def test_submit_duplicate_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )

    with direct_vm.expect_revert(
        "Claim already submitted for this wallet by this address"
    ):
        contract.submit_claim(
            WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
        )


def test_different_claimants_same_wallet(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    alice_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/alice", "alice's statement", _valid_signature(alice)
    )

    direct_vm.sender = direct_bob
    bob_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/bob", "bob's statement", _valid_signature(bob)
    )

    assert alice_claim_id != bob_claim_id
    assert contract.get_claim(alice_claim_id).drained_wallet == WALLET
    assert contract.get_claim(bob_claim_id).drained_wallet == WALLET
    assert len(contract.get_claims_for_wallet(WALLET)) == 2


def test_submit_claim_for_already_approved_wallet_fails(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)
    assert contract.get_claim(claim_id).status == "approved"

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("This wallet already has an approved recovery claim"):
        contract.submit_claim(
            WALLET, "https://evidence.example/bob", "bob's statement", _valid_signature(bob)
        )


def test_adjudicate_second_pending_claim_for_approved_wallet_denied(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Two claims for the same wallet can both be submitted while pending
    (submit_claim's approved_wallets check only guards against a wallet
    that's *already* approved). Once the first is approved, the second
    must be auto-denied at adjudication time, even if the LLM would have
    approved it - a wallet can only ever end up with one approved claim.
    """
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    alice_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/alice", "alice's statement", _valid_signature(alice)
    )

    direct_vm.sender = direct_bob
    bob_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/bob", "bob's statement", _valid_signature(bob)
    )

    direct_vm.sender = direct_alice
    _setup_verdict_mock(direct_vm, "alice", "approve", 90, "looks good")
    contract.adjudicate(alice_claim_id)
    assert contract.get_claim(alice_claim_id).status == "approved"

    direct_vm.sender = direct_bob
    _setup_verdict_mock(direct_vm, "bob", "approve", 90, "would also approve")
    contract.adjudicate(bob_claim_id)

    bob_claim = contract.get_claim(bob_claim_id)
    assert bob_claim.status == "denied"
    assert alice_claim_id in bob_claim.verdict_reasoning
    assert contract.get_claim(alice_claim_id).status == "approved"


def test_adjudicate_approved(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "I own this wallet, see proof.", _valid_signature(alice)
    )
    _setup_verdict_mock(
        direct_vm,
        "Signed message from the wallet matches the claimant.",
        "approve",
        90,
        "Signature matches the claimed wallet.",
    )

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "approved"
    assert claim.verdict_confidence == 90
    assert claim.verdict_reasoning == "Signature matches the claimed wallet."


def test_adjudicate_denied(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "trust me", _valid_signature(alice)
    )
    _setup_verdict_mock(
        direct_vm,
        "This page is unrelated to any wallet.",
        "deny",
        85,
        "Evidence does not reference the wallet at all.",
    )

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).status == "denied"


def test_adjudicate_insufficient_evidence(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "trust me", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "Page not found.", "insufficient", 40, "No usable evidence.")

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).status == "insufficient"


def test_adjudicate_clamps_confidence(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 150, "overconfident")

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).verdict_confidence == 100


def test_adjudicate_includes_chain_balance_in_prompt(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_chain_balance(direct_vm, balance_wei=123456)
    direct_vm.mock_llm(
        r".*Current balance.*123456 wei.*",
        json.dumps({"verdict": "approve", "confidence": 90, "reasoning": "balance matches"}),
    )

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).status == "approved"


def test_adjudicate_already_adjudicated_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    with direct_vm.expect_revert("Claim already adjudicated"):
        contract.adjudicate(claim_id)


def test_adjudicate_unknown_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Claim not found"):
        contract.adjudicate("nonexistent")


def test_get_claims_by_address(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )

    direct_vm.sender = direct_bob

    alice_claims = contract.get_claims_by_address(alice)
    bob_claims = contract.get_claims_by_address(bob)

    assert len(alice_claims) == 1
    assert alice_claims[0].id == claim_id
    assert len(bob_claims) == 0


def test_get_claims_for_wallet_unknown_returns_empty(direct_deploy):
    contract = direct_deploy(CONTRACT)
    assert contract.get_claims_for_wallet("eth:0xdoesnotexist") == []


def test_get_all_claims_empty(direct_deploy):
    contract = direct_deploy(CONTRACT)
    assert contract.get_all_claims() == {}


def test_appeal_denied_claim_resets_to_pending(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)
    assert contract.get_claim(claim_id).status == "denied"

    direct_vm.clear_mocks()
    contract.submit_appeal(
        claim_id, "https://evidence.example/stronger", "here is a signed message"
    )

    claim = contract.get_claim(claim_id)
    assert claim.status == "pending"
    assert claim.evidence_url == "https://evidence.example/stronger"
    assert claim.statement == "here is a signed message"
    assert claim.verdict_confidence == 0
    assert claim.verdict_reasoning == ""
    assert claim.appeal_count == 1


def test_appeal_then_readjudicate_to_approved(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)

    direct_vm.clear_mocks()
    contract.submit_appeal(
        claim_id, "https://evidence.example/stronger", "here is a signed message"
    )
    _setup_verdict_mock(direct_vm, "signed message matches", "approve", 95, "signature verified")
    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "approved"
    assert claim.verdict_confidence == 95
    assert claim.appeal_count == 1
    assert contract.get_claims_for_wallet(WALLET)[0].id == claim_id


def test_appeal_by_non_claimant_fails(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only the claimant can appeal this claim"):
        contract.submit_appeal(claim_id, "https://evidence.example/stronger", "statement")


def test_appeal_approved_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    with direct_vm.expect_revert("Approved claims cannot be appealed"):
        contract.submit_appeal(claim_id, "https://evidence.example/more", "more evidence")


def test_appeal_pending_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice)
    )

    with direct_vm.expect_revert("Claim is still awaiting its first adjudication"):
        contract.submit_appeal(claim_id, "https://evidence.example/more", "more evidence")


def test_appeal_unknown_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Claim not found"):
        contract.submit_appeal("nonexistent", "https://evidence.example/more", "statement")


def test_appeal_max_limit_reached_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice)
    )

    for i in range(3):
        _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
        contract.adjudicate(claim_id)
        contract.submit_appeal(
            claim_id, f"https://evidence.example/attempt{i}", "still trust me"
        )
        direct_vm.clear_mocks()

    assert contract.get_claim(claim_id).appeal_count == 3

    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)

    with direct_vm.expect_revert("Maximum of 3 appeals reached"):
        contract.submit_appeal(claim_id, "https://evidence.example/one-more", "please")
