# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""RecoveryReleaseVault - a working example of a downstream consumer for
RecoveryArbiter's attestation.

This is deliberately not Salvage's real production rescue router (which
runs on other, non-GenLayer chains and holds real user funds) - it's a
small, self-contained, independently deployable contract that proves
RecoveryArbiter's verdict can gate an actual fund release instead of
sitting as unused metadata. Anyone can deposit GEN earmarked for a
specific claim; release() only pays it out to that claim's claimant once
RecoveryArbiter has approved it.
"""

from genlayer import *


class RecoveryReleaseVault(gl.Contract):
    """Escrows deposits per claim_id and releases them to the claimant
    only once RecoveryArbiter approves that claim."""

    arbiter_address: Address
    deposits: TreeMap[str, u256]
    released: TreeMap[str, bool]

    def __init__(self, arbiter_address: str):
        self.arbiter_address = Address(arbiter_address)

    @gl.public.write.payable
    def deposit_for_claim(self, claim_id: str) -> None:
        """Earmarks this transaction's value for a specific claim. Anyone
        can call this (an insurer, a rescue router, a good samaritan)
        before or after a verdict is reached; deposits accumulate across
        multiple calls for the same claim."""
        value = gl.message.value
        if value <= 0:
            raise gl.vm.UserError("Must send a positive amount to deposit")
        self.deposits[claim_id] = self.deposits.get(claim_id, u256(0)) + value

    @gl.public.write
    def release(self, claim_id: str) -> None:
        """Pays out the full deposited amount for `claim_id` to its
        claimant - but only if RecoveryArbiter has approved it. This
        contract never re-judges the claim; it only requires the
        attestation, exactly like a real recovery flow would."""
        if self.released.get(claim_id, False):
            raise gl.vm.UserError("Already released for this claim")

        amount = self.deposits.get(claim_id, u256(0))
        if amount <= 0:
            raise gl.vm.UserError("Nothing deposited for this claim")

        arbiter = gl.get_contract_at(self.arbiter_address)
        status = arbiter.view().get_claim_status(claim_id)
        if status != "approved":
            raise gl.vm.UserError(
                f"RecoveryArbiter has not approved this claim (status: {status})"
            )

        claimant = arbiter.view().get_claim_claimant(claim_id)

        self.released[claim_id] = True
        gl.get_contract_at(claimant).emit_transfer(value=amount)

    @gl.public.view
    def get_deposit(self, claim_id: str) -> u256:
        return self.deposits.get(claim_id, u256(0))

    @gl.public.view
    def is_released(self, claim_id: str) -> bool:
        return self.released.get(claim_id, False)
