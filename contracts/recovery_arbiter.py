# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from genlayer import *

MAX_APPEALS = 3

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
    status: str  # "pending" | "approved" | "denied" | "insufficient"
    verdict_confidence: u256
    verdict_reasoning: str
    appeal_count: u256


def _extract_address_hex(wallet: str) -> str:
    """Strips an optional chain prefix (e.g. "eth:") and "0x", lowercased."""
    w = wallet.lower()
    if ":" in w:
        w = w.split(":", 1)[1]
    if w.startswith("0x"):
        w = w[2:]
    return w


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

    A claimant cryptographically proves control of a drained wallet via an
    EIP-191 signed message (verified through pure-Python ECDSA recovery,
    not AI judgment) and cites the specific transaction that drained it.
    Before the LLM is ever consulted, that citation is independently
    confirmed on-chain: the transaction must be a real, successful
    transaction sent FROM the claimed wallet that actually moved an asset
    (non-zero native value, or at least one emitted event log, so a token
    transfer counts too) - not merely a transaction hash that happens to
    exist. The cited incident's destination, value, and block are then fed
    to validators as authoritative facts alongside supporting evidence,
    which must itself reference the specific transaction or its
    destination (not just the wallet) to be authenticated as evidence for
    THIS incident. This model covers approval/phishing drains, where the
    victim still holds their key but was tricked into signing away funds,
    not private-key theft (which no signature-based scheme can prove,
    since only the thief could then sign anything). Validators reach
    consensus on a verdict via the equivalence principle. The result is an
    on-chain attestation that an off-chain recovery flow (e.g. Salvage's
    cross-chain rescue router) can require before releasing funds - one
    attestation per wallet, since an already-approved wallet cannot
    receive competing claims.
    """

    claims: TreeMap[str, Claim]
    claimant_claims: TreeMap[Address, DynArray[str]]
    wallet_claims: TreeMap[str, DynArray[str]]
    approved_wallets: TreeMap[str, str]

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
        """Fetches the cited drain transaction plus its receipt and returns
        the on-chain facts needed to confirm it's a real, successful asset
        movement out of the claimed wallet - not just that some transaction
        with this hash exists. Returns None if the transaction doesn't
        exist or either lookup fails.

        Returns a dict with:
        - from: sender address, canonicalized (lowercase, no "0x")
        - to: recipient address, canonicalized, or None
        - value_wei: native value transferred, as int
        - block_number: int, or None
        - status_success: bool - False means the transaction reverted, so
          nothing it appears to do actually took effect on-chain
        - log_count: number of event logs emitted (a non-empty log list is
          consistent with a token Transfer even when native value_wei is 0,
          which is the common case for an ERC-20 drain)

        Checking only 'from' (as an earlier version of this contract did)
        let a claimant cite ANY transaction they'd ever sent - including a
        zero-value, failed, or unrelated one - as "proof" a drain happened,
        without ever confirming value actually moved.
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

            return {
                "from": _extract_address_hex(from_address),
                "to": _extract_address_hex(to_address) if to_address else None,
                "value_wei": int(value_hex, 16) if value_hex else 0,
                "block_number": int(block_hex, 16) if block_hex else None,
                # Missing status (pre-Byzantium chains) is treated as success -
                # only an explicit "0x0" counts as a revert.
                "status_success": status_hex != "0x0",
                "log_count": len(logs),
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
                    "verdict": "deny",
                    "confidence": 100,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} could not be found on-chain."
                    ),
                }
            if facts["from"] != wallet_hex:
                return {
                    "verdict": "deny",
                    "confidence": 100,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} was not sent from the "
                        "claimed wallet - it originated from a different address."
                    ),
                }
            if not facts["status_success"]:
                return {
                    "verdict": "deny",
                    "confidence": 100,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} reverted on-chain - "
                        "nothing it attempted actually took effect, so no funds moved."
                    ),
                }
            if facts["value_wei"] == 0 and facts["log_count"] == 0:
                return {
                    "verdict": "deny",
                    "confidence": 100,
                    "reasoning": (
                        f"Cited drain transaction {drain_tx_hash} transferred no native "
                        "value and emitted no on-chain events, so it does not show any "
                        "asset actually leaving the wallet."
                    ),
                }

            web_data = gl.nondet.web.render(evidence_url, mode="text")
            web_data_lower = web_data.lower()

            if wallet_hex not in web_data_lower:
                return {
                    "verdict": "deny",
                    "confidence": 100,
                    "reasoning": (
                        f"The evidence at {evidence_url} does not mention the claimed "
                        "wallet address anywhere, so it cannot be authenticated as "
                        "evidence for this specific wallet."
                    ),
                }

            tx_hash_lower = drain_tx_hash.lower().removeprefix("0x")
            destination_mentioned = facts["to"] is not None and facts["to"] in web_data_lower
            if tx_hash_lower not in web_data_lower and not destination_mentioned:
                return {
                    "verdict": "deny",
                    "confidence": 100,
                    "reasoning": (
                        f"The evidence at {evidence_url} mentions the wallet but not the "
                        "specific drain transaction or its destination address, so it "
                        "cannot be authenticated as evidence for THIS incident rather "
                        "than the wallet generally."
                    ),
                }

            balance = self._fetch_chain_balance(drained_wallet)
            destination_display = f"0x{facts['to']}" if facts["to"] else "unknown (contract creation)"

            prompt = f"""
You are adjudicating a cryptocurrency fund-recovery claim on Salvage Arbiter.

Drained/compromised wallet address: {drained_wallet}

The claimant has already cryptographically proven they control (or retain signing
access to) this wallet via a verified EIP-191 signature - do not re-litigate
ownership, that part is settled by cryptography, not by you. It has also been
independently confirmed that {drain_tx_hash} is a real, successful on-chain
transaction sent FROM this wallet that actually moved an asset (native value or a
logged event such as a token transfer), so a drain event genuinely occurred - do not
re-litigate whether this wallet was drained, only whether the claimant's account of
it is credible. Your job is to judge whether the claimant's stated circumstances for
this recovery are coherent, credible, and consistent with the independently-verified
facts below.

Claimant's statement:
{statement}

Supporting evidence fetched from {evidence_url}:
\"\"\"
{web_data}
\"\"\"

Independently verified on-chain facts (authoritative, fetched directly from a public
RPC - not provided or editable by the claimant):
- Drain transaction {drain_tx_hash} is confirmed sent from {drained_wallet}, succeeded
  on-chain (did not revert), and moved an asset ({facts['value_wei']} wei native value,
  {facts['log_count']} event log(s) emitted).
- Destination of that transaction: {destination_display}
- Block number: {facts['block_number']}
- Current balance of {drained_wallet}: {balance}

Decide whether the statement and evidence together form a coherent, credible account
of this wallet's compromise and recovery request. Treat evidence that is generic,
unrelated to the actual events described, or contradicted by the on-chain facts above
(for example, describing an urgent unresolved drain when the balance shows otherwise)
as a reason to deny or mark insufficient.

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
