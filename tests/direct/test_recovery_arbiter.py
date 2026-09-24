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
DRAIN_TX_HASH = "0x" + "ab" * 32
DRAIN_DESTINATION = "0x" + "cd" * 20

# Must match RecoveryArbiter.TRANSFER_TOPIC exactly.
TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DRAIN_TOKEN = "0x" + "ee" * 20


def _pad_topic(address: str) -> str:
    return "0x" + "00" * 12 + address.lower().removeprefix("0x")


def _transfer_log(
    from_address: str = DRAINED_WALLET_ADDRESS,
    to_address: str = DRAIN_DESTINATION,
    token: str = DRAIN_TOKEN,
    amount: int = 1_000_000,
) -> dict:
    """A genuine ERC-20 Transfer event log, decodable by
    RecoveryArbiter._decode_transfer_out."""
    return {
        "address": token,
        "topics": ["0x" + TRANSFER_TOPIC, _pad_topic(from_address), _pad_topic(to_address)],
        "data": hex(amount),
    }


def _unrelated_log() -> dict:
    """A log with no topics at all - e.g. a non-event or a malformed
    entry. Must never be mistaken for a Transfer."""
    return {"address": DRAIN_TOKEN, "topics": [], "data": "0x"}


def _approval_log(owner: str = DRAINED_WALLET_ADDRESS) -> dict:
    """A real Approval event (different topic0) from the wallet - emits a
    log, but never moves anything. Must not be treated as a drain."""
    approval_topic = "8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    return {
        "address": DRAIN_TOKEN,
        "topics": ["0x" + approval_topic, _pad_topic(owner), _pad_topic(DRAIN_DESTINATION)],
        "data": hex(999),
    }


def _mock_chain_balance(vm, balance_wei: int = 0):
    vm.mock_web(
        r"call=balance",
        {
            "method": "POST",
            "status": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": 1, "result": hex(balance_wei)}),
        },
    )


def _mock_drain_tx(
    vm,
    from_address: str = DRAINED_WALLET_ADDRESS,
    found: bool = True,
    to_address: str = DRAIN_DESTINATION,
    value_wei: int = 1,
    status_success: bool = True,
    logs: list | None = None,
):
    """Mocks eth_getTransactionByHash + eth_getTransactionReceipt together
    (both are needed to authenticate a drain citation - see
    RecoveryArbiter._fetch_tx_facts). Defaults describe a real, successful
    transfer of native value; override to simulate a mismatched sender
    (from_address), a nonexistent tx (found=False), a reverted tx
    (status_success=False), a no-op tx that moved nothing (value_wei=0,
    logs=[]), or a token-style drain (value_wei=0, logs=[_transfer_log()]).
    """
    tx_result = None
    if found:
        tx_result = {
            "from": from_address,
            "to": to_address,
            "value": hex(value_wei),
            "blockNumber": hex(20738308),
            "hash": DRAIN_TX_HASH,
        }
    vm.mock_web(
        r"call=tx",
        {
            "method": "POST",
            "status": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": 1, "result": tx_result}),
        },
    )

    receipt_result = None
    if found:
        receipt_result = {
            "status": "0x1" if status_success else "0x0",
            "logs": logs if logs is not None else [],
        }
    vm.mock_web(
        r"call=receipt",
        {
            "method": "POST",
            "status": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": 1, "result": receipt_result}),
        },
    )


def _valid_signature(claimant_hex: str, wallet: str = WALLET) -> str:
    return sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, wallet, claimant_hex)


def _setup_verdict_mock(vm, evidence_body, verdict, confidence, reasoning, balance_wei=0):
    # The contract requires evidence to mention both the wallet address AND
    # the specific drain transaction (or its destination) before ever
    # consulting the LLM - this authenticates the evidence as being about
    # THIS wallet and THIS incident, not the wallet in general - so every
    # mocked evidence body includes both.
    vm.mock_web(
        r".*evidence\.example.*",
        {
            "status": 200,
            "body": f"{evidence_body} (wallet: {DRAINED_WALLET_ADDRESS}, tx: {DRAIN_TX_HASH})",
        },
    )
    _mock_drain_tx(vm)
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
        DRAIN_TX_HASH,
    )

    claim = contract.get_claim(claim_id)
    assert claim.claimant.as_hex == alice
    assert claim.drained_wallet == WALLET
    assert claim.drain_tx_hash == DRAIN_TX_HASH
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
            WALLET, "https://evidence.example/proof", "statement", "0xnotasignature", DRAIN_TX_HASH
        )


def test_submit_claim_with_wrong_signer_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    # Well-formed signature, but signed by an unrelated key - not the drained wallet.
    wrong_signature = sign_ownership_message(OTHER_PRIVATE_KEY, WALLET, alice)

    with direct_vm.expect_revert("Signature does not prove control of the drained wallet"):
        contract.submit_claim(
            WALLET, "https://evidence.example/proof", "statement", wrong_signature, DRAIN_TX_HASH
        )


def test_submit_duplicate_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    with direct_vm.expect_revert(
        "Claim already submitted for this wallet by this address"
    ):
        contract.submit_claim(
            WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
        )


def _reformatted_wallet() -> str:
    """Same real wallet as WALLET, but different case and no chain prefix -
    used to test that canonicalization treats these as the same wallet."""
    return "0X" + DRAINED_WALLET_ADDRESS[2:].upper()


def test_submit_duplicate_claim_with_reformatted_address_fails(
    direct_vm, direct_deploy, direct_alice
):
    """Adversarial: reformatting the same wallet's address string (dropping
    the chain prefix, changing case) must not let a claimant slip a second
    claim for a wallet they've already claimed past the duplicate check.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    reformatted = _reformatted_wallet()
    reformatted_signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, reformatted, alice)

    with direct_vm.expect_revert(
        "Claim already submitted for this wallet by this address"
    ):
        contract.submit_claim(
            reformatted, "https://evidence.example/proof2", "statement2", reformatted_signature, DRAIN_TX_HASH
        )


def test_submit_claim_for_approved_wallet_blocked_via_reformatted_address(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Adversarial: once a wallet has an approved claim, submitting again
    under a differently-formatted (but identical) address string must still
    be rejected at submission time, not treated as a "new" wallet.
    """
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)
    assert contract.get_claim(claim_id).status == "approved"

    reformatted = _reformatted_wallet()
    direct_vm.sender = direct_bob
    bob_signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, reformatted, bob)

    with direct_vm.expect_revert("This wallet already has an approved recovery claim"):
        contract.submit_claim(
            reformatted, "https://evidence.example/bob", "bob's statement", bob_signature, DRAIN_TX_HASH
        )


def test_adjudicate_denies_reformatted_wallet_competing_claim(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Adversarial: two claims for the same real wallet submitted under
    different address formatting, both still pending when submitted, must
    still trigger the competing-claim guard at adjudication time - the
    canonicalization has to hold even when the exploit targets the
    check-at-adjudication path specifically, not just check-at-submission.
    """
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    alice_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/alice", "alice's statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    reformatted = _reformatted_wallet()
    direct_vm.sender = direct_bob
    bob_signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, reformatted, bob)
    bob_claim_id = contract.submit_claim(
        reformatted, "https://evidence.example/bob", "bob's statement", bob_signature, DRAIN_TX_HASH
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


def test_get_claims_for_wallet_is_format_agnostic(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    reformatted = _reformatted_wallet()
    assert len(contract.get_claims_for_wallet(WALLET)) == 1
    assert len(contract.get_claims_for_wallet(reformatted)) == 1
    assert contract.get_claims_for_wallet(WALLET)[0].id == contract.get_claims_for_wallet(reformatted)[0].id


def test_different_claimants_same_wallet(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    alice_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/alice", "alice's statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.sender = direct_bob
    bob_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/bob", "bob's statement", _valid_signature(bob), DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)
    assert contract.get_claim(claim_id).status == "approved"

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("This wallet already has an approved recovery claim"):
        contract.submit_claim(
            WALLET, "https://evidence.example/bob", "bob's statement", _valid_signature(bob), DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/alice", "alice's statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.sender = direct_bob
    bob_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/bob", "bob's statement", _valid_signature(bob), DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/proof", "I own this wallet, see proof.", _valid_signature(alice), DRAIN_TX_HASH
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
    assert claim.drained_token == "native"
    assert claim.drained_amount == 1
    assert contract.get_claim_drained_asset(claim_id) == "native"
    assert contract.get_claim_drained_amount(claim_id) == 1


def test_adjudicate_denied(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "trust me", _valid_signature(alice), DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/proof", "trust me", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "Page not found.", "insufficient", 40, "No usable evidence.")

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).status == "insufficient"


def test_adjudicate_clamps_confidence(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 150, "overconfident")

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).verdict_confidence == 100


def test_adjudicate_includes_chain_balance_in_prompt(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(
        r".*evidence\.example.*",
        {"status": 200, "body": f"proof (wallet: {DRAINED_WALLET_ADDRESS}, tx: {DRAIN_TX_HASH})"},
    )
    _mock_drain_tx(direct_vm)
    _mock_chain_balance(direct_vm, balance_wei=123456)
    direct_vm.mock_llm(
        r".*Current balance.*123456 wei.*",
        json.dumps({"verdict": "approve", "confidence": 90, "reasoning": "balance matches"}),
    )

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).status == "approved"


def test_adjudicate_denies_when_drain_tx_not_found(direct_vm, direct_deploy, direct_alice):
    """Authoritative check: if the cited drain transaction doesn't exist
    on-chain, the claim is auto-denied without ever consulting the LLM -
    the claimant is citing evidence that doesn't hold up.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_drain_tx(direct_vm, found=False)
    _mock_chain_balance(direct_vm, balance_wei=0)
    # No LLM mock registered - if the contract called the LLM here, the
    # test would fail with an unmocked-prompt error, proving it didn't.

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert DRAIN_TX_HASH in claim.verdict_reasoning
    assert claim.verdict_confidence == 100


def test_adjudicate_denies_when_drain_tx_from_wrong_address(direct_vm, direct_deploy, direct_alice):
    """Authoritative check: if the cited transaction is real but wasn't
    sent from the claimed wallet, the claim is auto-denied without
    consulting the LLM.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_drain_tx(direct_vm, from_address=OTHER_ADDRESS)
    _mock_chain_balance(direct_vm, balance_wei=0)

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert DRAIN_TX_HASH in claim.verdict_reasoning
    assert claim.verdict_confidence == 100


def test_adjudicate_denies_when_drain_tx_reverted(direct_vm, direct_deploy, direct_alice):
    """Authoritative check: a cited transaction that exists and was sent
    from the claimed wallet, but reverted on-chain, proves nothing actually
    happened - it's auto-denied without consulting the LLM.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_drain_tx(direct_vm, status_success=False)
    _mock_chain_balance(direct_vm, balance_wei=0)

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert "reverted" in claim.verdict_reasoning
    assert claim.verdict_confidence == 100


def test_adjudicate_denies_when_drain_tx_moved_nothing(direct_vm, direct_deploy, direct_alice):
    """Authoritative check: a real, successful transaction from the claimed
    wallet that transferred zero native value and emitted no events proves
    no asset actually left the wallet - a claimant can't cite an unrelated
    zero-value transaction (e.g. a self-send) as "proof" of a drain.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_drain_tx(direct_vm, value_wei=0, logs=[])
    _mock_chain_balance(direct_vm, balance_wei=0)

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert "no genuine Transfer event" in claim.verdict_reasoning
    assert claim.verdict_confidence == 100
    assert claim.drained_token == ""
    assert claim.drained_amount == 0


def test_adjudicate_denies_when_only_unrelated_logs_emitted(
    direct_vm, direct_deploy, direct_alice
):
    """Adversarial: a transaction that emits logs - just not a Transfer
    naming this wallet as sender (e.g. only an Approval, or a Transfer to
    someone else's benefit) must NOT be treated as a drain just because
    "some log fired." This is the exact gap an earlier version of this
    contract had (log_count > 0 was sufficient on its own).
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_drain_tx(direct_vm, value_wei=0, logs=[_unrelated_log(), _approval_log()])
    _mock_chain_balance(direct_vm, balance_wei=0)
    # No LLM mock registered - if the contract called the LLM here, the
    # test would fail with an unmocked-prompt error, proving it didn't.

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert "no genuine Transfer event" in claim.verdict_reasoning
    assert claim.drained_token == ""
    assert claim.drained_amount == 0


def test_adjudicate_denies_when_transfer_log_is_from_someone_else(
    direct_vm, direct_deploy, direct_alice
):
    """Adversarial: a real Transfer event log is present, but its `from`
    is a different address than the claimed wallet (e.g. the claimant cited
    a transaction where THEY received tokens, or someone else's transfer
    logged in the same tx). Must not be treated as this wallet's drain.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(r".*evidence\.example.*", {"status": 200, "body": "proof"})
    _mock_drain_tx(direct_vm, value_wei=0, logs=[_transfer_log(from_address=OTHER_ADDRESS)])
    _mock_chain_balance(direct_vm, balance_wei=0)

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert "no genuine Transfer event" in claim.verdict_reasoning


def test_adjudicate_accepts_token_style_drain_with_zero_native_value(
    direct_vm, direct_deploy, direct_alice
):
    """A token drain (e.g. ERC-20) moves zero native value but emits a
    Transfer event log - this must NOT be denied as "nothing moved" just
    because native value_wei is 0, since token transfers are a common real
    drain pattern.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _mock_drain_tx(direct_vm, value_wei=0, logs=[_transfer_log(amount=1_000_000)])
    direct_vm.mock_web(
        r".*evidence\.example.*",
        {"status": 200, "body": f"proof (wallet: {DRAINED_WALLET_ADDRESS}, tx: {DRAIN_TX_HASH})"},
    )
    _mock_chain_balance(direct_vm, balance_wei=0)
    direct_vm.mock_llm(
        r".*adjudicating a cryptocurrency fund-recovery claim.*",
        json.dumps({"verdict": "approve", "confidence": 90, "reasoning": "token drain confirmed"}),
    )

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "approved"
    assert claim.drained_token == DRAIN_TOKEN.removeprefix("0x")
    assert claim.drained_amount == 1_000_000


def test_adjudicate_denies_when_evidence_does_not_reference_incident(
    direct_vm, direct_deploy, direct_alice
):
    """Authoritative check: evidence that mentions the wallet but neither
    the specific drain transaction nor its destination address can't be
    authenticated as evidence for THIS incident - just naming the wallet
    isn't enough on its own.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/generic", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(
        r".*evidence\.example.*",
        {"status": 200, "body": f"Some generic page about {DRAINED_WALLET_ADDRESS}."},
    )
    _mock_drain_tx(direct_vm)
    _mock_chain_balance(direct_vm, balance_wei=0)
    # No LLM mock registered - if the contract called the LLM here, the
    # test would fail with an unmocked-prompt error, proving it didn't.

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert "cannot be authenticated as evidence for THIS incident" in claim.verdict_reasoning
    assert claim.verdict_confidence == 100


def test_adjudicate_accepts_evidence_referencing_destination_instead_of_tx_hash(
    direct_vm, direct_deploy, direct_alice
):
    """Evidence naming the drain's destination address (e.g. a known
    scammer address tracked by a scam database) authenticates the incident
    just as well as quoting the raw transaction hash would.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _mock_drain_tx(direct_vm)
    direct_vm.mock_web(
        r".*evidence\.example.*",
        {
            "status": 200,
            "body": f"Funds from {DRAINED_WALLET_ADDRESS} sent to known scammer {DRAIN_DESTINATION}.",
        },
    )
    _mock_chain_balance(direct_vm, balance_wei=0)
    direct_vm.mock_llm(
        r".*adjudicating a cryptocurrency fund-recovery claim.*",
        json.dumps({"verdict": "approve", "confidence": 90, "reasoning": "destination matches scam db"}),
    )

    contract.adjudicate(claim_id)

    assert contract.get_claim(claim_id).status == "approved"


def test_adjudicate_denies_when_evidence_does_not_mention_wallet(
    direct_vm, direct_deploy, direct_alice
):
    """Authoritative check: evidence that never mentions the claimed wallet
    address anywhere can't be authenticated as being about this wallet, so
    it's auto-denied without consulting the LLM - a generic or copy-pasted
    URL isn't enough.
    """
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/generic", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.mock_web(
        r".*evidence\.example.*", {"status": 200, "body": "This page mentions nothing specific."}
    )
    _mock_drain_tx(direct_vm)
    _mock_chain_balance(direct_vm, balance_wei=0)
    # No LLM mock registered - if the contract called the LLM here, the
    # test would fail with an unmocked-prompt error, proving it didn't.

    contract.adjudicate(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"
    assert "does not mention the claimed wallet" in claim.verdict_reasoning
    assert claim.verdict_confidence == 100


def test_get_claim_status_and_claimant(direct_vm, direct_deploy, direct_alice):
    """Narrow getters used by downstream consumers (e.g.
    RecoveryReleaseVault) - see contracts/recovery_release_vault.py."""
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    assert contract.get_claim_status(claim_id) == "pending"
    assert contract.get_claim_claimant(claim_id).as_hex == alice

    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    assert contract.get_claim_status(claim_id) == "approved"


def test_get_claim_status_unknown_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Claim not found"):
        contract.get_claim_status("nonexistent")


def test_get_claim_claimant_unknown_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Claim not found"):
        contract.get_claim_claimant("nonexistent")


def test_adjudicate_already_adjudicated_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)
    assert contract.get_claim(claim_id).status == "denied"

    direct_vm.clear_mocks()
    contract.submit_appeal(
        claim_id, "https://evidence.example/stronger", "here is a signed message", DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)

    direct_vm.clear_mocks()
    contract.submit_appeal(
        claim_id, "https://evidence.example/stronger", "here is a signed message", DRAIN_TX_HASH
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
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only the claimant can appeal this claim"):
        contract.submit_appeal(claim_id, "https://evidence.example/stronger", "statement", DRAIN_TX_HASH)


def test_appeal_approved_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    with direct_vm.expect_revert("Approved claims cannot be appealed"):
        contract.submit_appeal(claim_id, "https://evidence.example/more", "more evidence", DRAIN_TX_HASH)


def test_appeal_pending_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    with direct_vm.expect_revert("Claim is still awaiting its first adjudication"):
        contract.submit_appeal(claim_id, "https://evidence.example/more", "more evidence", DRAIN_TX_HASH)


def test_appeal_unknown_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Claim not found"):
        contract.submit_appeal("nonexistent", "https://evidence.example/more", "statement", DRAIN_TX_HASH)


def test_appeal_max_limit_reached_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    alice = to_hex(direct_alice)

    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/weak", "trust me", _valid_signature(alice), DRAIN_TX_HASH
    )

    for i in range(3):
        _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
        contract.adjudicate(claim_id)
        contract.submit_appeal(
            claim_id, f"https://evidence.example/attempt{i}", "still trust me", DRAIN_TX_HASH
        )
        direct_vm.clear_mocks()

    assert contract.get_claim(claim_id).appeal_count == 3

    _setup_verdict_mock(direct_vm, "unrelated page", "deny", 90, "no mention of wallet")
    contract.adjudicate(claim_id)

    with direct_vm.expect_revert("Maximum of 3 appeals reached"):
        contract.submit_appeal(claim_id, "https://evidence.example/one-more", "please", DRAIN_TX_HASH)


# ---------------------------------------------------------------------------
# Challenge / resolve_challenge
# ---------------------------------------------------------------------------

def test_challenge_claim_freezes_approved_claim(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)
    assert contract.get_claim(claim_id).status == "approved"

    direct_vm.sender = direct_bob
    reason = "This looks like a voluntary transfer, not a phishing drain."
    contract.challenge_claim(claim_id, reason)

    claim = contract.get_claim(claim_id)
    assert claim.status == "challenged"
    assert claim.challenge_reason == reason
    assert claim.challenger == to_hex(direct_bob).lower().removeprefix("0x")
    assert claim.challenge_count == 1
    assert contract.get_claim_status(claim_id) == "challenged"


def test_challenge_only_works_on_approved_claim(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only an approved claim can be challenged"):
        contract.challenge_claim(claim_id, "reason")


def test_challenge_same_address_twice_fails(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    contract.challenge_claim(claim_id, "first challenge")

    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "still looks good")
    contract.resolve_challenge(claim_id)
    assert contract.get_claim(claim_id).status == "approved"

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("This address has already challenged this claim"):
        contract.challenge_claim(claim_id, "second challenge attempt")


def test_challenge_max_limit_reached_fails(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    from gltest.direct.loader import create_address

    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    dave = create_address("dave")
    eve = create_address("eve")

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    for challenger in (direct_bob, direct_charlie, dave):
        direct_vm.sender = challenger
        contract.challenge_claim(claim_id, "reason")
        direct_vm.sender = direct_alice
        direct_vm.clear_mocks()
        _setup_verdict_mock(direct_vm, "proof", "approve", 90, "still looks good")
        contract.resolve_challenge(claim_id)

    assert contract.get_claim(claim_id).challenge_count == 3

    direct_vm.sender = eve
    with direct_vm.expect_revert("Maximum of 3 challenges reached"):
        contract.challenge_claim(claim_id, "one more")


def test_challenge_unknown_claim_fails(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_bob

    with direct_vm.expect_revert("Claim not found"):
        contract.challenge_claim("nonexistent", "reason")


def test_resolve_challenge_overrules_back_to_approved(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    contract.challenge_claim(claim_id, "reason")

    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _setup_verdict_mock(direct_vm, "proof", "approve", 95, "confirmed again")
    contract.resolve_challenge(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "approved"
    assert claim.verdict_confidence == 95
    assert contract.get_claim_status(claim_id) == "approved"


def test_resolve_challenge_confirms_denial_and_frees_wallet(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """If re-adjudication no longer approves, the wallet's approved-claim
    slot must be freed - a challenged-and-overturned claim doesn't get to
    permanently occupy it."""
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)
    bob = to_hex(direct_bob)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    contract.challenge_claim(claim_id, "this was a voluntary transfer, not a phishing drain")

    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _setup_verdict_mock(direct_vm, "proof", "deny", 90, "evidence supports a voluntary transfer")
    contract.resolve_challenge(claim_id)

    claim = contract.get_claim(claim_id)
    assert claim.status == "denied"

    # The wallet must now be claimable again by a different claimant.
    direct_vm.sender = direct_bob
    new_signature = sign_ownership_message(DRAINED_WALLET_PRIVATE_KEY, WALLET, bob)
    new_claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/bob", "bob's statement", new_signature, DRAIN_TX_HASH
    )
    assert new_claim_id != claim_id


def test_resolve_challenge_by_non_claimant_fails(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    contract.challenge_claim(claim_id, "reason")

    with direct_vm.expect_revert("Only the claimant can resolve a challenge"):
        contract.resolve_challenge(claim_id)


def test_resolve_challenge_when_not_challenged_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    with direct_vm.expect_revert("This claim is not currently challenged"):
        contract.resolve_challenge(claim_id)


def test_resolve_challenge_unknown_claim_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Claim not found"):
        contract.resolve_challenge("nonexistent")


def test_submit_appeal_on_challenged_claim_fails(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT)
    alice = to_hex(direct_alice)

    direct_vm.sender = direct_alice
    claim_id = contract.submit_claim(
        WALLET, "https://evidence.example/proof", "statement", _valid_signature(alice), DRAIN_TX_HASH
    )
    _setup_verdict_mock(direct_vm, "proof", "approve", 90, "looks good")
    contract.adjudicate(claim_id)

    direct_vm.sender = direct_bob
    contract.challenge_claim(claim_id, "reason")

    direct_vm.sender = direct_alice
    with direct_vm.expect_revert(
        "This claim is under challenge - use resolve_challenge, not submit_appeal"
    ):
        contract.submit_appeal(claim_id, "https://evidence.example/more", "more evidence", DRAIN_TX_HASH)
