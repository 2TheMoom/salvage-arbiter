# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from genlayer import *

MAX_APPEALS = 3
MAX_CHALLENGES = 3

# keccak256("Transfer(address,address,uint256)") - the standard ERC-20/721
# Transfer event signature. Used to find a genuine asset movement in a
# transaction's logs, rather than treating "any log was emitted" as proof
# something moved (an Approval, an unrelated Transfer, a governance vote,
# or any other log-emitting call would otherwise pass just as easily).
TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# secp256k1 curve parameters, for pure-Python ECDSA public-key recovery.
_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP256K1_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_SECP256K1_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

# Chain-fact lookups aren't security-critical the way signature verification
# is (the LLM's equivalence check only compares its final verdict string,
# not this value byte-for-byte), so a public RPC via the equivalence
# principle is fine here.
CHAIN_DATA_RPC_URL = "https://ethereum-rpc.publicnode.com"

# Public RPC gateways can reject requests without a browser-like User-Agent
# as bot traffic (observed live: Cloudflare's did this).
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
    """Finds a genuine ERC-20/721 Transfer log whose `from` topic decodes
    to wallet_hex; returns its token, amount (or tokenId for an NFT), and
    destination, or None. Deliberately stricter than "any log exists" -
    an Approval, an unrelated Transfer, or any other log-emitting call
    must not count as evidence this wallet lost an asset."""
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
        if len(topics) >= 4:
            # ERC-721: tokenId is the 3rd indexed topic, no data payload.
            token_id = int(str(topics[3]), 16)
            return {"token": token, "amount": token_id, "to": destination}
        data = log.get("data") or "0x"
        amount = int(str(data), 16) if data and str(data) != "0x" else 0
        return {"token": token, "amount": amount, "to": destination}
    return None


def _canonical_wallet_key(drained_wallet: str) -> str:
    """Canonical form used for every internal key derived from a drained
    wallet (claim_id, approved_wallets, wallet_claims). Without this, the
    SAME real wallet submitted as "eth:0xABC..." vs "0xabc..." vs
    "ETH:0xAbC..." would be treated as distinct wallets by raw string
    equality, letting a second claim for an already-approved wallet slip
    past the "one approved claim per wallet" check just by reformatting the
    address string."""
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
    """Recovers the 20-byte Ethereum address that produced an ECDSA
    signature over `digest`, via pure-Python secp256k1 arithmetic.

    This is deliberately NOT delegated to an external RPC's ecrecover
    precompile: live testing showed that calling out to a public RPC via
    GenVM's equivalence principle for this specific check is unreliable -
    different validators can land on different backend nodes behind a
    provider's load balancer, and even a byte-for-byte deterministic
    computation like ecrecover can come back inconsistent across them,
    causing spurious consensus failures. A pure computation has no such
    failure mode: every validator runs the identical bytecode on the
    identical input and always agrees.
    """
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
    ECDSA, not AI) and cites the drain transaction. Before the LLM is
    consulted, that citation is independently confirmed on-chain: a real,
    successful tx from the claimed wallet whose receipt contains a genuine
    ERC-20/721 Transfer naming that wallet as sender (or non-zero native
    value) - not just any tx hash, and not just any log-emitting tx. The
    decoded token/amount/destination are bound to the claim, not supplied
    by the claimant, so a downstream release can be checked against what
    was actually verified. Evidence must reference that specific tx or
    destination before the LLM judges whether the claimant's account
    credibly shows the movement was *unauthorized* (phishing/approval
    exploit) rather than voluntary - the movement itself is never in
    question by that point. Covers approval/phishing drains, not
    private-key theft (unprovable by any signature scheme, since only the
    thief could then sign). Validators reach consensus on both the
    decoded facts and the verdict via the equivalence principle.

    An approved claim isn't final: any address may challenge it once
    (challenge_claim), freezing it against release until the claimant
    triggers a fresh re-adjudication (resolve_challenge). Rate-limited per
    address and capped (MAX_CHALLENGES) rather than bonded, since this
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
            raise gl.vm.UserError(
                "Claim already submitted for this wallet by this address"
            )

        if wallet_key in self.approved_wallets:
            raise gl.vm.UserError(
                "This wallet already has an approved recovery claim"
            )

        if not self._verify_ownership_signature(drained_wallet, sender, signature):
            raise gl.vm.UserError(
                "Signature does not prove control of the drained wallet"
            )

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
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBalance",
                "params": ["0x" + wallet_hex, "latest"],
            }
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
        """Fetches the cited drain tx + receipt. Returns None if it
        doesn't exist or a lookup fails, else a dict: from/to (hex, no
        "0x"), value_wei, block_number, status_success (False = reverted),
        and token_transfer - the decoded {"token","amount","to"} of a
        genuine Transfer naming this tx's sender, or None. token_transfer
        is deliberately not just "logs exist" - an Approval or an
        unrelated Transfer must not count as this wallet losing an asset.
        """
        tx_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionByHash",
                "params": [tx_hash],
            }
        )
        receipt_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash],
            }
        )
        try:
            # The query suffix has no effect on the real RPC call (JSON-RPC
            # routing is entirely body-based) - it only lets tests mock each
            # call distinctly, since they share a base URL.
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
                # Missing status (pre-Byzantium chains) is treated as success -
                # only an explicit "0x0" counts as a revert.
                "status_success": status_hex != "0x0",
                "token_transfer": _decode_transfer_out(logs, sender_hex),
            }
        except (ValueError, AttributeError, TypeError):
            return None

    def _judge(
        self, drained_wallet: str, evidence_url: str, statement: str, drain_tx_hash: str
    ) -> dict:
        def leader_fn() -> dict:
            wallet_hex = _extract_address_hex(drained_wallet)
            facts = self._fetch_tx_facts(drain_tx_hash)

            if facts is None:
                return {
                    "verdict": "deny", "confidence": 100, "token": "", "amount": 0,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} could not be found on-chain."
                    ),
                }
            if facts["from"] != wallet_hex:
                return {
                    "verdict": "deny", "confidence": 100, "token": "", "amount": 0,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} was not sent from the "
                        "claimed wallet - it originated from a different address."
                    ),
                }
            if not facts["status_success"]:
                return {
                    "verdict": "deny", "confidence": 100, "token": "", "amount": 0,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} reverted on-chain - "
                        "nothing it attempted actually took effect, so no funds moved."
                    ),
                }
            transfer = facts["token_transfer"]
            if facts["value_wei"] == 0 and transfer is None:
                return {
                    "verdict": "deny", "confidence": 100, "token": "", "amount": 0,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} transferred no native "
                        "value and its logs contain no genuine Transfer event naming this "
                        "wallet as sender, so it does not show any asset actually leaving "
                        "the wallet."
                    ),
                }

            if transfer is not None:
                drained_token, drained_amount = transfer["token"], transfer["amount"]
                destination_hex = transfer["to"]
            else:
                drained_token, drained_amount = "native", facts["value_wei"]
                destination_hex = facts["to"]

            web_data = gl.nondet.web.render(evidence_url, mode="text")
            web_data_lower = web_data.lower()

            if wallet_hex not in web_data_lower:
                return {
                    "verdict": "deny", "confidence": 100, "token": "", "amount": 0,
                    "reasoning": (
                        f"The evidence at {evidence_url} does not mention the claimed "
                        "wallet address anywhere, so it cannot be authenticated as "
                        "evidence for this specific wallet."
                    ),
                }

            tx_hash_lower = drain_tx_hash.lower().removeprefix("0x")
            destination_mentioned = destination_hex is not None and destination_hex in web_data_lower
            if tx_hash_lower not in web_data_lower and not destination_mentioned:
                return {
                    "verdict": "deny", "confidence": 100, "token": "", "amount": 0,
                    "reasoning": (
                        f"The evidence at {evidence_url} mentions the wallet but not the "
                        "specific drain transaction or its destination address, so it "
                        "cannot be authenticated as evidence for THIS incident rather "
                        "than the wallet generally."
                    ),
                }

            balance = self._fetch_chain_balance(drained_wallet)
            destination_display = f"0x{destination_hex}" if destination_hex else "unknown (contract creation)"
            asset_display = (
                f"{drained_amount} wei of native ETH" if drained_token == "native"
                else f"{drained_amount} base units of token 0x{drained_token}"
            )

            prompt = f"""
You are adjudicating a cryptocurrency fund-recovery claim on Salvage Arbiter.

Drained/compromised wallet address: {drained_wallet}

The claimant has already cryptographically proven they control (or retain signing
access to) this wallet via a verified EIP-191 signature - do not re-litigate
ownership, that part is settled by cryptography, not by you.

It has been independently confirmed, directly from a public RPC and not provided or
editable by the claimant, that {drain_tx_hash} is a real, successful transaction sent
FROM this wallet that moved {asset_display} to {destination_display}. That specific
movement is a settled fact - do not re-litigate whether it happened.

What has NOT been established is whether this movement was authorized by the
wallet's owner. The wallet's own key-holder signing this exact transaction is
consistent with either: (a) an ordinary voluntary transfer, swap, or payment they
meant to make, or (b) a phishing or malicious-approval attack that tricked them into
signing away funds without realizing it. Your job is to judge which of these the
claimant's statement and evidence actually support - not whether a transaction
occurred (already confirmed above), but whether it was unauthorized.

Claimant's statement:
{statement}

Supporting evidence fetched from {evidence_url}:
\"\"\"
{web_data}
\"\"\"

Independently verified on-chain facts (authoritative, fetched directly from a public
RPC - not provided or editable by the claimant):
- {drain_tx_hash}: confirmed sent from {drained_wallet}, succeeded on-chain (did not
  revert), and moved {asset_display} to {destination_display}.
- Block number: {facts['block_number']}
- Current balance of {drained_wallet}: {balance}

Approve only if the statement and evidence together credibly describe this specific
movement as unauthorized (e.g. a phishing site, a malicious token approval, a fake
"support" request) - not merely that the wallet lost funds. Treat evidence that is
generic, unrelated to this specific transaction, consistent with an ordinary
voluntary transfer, or contradicted by the on-chain facts above (for example,
describing an urgent unresolved drain when the balance shows otherwise) as a reason
to deny or mark insufficient.

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
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            result["token"] = drained_token
            result["amount"] = drained_amount
            return result

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            my_result = leader_fn()
            theirs = leaders_res.calldata
            # token/amount are decoded on-chain facts, not LLM output - every
            # honest validator derives the same values, so requiring them to
            # match too stops a leader lying about what was verified.
            return (
                my_result["verdict"] == theirs["verdict"]
                and my_result["token"] == theirs["token"]
                and my_result["amount"] == theirs["amount"]
            )

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    @gl.public.write
    def adjudicate(self, claim_id: str) -> None:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        claim = self.claims[claim_id]
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

        verdict_value = str(verdict.get("verdict", "")).lower()
        if verdict_value == "approve":
            claim.status = "approved"
            self.approved_wallets[wallet_key] = claim.id
        elif verdict_value == "deny":
            claim.status = "denied"
        else:
            claim.status = "insufficient"

        confidence = int(verdict.get("confidence", 0))
        claim.verdict_confidence = max(0, min(100, confidence))
        claim.verdict_reasoning = str(verdict.get("reasoning", ""))
        claim.drained_token = str(verdict.get("token", ""))
        claim.drained_amount = int(verdict.get("amount", 0))

    @gl.public.write
    def challenge_claim(self, claim_id: str, reason: str) -> None:
        """Freezes an approved claim pending re-adjudication. Permissionless
        - anyone who spots a wrongly-approved claim (e.g. a "drain" that
        was really a voluntary transfer) can stop a release before it
        happens. Rate-limited per address and capped (MAX_CHALLENGES)
        rather than bonded, since this contract never moves value itself.
        A "challenged" status is no longer "approved", which alone blocks
        RecoveryReleaseVault's release() without this contract needing to
        know anything about what sits downstream.
        """
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        claim = self.claims[claim_id]
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
        """Re-runs full validator consensus on a challenged claim, exactly
        as the first adjudication did. Claimant-only - they already proved
        wallet control at submission. If consensus still approves, the
        challenge is overruled and status returns to "approved"; if not,
        the wallet's approved-claim slot is freed for a new claim. Honest
        limitation: no cooldown before resolving, so this doesn't force a
        cooling-off period the way a real dispute process might - though a
        claimant expecting to lose has no reason to delay anyway.
        """
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        claim = self.claims[claim_id]
        if gl.message.sender_address != claim.claimant:
            raise gl.vm.UserError("Only the claimant can resolve a challenge")
        if claim.status != "challenged":
            raise gl.vm.UserError("This claim is not currently challenged")

        wallet_key = _canonical_wallet_key(claim.drained_wallet)
        verdict = self._judge(
            claim.drained_wallet, claim.evidence_url, claim.statement, claim.drain_tx_hash
        )

        verdict_value = str(verdict.get("verdict", "")).lower()
        if verdict_value == "approve":
            claim.status = "approved"
            self.approved_wallets[wallet_key] = claim.id
        else:
            claim.status = "denied" if verdict_value == "deny" else "insufficient"
            existing = self.approved_wallets.get(wallet_key)
            if existing == claim.id:
                del self.approved_wallets[wallet_key]

        confidence = int(verdict.get("confidence", 0))
        claim.verdict_confidence = max(0, min(100, confidence))
        claim.verdict_reasoning = str(verdict.get("reasoning", ""))
        claim.drained_token = str(verdict.get("token", ""))
        claim.drained_amount = int(verdict.get("amount", 0))

    @gl.public.write
    def submit_appeal(
        self, claim_id: str, evidence_url: str, statement: str, drain_tx_hash: str
    ) -> None:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        claim = self.claims[claim_id]

        if gl.message.sender_address != claim.claimant:
            raise gl.vm.UserError("Only the claimant can appeal this claim")

        if claim.status == "pending":
            raise gl.vm.UserError("Claim is still awaiting its first adjudication")

        if claim.status == "approved":
            raise gl.vm.UserError("Approved claims cannot be appealed")

        if claim.status == "challenged":
            raise gl.vm.UserError(
                "This claim is under challenge - use resolve_challenge, not submit_appeal"
            )

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
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id]

    @gl.public.view
    def get_claim_status(self, claim_id: str) -> str:
        """Narrow, primitive-typed getter for downstream consumers (e.g. a
        recovery/escrow contract deciding whether to release funds) - a
        single str is trivial to consume via a cross-contract call, unlike
        decoding the full Claim dataclass. See contracts/recovery_release_vault.py
        for a working example consumer."""
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id].status

    @gl.public.view
    def get_claim_claimant(self, claim_id: str) -> Address:
        """Companion to get_claim_status: who to pay out to once a
        downstream consumer confirms the claim is approved."""
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id].claimant

    @gl.public.view
    def get_claim_drained_asset(self, claim_id: str) -> str:
        """Companion to get_claim_status: which asset a downstream release
        should be denominated in - "native", a token contract address, or
        "" if no asset was ever verified for this claim (e.g. it was
        auto-denied before a transfer could be decoded)."""
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id].drained_token

    @gl.public.view
    def get_claim_drained_amount(self, claim_id: str) -> u256:
        """Companion to get_claim_drained_asset: the verified amount, in
        the drained asset's own base units (wei for native, or the
        token's smallest unit / tokenId for a Transfer)."""
        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")
        return self.claims[claim_id].drained_amount

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
