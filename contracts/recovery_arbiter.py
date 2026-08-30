# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

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
    status: str  # "pending" | "approved" | "denied" | "insufficient"
    verdict_confidence: u256
    verdict_reasoning: str


class RecoveryArbiter(gl.Contract):
    """Adjudicates fund-recovery claims for compromised wallets.

    A claimant asserts ownership of a drained wallet and points to public
    evidence (a signed message, a social post, etc). Validators fetch that
    evidence and reach consensus on a verdict via the equivalence principle,
    producing an on-chain attestation that an off-chain recovery flow
    (e.g. Salvage's cross-chain rescue router) can require before releasing
    funds.
    """

    claims: TreeMap[str, Claim]
    claimant_claims: TreeMap[Address, DynArray[str]]

    def __init__(self):
        pass

    @gl.public.write
    def submit_claim(
        self, drained_wallet: str, evidence_url: str, statement: str
    ) -> str:
        sender = gl.message.sender_address
        claim_id = f"{drained_wallet}_{sender.as_hex}".lower()

        if claim_id in self.claims:
            raise gl.vm.UserError(
                "Claim already submitted for this wallet by this address"
            )

        claim = Claim(
            id=claim_id,
            claimant=sender,
            drained_wallet=drained_wallet,
            evidence_url=evidence_url,
            statement=statement,
            status="pending",
            verdict_confidence=0,
            verdict_reasoning="",
        )
        self.claims[claim_id] = claim
        self.claimant_claims.get_or_insert_default(sender).append(claim_id)
        return claim_id

    def _judge(self, drained_wallet: str, evidence_url: str, statement: str) -> dict:
        def leader_fn() -> dict:
            web_data = gl.nondet.web.render(evidence_url, mode="text")

            prompt = f"""
You are adjudicating a cryptocurrency fund-recovery claim.

Drained/compromised wallet address: {drained_wallet}

Claimant's statement:
{statement}

Public evidence fetched from {evidence_url}:
\"\"\"
{web_data}
\"\"\"

Decide whether this evidence plausibly demonstrates that the claimant controls
or owns the drained wallet (for example: a signed message from that address,
a social media post referencing that address under the claimant's identity,
or a description of transaction history that matches the address's real
activity). Evidence that is unrelated, generic, or does not mention the
wallet address should not be treated as sufficient.

Respond in JSON:
{{
    "verdict": str,  // "approve", "deny", or "insufficient"
    "confidence": int,  // 0-100
    "reasoning": str  // one or two sentences
}}
It is mandatory that you respond only using the JSON format above,
nothing else. Don't include any other words or characters,
your output must be only JSON without any formatting prefix or suffix.
This result should be perfectly parsable by a JSON parser without errors.
"""
            return gl.nondet.exec_prompt(prompt, response_format="json")

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            my_result = leader_fn()
            return my_result["verdict"] == leaders_res.calldata["verdict"]

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    @gl.public.write
    def adjudicate(self, claim_id: str) -> None:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        claim = self.claims[claim_id]
        if claim.status != "pending":
            raise gl.vm.UserError("Claim already adjudicated")

        verdict = self._judge(claim.drained_wallet, claim.evidence_url, claim.statement)

        verdict_value = str(verdict.get("verdict", "")).lower()
        if verdict_value == "approve":
            claim.status = "approved"
        elif verdict_value == "deny":
            claim.status = "denied"
        else:
            claim.status = "insufficient"

        confidence = int(verdict.get("confidence", 0))
        claim.verdict_confidence = max(0, min(100, confidence))
        claim.verdict_reasoning = str(verdict.get("reasoning", ""))

    @gl.public.view
    def get_claim(self, claim_id: str) -> Claim:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id]

    @gl.public.view
    def get_claims_by_address(self, claimant: str) -> list:
        addr = Address(claimant)
        if addr not in self.claimant_claims:
            return []
        return [self.claims[claim_id] for claim_id in self.claimant_claims[addr]]

    @gl.public.view
    def get_all_claims(self) -> dict:
        return {claim_id: claim for claim_id, claim in self.claims.items()}
