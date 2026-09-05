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
    not AI judgment), then validators independently fetch supporting
    evidence and authoritative on-chain facts and reach consensus on a
    verdict via the equivalence principle. The result is an on-chain
    attestation that an off-chain recovery flow (e.g. Salvage's cross-chain
    rescue router) can require before releasing funds - one attestation
    per wallet, since an already-approved wallet cannot receive competing
    claims.
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
            resp = gl.nondet.web.post(CHAIN_DATA_RPC_URL, body=body, headers=RPC_HEADERS)
            payload = json.loads((resp.body or b"").decode("utf-8"))
            balance_hex = payload.get("result")
            if not balance_hex:
                return "unknown (RPC lookup failed)"
            return f"{int(balance_hex, 16)} wei"
        except (ValueError, AttributeError, TypeError):
            return "unknown (RPC lookup failed)"

    def _judge(self, drained_wallet: str, evidence_url: str, statement: str) -> dict:
        def leader_fn() -> dict:
            web_data = gl.nondet.web.render(evidence_url, mode="text")
            balance = self._fetch_chain_balance(drained_wallet)

            prompt = f"""
You are adjudicating a cryptocurrency fund-recovery claim on Salvage Arbiter.

Drained/compromised wallet address: {drained_wallet}

The claimant has already cryptographically proven they control (or retain signing
access to) this wallet via a verified EIP-191 signature - do not re-litigate
ownership, that part is settled by cryptography, not by you. Your job is to judge
whether the claimant's stated circumstances for this recovery are coherent, credible,
and consistent with the independently-verified facts below.

Claimant's statement:
{statement}

Supporting evidence fetched from {evidence_url}:
\"\"\"
{web_data}
\"\"\"

Independently verified on-chain fact (authoritative, fetched directly from a public
RPC - not provided or editable by the claimant):
Current balance of {drained_wallet}: {balance}

Decide whether the statement and evidence together form a coherent, credible account
of this wallet's compromise and recovery request. Treat evidence that is generic,
unrelated to the actual events described, or contradicted by the on-chain balance
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

        verdict = self._judge(claim.drained_wallet, claim.evidence_url, claim.statement)

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
    def submit_appeal(self, claim_id: str, evidence_url: str, statement: str) -> None:
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
