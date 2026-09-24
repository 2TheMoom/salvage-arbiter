# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from genlayer import *

MAX_APPEALS = 3
MAX_CHALLENGES = 3

# keccak256("Transfer(address,address,uint256)") - finds a genuine asset
# movement, not just "a log was emitted" (which an Approval etc. would pass).
TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# secp256k1 curve parameters, for pure-Python ECDSA public-key recovery.
_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP256K1_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_SECP256K1_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

# Not security-critical (only the LLM's verdict is equivalence-checked), so
# a plain public RPC is fine here.
CHAIN_DATA_RPC_URL = "https://ethereum-rpc.publicnode.com"

# A browser-like User-Agent avoids bot-blocking on some public RPC gateways.
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
    status: str  # "pending" | "approved" | "denied" | "insufficient" | "challenged"
    verdict_confidence: u256
    verdict_reasoning: str
    appeal_count: u256
    drained_token: str  # contract address (no "0x"), or "native" for ETH
    drained_amount: u256  # base units of drained_token, or wei if native
    challenge_reason: str
    challenger: str  # address hex (no "0x") of whoever last challenged this claim
    challenge_count: u256


def _extract_address_hex(wallet: str) -> str:
    """Strips an optional chain prefix (e.g. "eth:") and "0x", lowercased."""
    w = wallet.lower()
    if ":" in w:
        w = w.split(":", 1)[1]
    if w.startswith("0x"):
        w = w[2:]
    return w


def _decode_transfer_out(logs: list, wallet_hex: str) -> dict | None:
    """Genuine ERC-20/721 Transfer log naming wallet_hex as sender, else
    None - stricter than "any log exists" (an Approval must not count)."""
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        topic0 = str(topics[0]).lower().removeprefix("0x")
        if topic0 != TRANSFER_TOPIC:
            continue
        from_topic = str(topics[1]).lower().removeprefix("0x")
        if from_topic[-40:] != wallet_hex:
            continue
        to_topic = str(topics[2]).lower().removeprefix("0x")
        destination = to_topic[-40:]
        token = str(log.get("address") or "").lower().removeprefix("0x")
        if len(topics) >= 4:  # ERC-721: tokenId is the 3rd indexed topic
            token_id = int(str(topics[3]), 16)
            return {"token": token, "amount": token_id, "to": destination}
        data = log.get("data") or "0x"
        amount = int(str(data), 16) if data and str(data) != "0x" else 0
        return {"token": token, "amount": amount, "to": destination}
    return None


def _canonical_wallet_key(drained_wallet: str) -> str:
    """Canonical key for a drained wallet - without this, "eth:0xABC" vs
    "0xabc" would be distinct wallets by raw string equality, letting a
    reformatted address slip past the one-approved-claim-per-wallet check."""
    return _extract_address_hex(drained_wallet)


def _ec_inv(a: int, m: int) -> int:
    return pow(a, m - 2, m)


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _SECP256K1_P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * _ec_inv(2 * y1, _SECP256K1_P) % _SECP256K1_P
    else:
        lam = (y2 - y1) * _ec_inv((x2 - x1) % _SECP256K1_P, _SECP256K1_P) % _SECP256K1_P
    x3 = (lam * lam - x1 - x2) % _SECP256K1_P
    y3 = (lam * (x1 - x3) - y1) % _SECP256K1_P
    return (x3, y3)


def _ec_mul(k: int, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_add(addend, addend)
        k >>= 1
    return result


def _ecrecover(digest: bytes, v: int, r: int, s: int) -> bytes:
    """Recovers the 20-byte signer address via pure-Python secp256k1 -
    deliberately not an RPC ecrecover call, since different validators can
    land on different backend nodes and disagree even on this deterministic
    a computation, causing spurious consensus failures."""
    if r <= 0 or r >= _SECP256K1_N or s <= 0 or s >= _SECP256K1_N:
        raise ValueError("invalid signature component")

    recovery_id = v - 27
    x = r
    y_squared = (pow(x, 3, _SECP256K1_P) + 7) % _SECP256K1_P
    y = pow(y_squared, (_SECP256K1_P + 1) // 4, _SECP256K1_P)
    if y % 2 != recovery_id % 2:
        y = _SECP256K1_P - y

    point_r = (x, y)
    e = int.from_bytes(digest, "big") % _SECP256K1_N
    r_inv = _ec_inv(r, _SECP256K1_N)
    generator = (_SECP256K1_GX, _SECP256K1_GY)

    s_r = _ec_mul(s, point_r)
    e_g = _ec_mul(e, generator)
    neg_e_g = (e_g[0], (_SECP256K1_P - e_g[1]) % _SECP256K1_P)
    public_key = _ec_mul(r_inv, _ec_add(s_r, neg_e_g))

    pubkey_bytes = public_key[0].to_bytes(32, "big") + public_key[1].to_bytes(32, "big")
    return Keccak256(pubkey_bytes).digest()[-20:]


class RecoveryArbiter(gl.Contract):
    """Adjudicates fund-recovery claims for compromised wallets.

    A claimant proves wallet control via EIP-191 signature (pure-Python
    ECDSA, not AI) and cites the drain tx. Before the LLM is consulted,
    that citation is confirmed on-chain: a real, successful tx from the
    claimed wallet with a genuine ERC-20/721 Transfer naming it as sender
    (or non-zero native value) - not just any tx hash or log-emitting tx.
    The decoded token/amount/destination bind to the claim, not supplied
    by the claimant. Evidence must reference that tx/destination before
    the LLM judges whether the movement was *unauthorized* (phishing/
    approval exploit) vs. voluntary - occurrence itself is never in
    question by that point. Covers approval/phishing drains, not
    private-key theft (unprovable by any signature scheme - only the
    thief could then sign). Validators reach consensus on both the
    decoded facts and the verdict via the equivalence principle.

    An approved claim isn't final: any address may challenge it once
    (challenge_claim), freezing it until the claimant re-adjudicates
    (resolve_challenge) - rate-limited and capped, not bonded, since this
    contract never moves value itself.

    Result: an on-chain attestation an off-chain recovery flow can require
    before releasing funds - one per wallet.
    """

    claims: TreeMap[str, Claim]
    claimant_claims: TreeMap[Address, DynArray[str]]
    wallet_claims: TreeMap[str, DynArray[str]]
    approved_wallets: TreeMap[str, str]
    challenged_by: TreeMap[str, bool]

    def __init__(self):
        pass

    def _get_claim(self, claim_id: str) -> Claim:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id]

    def _ownership_message(self, drained_wallet: str, claimant: Address) -> str:
        return (
            f"I authorize {claimant.as_hex} to submit a Salvage Arbiter "
            f"recovery claim on behalf of {drained_wallet}."
        )

    def _recover_signer_hex(self, message: str, signature: str) -> str:
        """Recovers the signer of an EIP-191 personal-sign signature and
        returns it as lowercase hex (no 0x), or "" if the signature is
        malformed."""
        message_bytes = message.encode("utf-8")
        prefix = f"\x19Ethereum Signed Message:\n{len(message_bytes)}".encode("utf-8")
        digest = Keccak256(prefix + message_bytes).digest()

        sig_hex = signature.lower()
        if sig_hex.startswith("0x"):
            sig_hex = sig_hex[2:]
        if len(sig_hex) != 130:
            return ""

        try:
            sig_bytes = bytes.fromhex(sig_hex)
        except ValueError:
            return ""

        r = int.from_bytes(sig_bytes[:32], "big")
        s = int.from_bytes(sig_bytes[32:64], "big")
        v = sig_bytes[64]
        if v < 27:
            v += 27
        if v not in (27, 28):
            return ""

        try:
            recovered = _ecrecover(digest, v, r, s)
        except (ValueError, ZeroDivisionError):
            return ""
        return recovered.hex()

    def _verify_ownership_signature(
        self, drained_wallet: str, claimant: Address, signature: str
    ) -> bool:
        wallet_hex = _extract_address_hex(drained_wallet)
        if len(wallet_hex) != 40:
            return False

        message = self._ownership_message(drained_wallet, claimant)
        recovered = self._recover_signer_hex(message, signature)
        return bool(recovered) and recovered == wallet_hex

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
        wallet_key = _canonical_wallet_key(drained_wallet)
        claim_id = f"{wallet_key}_{sender.as_hex}".lower()

        if claim_id in self.claims:
            raise gl.vm.UserError("Claim already submitted for this wallet by this address")

        if wallet_key in self.approved_wallets:
            raise gl.vm.UserError("This wallet already has an approved recovery claim")

        if not self._verify_ownership_signature(drained_wallet, sender, signature):
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
        self.wallet_claims.get_or_insert_default(wallet_key).append(claim_id)
        return claim_id

    def _fetch_chain_balance(self, drained_wallet: str) -> str:
        wallet_hex = _extract_address_hex(drained_wallet)
        if len(wallet_hex) != 40:
            return "unknown (unrecognized wallet address format)"

        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": ["0x" + wallet_hex, "latest"]}
        )
        try:
            resp = gl.nondet.web.post(
                CHAIN_DATA_RPC_URL + "?call=balance", body=body, headers=RPC_HEADERS
            )
            payload = json.loads((resp.body or b"").decode("utf-8"))
            balance_hex = payload.get("result")
            if not balance_hex:
                return "unknown (RPC lookup failed)"
            return f"{int(balance_hex, 16)} wei"
        except (ValueError, AttributeError, TypeError):
            return "unknown (RPC lookup failed)"

    def _fetch_tx_facts(self, tx_hash: str) -> dict | None:
        """Fetches the cited drain tx + receipt; None if not found/failed,
        else from/to/value_wei/block_number/status_success plus
        token_transfer (decoded genuine Transfer naming the sender, not
        just "logs exist")."""
        tx_body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionByHash", "params": [tx_hash]}
        )
        receipt_body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash]}
        )
        try:
            # Query suffix is inert on the real RPC (body-routed); lets tests mock each call distinctly.
            tx_resp = gl.nondet.web.post(
                CHAIN_DATA_RPC_URL + "?call=tx", body=tx_body, headers=RPC_HEADERS
            )
            tx_result = json.loads((tx_resp.body or b"").decode("utf-8")).get("result")
            if not tx_result:
                return None
            from_address = tx_result.get("from")
            if not from_address:
                return None

            receipt_resp = gl.nondet.web.post(
                CHAIN_DATA_RPC_URL + "?call=receipt", body=receipt_body, headers=RPC_HEADERS
            )
            receipt_result = json.loads((receipt_resp.body or b"").decode("utf-8")).get("result")
            if not receipt_result:
                return None

            to_address = tx_result.get("to")
            value_hex = tx_result.get("value")
            block_hex = tx_result.get("blockNumber")
            status_hex = receipt_result.get("status")
            logs = receipt_result.get("logs") or []
            sender_hex = _extract_address_hex(from_address)

            return {
                "from": sender_hex,
                "to": _extract_address_hex(to_address) if to_address else None,
                "value_wei": int(value_hex, 16) if value_hex else 0,
                "block_number": int(block_hex, 16) if block_hex else None,
                "status_success": status_hex != "0x0",  # missing status (pre-Byzantium) = success
                "token_transfer": _decode_transfer_out(logs, sender_hex),
            }
        except (ValueError, AttributeError, TypeError):
            return None

    def _judge(
        self, drained_wallet: str, evidence_url: str, statement: str, drain_tx_hash: str
    ) -> dict:
        def _deny(reason: str) -> dict:
            return {"verdict": "deny", "confidence": 100, "token": "", "amount": 0, "reasoning": reason}

        def leader_fn() -> dict:
            wallet_hex = _extract_address_hex(drained_wallet)
            facts = self._fetch_tx_facts(drain_tx_hash)

            if facts is None:
                return _deny(f"Cited drain transaction {drain_tx_hash} could not be found on-chain.")
            if facts["from"] != wallet_hex:
                return _deny(
                    f"Cited drain transaction {drain_tx_hash} was not sent from the "
                    "claimed wallet - it originated from a different address."
                )
            if not facts["status_success"]:
                return _deny(
                    f"Cited drain transaction {drain_tx_hash} reverted on-chain - "
                    "nothing it attempted actually took effect, so no funds moved."
                )
            transfer = facts["token_transfer"]
            if facts["value_wei"] == 0 and transfer is None:
                return _deny(
                    f"Cited drain transaction {drain_tx_hash} transferred no native value "
                    "and its logs contain no genuine Transfer event naming this wallet as "
                    "sender, so it does not show any asset actually leaving the wallet."
                )

            if transfer is not None:
                drained_token, drained_amount = transfer["token"], transfer["amount"]
                destination_hex = transfer["to"]
            else:
                drained_token, drained_amount = "native", facts["value_wei"]
                destination_hex = facts["to"]

            web_data = gl.nondet.web.render(evidence_url, mode="text")
            web_data_lower = web_data.lower()

            if wallet_hex not in web_data_lower:
                return _deny(
                    f"The evidence at {evidence_url} does not mention the claimed wallet "
                    "address anywhere, so it cannot be authenticated as evidence for this "
                    "specific wallet."
                )

            tx_hash_lower = drain_tx_hash.lower().removeprefix("0x")
            destination_mentioned = destination_hex is not None and destination_hex in web_data_lower
            if tx_hash_lower not in web_data_lower and not destination_mentioned:
                return _deny(
                    f"The evidence at {evidence_url} mentions the wallet but not the "
                    "specific drain transaction or its destination address, so it cannot "
                    "be authenticated as evidence for THIS incident rather than the "
                    "wallet generally."
                )

            balance = self._fetch_chain_balance(drained_wallet)
            destination_display = f"0x{destination_hex}" if destination_hex else "unknown (contract creation)"
            asset_display = (
                f"{drained_amount} wei of native ETH" if drained_token == "native"
                else f"{drained_amount} base units of token 0x{drained_token}"
            )

            prompt = f"""You are adjudicating a cryptocurrency fund-recovery claim on Salvage Arbiter.

Drained/compromised wallet: {drained_wallet}

The claimant already cryptographically proved control of this wallet via a verified
EIP-191 signature - don't re-litigate ownership.

Independently confirmed on-chain (not provided or editable by the claimant): {drain_tx_hash}
is a real, successful tx sent FROM this wallet that moved {asset_display} to
{destination_display}, at block {facts['block_number']}. That movement is a settled fact.
Current balance of {drained_wallet}: {balance}.

NOT yet established: whether this movement was authorized. The key-holder signing this
exact tx is consistent with either (a) an ordinary voluntary transfer/swap/payment, or
(b) a phishing or malicious-approval attack that tricked them into signing away funds.
Judge which the claimant's statement and evidence support - not whether the tx happened
(already settled), but whether it was unauthorized.

Claimant's statement:
{statement}

Supporting evidence fetched from {evidence_url}:
\"\"\"
{web_data}
\"\"\"

Approve only if the statement and evidence together credibly describe this specific
movement as unauthorized (e.g. a phishing site, a malicious token approval, a fake
"support" request) - not merely that the wallet lost funds. Treat evidence that is
generic, unrelated to this transaction, consistent with a voluntary transfer, or
contradicted by the facts above as a reason to deny or mark insufficient.

Respond in JSON only, perfectly parsable, no other text:
{{"verdict": str, "confidence": int, "reasoning": str}}
verdict is "approve", "deny", or "insufficient"; confidence is 0-100; reasoning is one
or two sentences.
"""
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            result["token"] = drained_token
            result["amount"] = drained_amount
            return result

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            my_result = leader_fn()
            theirs = leaders_res.calldata
            # token/amount are on-chain facts, not LLM output - matching them
            # too stops a leader lying about what was verified.
            return (
                my_result["verdict"] == theirs["verdict"]
                and my_result["token"] == theirs["token"]
                and my_result["amount"] == theirs["amount"]
            )

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    def _apply_verdict(self, claim: Claim, wallet_key: str, verdict: dict, clear_wallet_on_reject: bool = False) -> None:
        verdict_value = str(verdict.get("verdict", "")).lower()
        if verdict_value == "approve":
            claim.status = "approved"
            self.approved_wallets[wallet_key] = claim.id
        else:
            claim.status = "denied" if verdict_value == "deny" else "insufficient"
            if clear_wallet_on_reject and self.approved_wallets.get(wallet_key) == claim.id:
                del self.approved_wallets[wallet_key]

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

        wallet_key = _canonical_wallet_key(claim.drained_wallet)
        existing_approved_id = self.approved_wallets.get(wallet_key)
        if existing_approved_id is not None and existing_approved_id != claim.id:
            claim.status = "denied"
            claim.verdict_confidence = 100
            claim.verdict_reasoning = (
                "This wallet already has a different approved recovery claim "
                f"({existing_approved_id}); competing claims cannot also be approved."
            )
            return

        verdict = self._judge(
            claim.drained_wallet, claim.evidence_url, claim.statement, claim.drain_tx_hash
        )
        self._apply_verdict(claim, wallet_key, verdict)

    @gl.public.write
    def challenge_claim(self, claim_id: str, reason: str) -> None:
        """Permissionless: freezes an approved claim pending re-adjudication
        (e.g. a "drain" that was really voluntary). Rate-limited/capped, not
        bonded, since this contract never moves value. "challenged" !=
        "approved", which alone blocks RecoveryReleaseVault.release()."""
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
        claim.challenger = _extract_address_hex(challenger.as_hex)
        claim.challenge_count += 1

    @gl.public.write
    def resolve_challenge(self, claim_id: str) -> None:
        """Re-runs full validator consensus on a challenged claim.
        Claimant-only - they already proved wallet control at submission.
        Approves overrule the challenge back to "approved"; otherwise the
        wallet's approved-claim slot is freed for a new claim."""
        claim = self._get_claim(claim_id)
        if gl.message.sender_address != claim.claimant:
            raise gl.vm.UserError("Only the claimant can resolve a challenge")
        if claim.status != "challenged":
            raise gl.vm.UserError("This claim is not currently challenged")

        wallet_key = _canonical_wallet_key(claim.drained_wallet)
        verdict = self._judge(
            claim.drained_wallet, claim.evidence_url, claim.statement, claim.drain_tx_hash
        )
        self._apply_verdict(claim, wallet_key, verdict, clear_wallet_on_reject=True)

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
        """Narrow, primitive-typed getter for downstream consumers, e.g.
        contracts/recovery_release_vault.py."""
        return self._get_claim(claim_id).status

    @gl.public.view
    def get_claim_claimant(self, claim_id: str) -> Address:
        """Companion to get_claim_status: who to pay out."""
        return self._get_claim(claim_id).claimant

    @gl.public.view
    def get_claim_drained_asset(self, claim_id: str) -> str:
        """Which asset a downstream release should be denominated in -
        "native", a token address, or "" if never verified."""
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
        wallet_key = _canonical_wallet_key(drained_wallet)
        if wallet_key not in self.wallet_claims:
            return []
        return [self.claims[claim_id] for claim_id in self.wallet_claims[wallet_key]]

    @gl.public.view
    def get_all_claims(self) -> dict:
        return {claim_id: claim for claim_id, claim in self.claims.items()}
