# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from genlayer import *

MAX_APPEALS = 3
MAX_CHALLENGES = 3

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

CHAIN_DATA_RPC_URL = "https://ethereum-rpc.publicnode.com"

RPC_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


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
    status: str  # pending|approved|denied|insufficient|challenged
    verdict_confidence: u256
    verdict_reasoning: str
    appeal_count: u256
    drained_token: str  # token addr, or "native"
    drained_amount: u256
    challenge_reason: str
    challenger: str  # hex, no "0x"
    challenge_count: u256


def _ahex(w: str) -> str:
    """Strips optional chain prefix (e.g. "eth:") and "0x", lowercased."""
    w = w.lower()
    if ":" in w:
        w = w.split(":", 1)[1]
    return w[2:] if w.startswith("0x") else w


def _xfer_out(logs: list, wh: str) -> dict | None:
    """Genuine ERC-20/721 Transfer log naming wh as sender, or None."""
    for log in logs:
        t = log.get("topics") or []
        if len(t) < 3 or str(t[0]).lower().removeprefix("0x") != TRANSFER_TOPIC:
            continue
        if str(t[1]).lower().removeprefix("0x")[-40:] != wh:
            continue
        dst = str(t[2]).lower().removeprefix("0x")[-40:]
        tok = str(log.get("address") or "").lower().removeprefix("0x")
        if len(t) >= 4:  # ERC-721: tokenId is the 3rd indexed topic
            return {"token": tok, "amount": int(str(t[3]), 16), "to": dst}
        d = log.get("data") or "0x"
        amt = int(str(d), 16) if d and str(d) != "0x" else 0
        return {"token": tok, "amount": amt, "to": dst}
    return None


def _wkey(drained_wallet: str) -> str:
    """Canonical wallet key, so "eth:0xABC" and "0xabc" dedupe as one."""
    return _ahex(drained_wallet)


class RecoveryArbiter(gl.Contract):
    """Adjudicates fund-recovery claims for compromised wallets.

    Ownership: EIP-191 signature via cross-contract call to
    SignatureVerifier (split out for Bradbury's deploy gas ceiling). Drain
    proof: a real, successful tx from the claimed wallet with a genuine
    ERC-20/721 Transfer naming it as sender (or non-zero native value) -
    decoded token/amount/destination bind to the claim, not claimant-
    supplied. Evidence must reference that tx/destination before the LLM
    judges whether the movement was *unauthorized* vs. voluntary -
    occurrence is settled by then. Covers approval/phishing drains, not
    private-key theft (unprovable by any signature scheme). Validators
    reach consensus on both the decoded facts and the verdict.

    An approved claim isn't final: any address may challenge it once,
    freezing it until the claimant re-adjudicates. Result: an on-chain
    attestation an off-chain recovery flow can require before releasing
    funds - one per wallet.
    """

    claims: TreeMap[str, Claim]
    claimant_claims: TreeMap[Address, DynArray[str]]
    wallet_claims: TreeMap[str, DynArray[str]]
    approved_wallets: TreeMap[str, str]
    challenged_by: TreeMap[str, bool]
    verifier_address: Address

    def __init__(self, verifier_address: str):
        self.verifier_address = Address(verifier_address)

    def _get_claim(self, claim_id: str) -> Claim:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id]

    @gl.public.write
    def submit_claim(
        self,
        drained_wallet: str,
        evidence_url: str,
        statement: str,
        signature: str,
        drain_tx_hash: str,
    ) -> str:
        sender = gl.message.sender_address
        wk = _wkey(drained_wallet)
        claim_id = f"{wk}_{sender.as_hex}".lower()

        if claim_id in self.claims:
            raise gl.vm.UserError("Claim already submitted for this wallet by this address")

        if wk in self.approved_wallets:
            raise gl.vm.UserError("This wallet already has an approved recovery claim")

        verifier = gl.get_contract_at(self.verifier_address)
        if not verifier.view().verify_ownership(drained_wallet, sender, signature):
            raise gl.vm.UserError("Signature does not prove control of the drained wallet")

        claim = Claim(
            id=claim_id,
            claimant=sender,
            drained_wallet=drained_wallet,
            evidence_url=evidence_url,
            statement=statement,
            signature=signature,
            drain_tx_hash=drain_tx_hash,
            status="pending",
            verdict_confidence=0,
            verdict_reasoning="",
            appeal_count=0,
            drained_token="",
            drained_amount=0,
            challenge_reason="",
            challenger="",
            challenge_count=0,
        )
        self.claims[claim_id] = claim
        self.claimant_claims.get_or_insert_default(sender).append(claim_id)
        self.wallet_claims.get_or_insert_default(wk).append(claim_id)
        return claim_id

    def _fetch_tx_facts(self, tx_hash: str) -> dict | None:
        """Cited drain tx + receipt facts, or None if not found/failed."""
        tx_body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionByHash", "params": [tx_hash]}
        )
        receipt_body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash]}
        )
        try:
            # Query suffix is inert on real RPC; lets tests mock each call distinctly.
            r1 = gl.nondet.web.post(CHAIN_DATA_RPC_URL + "?call=tx", body=tx_body, headers=RPC_HEADERS)
            tx = json.loads((r1.body or b"").decode("utf-8")).get("result")
            if not tx or not tx.get("from"):
                return None

            r2 = gl.nondet.web.post(CHAIN_DATA_RPC_URL + "?call=receipt", body=receipt_body, headers=RPC_HEADERS)
            rc = json.loads((r2.body or b"").decode("utf-8")).get("result")
            if not rc:
                return None

            to_addr = tx.get("to")
            value_hex = tx.get("value")
            block_hex = tx.get("blockNumber")
            status_hex = rc.get("status")
            logs = rc.get("logs") or []
            sh = _ahex(tx["from"])

            return {
                "from": sh,
                "to": _ahex(to_addr) if to_addr else None,
                "value_wei": int(value_hex, 16) if value_hex else 0,
                "block_number": int(block_hex, 16) if block_hex else None,
                "status_success": status_hex != "0x0",  # missing status (pre-Byzantium) = success
                "token_transfer": _xfer_out(logs, sh),
            }
        except (ValueError, AttributeError, TypeError):
            return None

    def _judge(
        self, drained_wallet: str, evidence_url: str, statement: str, drain_tx_hash: str
    ) -> dict:
        def _deny(reason: str) -> dict:
            return {"verdict": "deny", "confidence": 100, "token": "", "amount": 0, "reasoning": reason}

        def leader_fn() -> dict:
            wh = _ahex(drained_wallet)
            facts = self._fetch_tx_facts(drain_tx_hash)

            if facts is None:
                return _deny(f"Cited drain transaction {drain_tx_hash} could not be found on-chain.")
            if facts["from"] != wh:
                return _deny(f"Cited drain transaction {drain_tx_hash} was not sent from the claimed wallet.")
            if not facts["status_success"]:
                return _deny(f"Cited drain transaction {drain_tx_hash} reverted on-chain - no funds moved.")
            transfer = facts["token_transfer"]
            if facts["value_wei"] == 0 and transfer is None:
                return _deny(
                    f"Cited drain transaction {drain_tx_hash} moved no native value and its logs "
                    "contain no genuine Transfer event naming this wallet as sender."
                )

            if transfer is not None:
                token, amount = transfer["token"], transfer["amount"]
                dest = transfer["to"]
            else:
                token, amount = "native", facts["value_wei"]
                dest = facts["to"]

            web_data = gl.nondet.web.render(evidence_url, mode="text")
            web_lower = web_data.lower()

            if wh not in web_lower:
                return _deny(f"The evidence at {evidence_url} does not mention the claimed wallet.")

            tx_lower = drain_tx_hash.lower().removeprefix("0x")
            dest_mentioned = dest is not None and dest in web_lower
            if tx_lower not in web_lower and not dest_mentioned:
                return _deny(
                    f"The evidence at {evidence_url} mentions the wallet but not the specific "
                    "drain transaction, so it cannot be authenticated as evidence for THIS incident."
                )

            dest_display = f"0x{dest}" if dest else "unknown (contract creation)"
            asset_display = (
                f"{amount} wei of native ETH" if token == "native"
                else f"{amount} base units of token 0x{token}"
            )

            prompt = f"""You are adjudicating a cryptocurrency fund-recovery claim on Salvage Arbiter.

Drained/compromised wallet: {drained_wallet}

Claimant already proved control of this wallet via a verified EIP-191 signature - don't
re-litigate ownership.

Confirmed on-chain (not editable by claimant): {drain_tx_hash} is a real, successful tx
sent FROM this wallet that moved {asset_display} to {dest_display}, at block
{facts['block_number']}. That movement is settled fact.

NOT established: whether this movement was authorized. The key-holder signing this exact
tx is consistent with (a) an ordinary voluntary transfer, or (b) a phishing/malicious-
approval attack that tricked them into signing away funds. Judge which the claimant's
statement and evidence support - not whether the tx happened (settled), but whether it
was unauthorized.

Claimant's statement:
{statement}

Supporting evidence fetched from {evidence_url}:
\"\"\"
{web_data}
\"\"\"

Approve only if the statement and evidence together credibly describe this movement as
unauthorized (e.g. phishing, a malicious token approval, a fake "support" request) - not
merely that the wallet lost funds. Treat generic evidence, evidence unrelated to this
tx, evidence consistent with a voluntary transfer, or evidence contradicted by the facts
above as a reason to deny or mark insufficient.

Respond in JSON only, perfectly parsable, no other text:
{{"verdict": str, "confidence": int, "reasoning": str}}
verdict is "approve"/"deny"/"insufficient"; confidence is 0-100; reasoning one or two
sentences.
"""
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            result["token"] = token
            result["amount"] = amount
            return result

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = leader_fn()
            theirs = leaders_res.calldata
            # token/amount are on-chain facts, not LLM output - matching them
            # too stops a leader lying about what was verified.
            return (
                mine["verdict"] == theirs["verdict"]
                and mine["token"] == theirs["token"]
                and mine["amount"] == theirs["amount"]
            )

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    def _apply_verdict(self, claim: Claim, wk: str, verdict: dict, clear_on_reject: bool = False) -> None:
        v = str(verdict.get("verdict", "")).lower()
        if v == "approve":
            claim.status = "approved"
            self.approved_wallets[wk] = claim.id
        else:
            claim.status = "denied" if v == "deny" else "insufficient"
            if clear_on_reject and self.approved_wallets.get(wk) == claim.id:
                del self.approved_wallets[wk]

        confidence = int(verdict.get("confidence", 0))
        claim.verdict_confidence = max(0, min(100, confidence))
        claim.verdict_reasoning = str(verdict.get("reasoning", ""))
        claim.drained_token = str(verdict.get("token", ""))
        claim.drained_amount = int(verdict.get("amount", 0))

    @gl.public.write
    def adjudicate(self, claim_id: str) -> None:
        claim = self._get_claim(claim_id)
        if claim.status != "pending":
            raise gl.vm.UserError("Claim already adjudicated")

        wk = _wkey(claim.drained_wallet)
        existing = self.approved_wallets.get(wk)
        if existing is not None and existing != claim.id:
            claim.status = "denied"
            claim.verdict_confidence = 100
            claim.verdict_reasoning = (
                f"This wallet already has a different approved recovery claim ({existing})."
            )
            return

        verdict = self._judge(
            claim.drained_wallet, claim.evidence_url, claim.statement, claim.drain_tx_hash
        )
        self._apply_verdict(claim, wk, verdict)

    @gl.public.write
    def challenge_claim(self, claim_id: str, reason: str) -> None:
        """Permissionless: freezes an approved claim pending re-adjudication."""
        claim = self._get_claim(claim_id)
        if claim.status != "approved":
            raise gl.vm.UserError("Only an approved claim can be challenged")

        if claim.challenge_count >= MAX_CHALLENGES:
            raise gl.vm.UserError(f"Maximum of {MAX_CHALLENGES} challenges reached")

        challenger = gl.message.sender_address
        dedupe_key = f"{claim_id}_{challenger.as_hex}".lower()
        if dedupe_key in self.challenged_by:
            raise gl.vm.UserError("This address has already challenged this claim")
        self.challenged_by[dedupe_key] = True

        claim.status = "challenged"
        claim.challenge_reason = reason
        claim.challenger = _ahex(challenger.as_hex)
        claim.challenge_count += 1

    @gl.public.write
    def resolve_challenge(self, claim_id: str) -> None:
        """Re-runs consensus on a challenged claim. Claimant-only."""
        claim = self._get_claim(claim_id)
        if gl.message.sender_address != claim.claimant:
            raise gl.vm.UserError("Only the claimant can resolve a challenge")
        if claim.status != "challenged":
            raise gl.vm.UserError("This claim is not currently challenged")

        wk = _wkey(claim.drained_wallet)
        verdict = self._judge(
            claim.drained_wallet, claim.evidence_url, claim.statement, claim.drain_tx_hash
        )
        self._apply_verdict(claim, wk, verdict, clear_on_reject=True)

    @gl.public.write
    def submit_appeal(
        self, claim_id: str, evidence_url: str, statement: str, drain_tx_hash: str
    ) -> None:
        claim = self._get_claim(claim_id)

        if gl.message.sender_address != claim.claimant:
            raise gl.vm.UserError("Only the claimant can appeal this claim")

        if claim.status == "pending":
            raise gl.vm.UserError("Claim is still awaiting its first adjudication")

        if claim.status == "approved":
            raise gl.vm.UserError("Approved claims cannot be appealed")

        if claim.status == "challenged":
            raise gl.vm.UserError("This claim is under challenge - use resolve_challenge, not submit_appeal")

        if claim.appeal_count >= MAX_APPEALS:
            raise gl.vm.UserError(f"Maximum of {MAX_APPEALS} appeals reached")

        claim.evidence_url = evidence_url
        claim.statement = statement
        claim.drain_tx_hash = drain_tx_hash
        claim.status = "pending"
        claim.verdict_confidence = 0
        claim.verdict_reasoning = ""
        claim.appeal_count += 1

    @gl.public.view
    def get_claim(self, claim_id: str) -> Claim:
        return self._get_claim(claim_id)

    @gl.public.view
    def get_claim_status(self, claim_id: str) -> str:
        """Narrow getter for downstream consumers."""
        return self._get_claim(claim_id).status

    @gl.public.view
    def get_claim_claimant(self, claim_id: str) -> Address:
        """Companion to get_claim_status: who to pay out."""
        return self._get_claim(claim_id).claimant

    @gl.public.view
    def get_claim_drained_asset(self, claim_id: str) -> str:
        """Asset: "native", a token address, or "" if never verified."""
        return self._get_claim(claim_id).drained_token

    @gl.public.view
    def get_claim_drained_amount(self, claim_id: str) -> u256:
        """Companion to get_claim_drained_asset: the verified amount."""
        return self._get_claim(claim_id).drained_amount

    @gl.public.view
    def get_claims_by_address(self, claimant: str) -> list:
        addr = Address(claimant)
        if addr not in self.claimant_claims:
            return []
        return [self.claims[claim_id] for claim_id in self.claimant_claims[addr]]

    @gl.public.view
    def get_claims_for_wallet(self, drained_wallet: str) -> list:
        wk = _wkey(drained_wallet)
        if wk not in self.wallet_claims:
            return []
        return [self.claims[claim_id] for claim_id in self.wallet_claims[wk]]

    @gl.public.view
    def get_all_claims(self) -> dict:
        return {claim_id: claim for claim_id, claim in self.claims.items()}
