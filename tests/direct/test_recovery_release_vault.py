"""Direct-mode tests for RecoveryReleaseVault.

Cross-contract calls (RecoveryArbiter <- vault) aren't supported by this
project's direct-mode harness without a custom dispatch hook, so the
release-when-approved happy path (and the resulting double-release guard,
which can only be reached after a real release) is verified live on
Bradbury testnet instead - see README "Live deployment". These tests cover
everything reachable without a cross-contract call: deposit accounting and
the guards release() checks before it ever calls out to RecoveryArbiter.
"""

CONTRACT = "contracts/recovery_release_vault.py"
ARBITER_PLACEHOLDER = "0x" + "11" * 20


def test_deposit_for_claim_accumulates(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT, ARBITER_PLACEHOLDER)
    direct_vm.sender = direct_alice

    direct_vm.value = 100
    contract.deposit_for_claim("claim1")
    assert contract.get_deposit("claim1") == 100

    direct_vm.value = 50
    contract.deposit_for_claim("claim1")
    assert contract.get_deposit("claim1") == 150

    assert contract.get_deposit("claim2") == 0


def test_deposit_zero_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT, ARBITER_PLACEHOLDER)
    direct_vm.sender = direct_alice
    direct_vm.value = 0

    with direct_vm.expect_revert("Must send a positive amount to deposit"):
        contract.deposit_for_claim("claim1")


def test_release_without_deposit_fails(direct_vm, direct_deploy, direct_alice):
    """release() checks for a deposit before ever calling out to
    RecoveryArbiter, so this doesn't need cross-contract support."""
    contract = direct_deploy(CONTRACT, ARBITER_PLACEHOLDER)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Nothing deposited for this claim"):
        contract.release("claim1")


def test_is_released_defaults_false(direct_deploy):
    contract = direct_deploy(CONTRACT, ARBITER_PLACEHOLDER)
    assert contract.is_released("claim1") is False
