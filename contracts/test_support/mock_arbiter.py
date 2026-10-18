# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""TEST ONLY. A stand-in for RecoveryArbiter with the same get_claim shape, so the vault's money paths can be exercised live on
Bradbury without a real Ethereum drain. Anyone can set any status: it must never be used as a real arbiter, and the vault pointed
at it holds test money only. The real arbiter is exercised separately (see the README)."""

from dataclasses import dataclass
from genlayer import *


@allow_storage
@dataclass
class Claim:
    id: str
    claimant: Address
    drained_wallet: str
    evidence_url: str
    statement: str
    signature: str
    drain_tx_hash: str
    status: str
    verdict_confidence: u256
    verdict_reasoning: str
    appeal_count: u256
    drained_token: str
    drained_amount: u256
    challenge_reason: str
    challenger: str
    challenge_count: u256


class MockArbiter(gl.Contract):
    claims: TreeMap[str, Claim]

    def __init__(self):
        pass

    @gl.public.write
    def put(self, claim_id: str, claimant: str, status: str, token: str, amount: int, challenges: int) -> None:
        self.claims[claim_id] = Claim(
            id=claim_id, claimant=Address(claimant), drained_wallet="", evidence_url="", statement="", signature="", drain_tx_hash="",
            status=status, verdict_confidence=0, verdict_reasoning="", appeal_count=0, drained_token=token, drained_amount=amount,
            challenge_reason="", challenger="", challenge_count=challenges,
        )

    @gl.public.view
    def get_claim(self, claim_id: str) -> Claim:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id]
