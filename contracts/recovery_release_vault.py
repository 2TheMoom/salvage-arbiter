# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""RecoveryReleaseVault v2 - a downstream consumer of RecoveryArbiter's verdict that holds real GEN.

Anyone can deposit GEN earmarked for a claim. It is paid to that claim's claimant only after RecoveryArbiter has approved the claim
in FINALIZED state (an appealable verdict never moves money), a verified drained asset and amount is bound to it, and a challenge
window has passed in which nobody froze it. A depositor whose claim is denied, or never approved, can take their own deposit back.

The money paths, and what each is allowed to do:
  deposit_for_claim  takes value, nothing else
  queue_release      reads the arbiter's finalized state, starts the challenge window, moves no money
  cancel_queue       if the claim no longer looks the way it did when queued, drops the queue, moves no money
  release            after the window, if the claim still looks the same, records the payout decision, moves no money
  settle             pays a recorded decision, once; reads nothing
  refund             a depositor records a refund of their own deposit when the claim is denied or the claim went stale, moves no money
  settle_refund      pays a recorded refund, once; reads nothing
A decision (a read of the arbiter) and a payment never share a transaction. get_accounting shows every wei received, every wei
scheduled out, and anything in flight, so a transfer that never lands is visible instead of silent.

This is not Salvage's production rescue router. It holds and pays only GEN, while a real drain was in ETH or an ERC-20, so it
records the verified (asset, amount) next to the payout for a real cross-chain router to check against.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from genlayer import *
from genlayer.py.public_abi import StorageType

CHALLENGE_WINDOW = 3600  # twice the ~30 minutes a transaction takes to finalize on Bradbury
REFUND_AFTER = 30 * 86400
MAX_ID = 200
OPEN, QUEUED, DECIDED, SETTLED = "open", "queued", "decided", "settled"
DEAD = ("denied", "insufficient")


@gl.evm.contract_interface
class Payee:
    """A pure value transfer to an EOA (the chain-layer primitive); no method is ever called on the recipient."""

    class View:
        pass

    class Write:
        pass


def _bad(c: bool, m: str) -> None:
    if c:
        raise gl.vm.UserError(m)


@allow_storage
@dataclass
class Release:
    phase: str
    claimant: Address
    asset: str
    bound_amount: u256
    challenges: u256
    queued_at: u256
    pay: u256


class RecoveryReleaseVault(gl.Contract):
    arbiter_address: Address
    deposits: TreeMap[str, u256]
    by_depositor: TreeMap[str, u256]
    deposited_at: TreeMap[str, u256]
    refunds: TreeMap[str, u256]
    releases: TreeMap[str, Release]
    total_received: u256
    total_scheduled: u256

    def __init__(self, arbiter_address: str):
        # Fixed for the life of this contract: there is no setter and no owner.
        self.arbiter_address = arbiter_address if isinstance(arbiter_address, Address) else Address(arbiter_address)

    def _now(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    def _id(self, claim_id) -> str:
        _bad(not isinstance(claim_id, str) or not 0 < len(claim_id) <= MAX_ID, f"claim_id must be 1 to {MAX_ID} characters")
        return claim_id

    def _key(self, claim_id: str, who: Address) -> str:
        return f"{claim_id}|{who.as_hex.lower()}"  # the last 42 characters are always the depositor, so keys never collide

    def _seen(self, claim_id: str):
        """The arbiter's FINALIZED record of this claim as a clean dict, or None when it cannot be read or is not shaped right.
        None is never taken for a verdict: it refuses everything that needs one."""
        try:
            c = gl.get_contract_at(self.arbiter_address).view(state=StorageType.LATEST_FINAL).get_claim(claim_id)
            status, token, amount, n, who = c["status"], c["drained_token"], c["drained_amount"], c["challenge_count"], c["claimant"]
        except Exception:
            return None
        if not isinstance(status, str) or not isinstance(token, str) or type(amount) is not int or amount < 0 or type(n) is not int or n < 0:
            return None
        try:
            who = who if isinstance(who, Address) else Address(who)
        except Exception:
            return None
        return {"status": status, "asset": token, "amount": amount, "challenges": n, "claimant": who}

    def _same(self, r: dict, q: Release) -> bool:
        return r["status"] == "approved" and r["challenges"] == int(q.challenges) and r["claimant"] == q.claimant and r["asset"] == q.asset and r["amount"] == int(q.bound_amount)

    def _pay(self, to: Address, amount: int) -> None:
        _bad(amount <= 0, "Nothing to pay")
        self.total_scheduled += amount
        Payee(to).emit_transfer(value=amount)

    @gl.public.write.payable
    def deposit_for_claim(self, claim_id: str) -> None:
        """Earmarks this transaction's value for a claim. Anyone may deposit, before or after a verdict. Refused once the claim's
        payout is decided, because a later deposit would have nowhere to go."""
        cid = self._id(claim_id)
        _bad(gl.message.value <= 0, "Must send a positive amount to deposit")
        r = self.releases.get(cid)
        _bad(r is not None and r.phase in (DECIDED, SETTLED), "This claim's payout is already decided, deposit to a new claim")
        k = self._key(cid, gl.message.sender_address)
        self.deposits[cid] = self.deposits.get(cid, u256(0)) + gl.message.value
        self.by_depositor[k] = self.by_depositor.get(k, u256(0)) + gl.message.value
        self.deposited_at[k] = self._now()
        self.total_received += gl.message.value

    @gl.public.write
    def queue_release(self, claim_id: str) -> None:
        """Permissionless. Needs the arbiter's FINALIZED state to show the claim approved, with a verified asset and amount."""
        cid = self._id(claim_id)
        _bad(cid in self.releases, "Already queued or decided")
        _bad(self.deposits.get(cid, u256(0)) <= 0, "Nothing deposited for this claim")
        r = self._seen(cid)
        _bad(r is None, "The arbiter could not be read, nothing recorded")
        _bad(r["status"] != "approved", f"The arbiter has not approved this claim in finalized state (status: {r['status']})")
        _bad(r["asset"] == "" or r["amount"] <= 0, "No verified drained asset and amount is bound to this claim")
        self.releases[cid] = Release(phase=QUEUED, claimant=r["claimant"], asset=r["asset"], bound_amount=r["amount"], challenges=r["challenges"], queued_at=self._now(), pay=0)

    @gl.public.write
    def cancel_queue(self, claim_id: str) -> None:
        """Permissionless. A queued claim that was challenged, denied or changed in finalized state is taken out of the queue
        (so it can be queued again after a fresh approval, or refunded). Never on an unreadable arbiter."""
        cid = self._id(claim_id)
        q = self.releases.get(cid)
        _bad(q is None or q.phase != QUEUED, "Not queued")
        r = self._seen(cid)
        _bad(r is None, "The arbiter could not be read, nothing recorded")
        _bad(self._same(r, q), "The claim still looks the way it did when it was queued")
        del self.releases[cid]

    @gl.public.write
    def release(self, claim_id: str) -> None:
        """Permissionless. After the challenge window, and only if the finalized claim is exactly what was queued: records the
        payout decision. Moves no money; settle pays it."""
        cid = self._id(claim_id)
        q = self.releases.get(cid)
        _bad(q is None or q.phase != QUEUED, "Not queued")
        _bad(self._now() < int(q.queued_at) + CHALLENGE_WINDOW, "The challenge window is still open")
        r = self._seen(cid)
        _bad(r is None, "The arbiter could not be read, nothing recorded")
        _bad(not self._same(r, q), "The claim changed since it was queued, call cancel_queue")
        pay = self.deposits.get(cid, u256(0))
        _bad(pay <= 0, "Nothing deposited for this claim")
        self.deposits[cid] = u256(0)
        q.phase = DECIDED
        q.pay = pay

    @gl.public.write
    def settle(self, claim_id: str) -> None:
        """Pays a recorded decision to the claimant, once. Reads nothing."""
        cid = self._id(claim_id)
        q = self.releases.get(cid)
        _bad(q is None or q.phase != DECIDED, "No payout decision to settle")
        pay = int(q.pay)
        q.phase = SETTLED
        self._pay(q.claimant, pay)

    @gl.public.write
    def refund(self, claim_id: str) -> None:
        """A depositor takes back their OWN deposit, while the claim is not queued or decided: when the arbiter's finalized state says
        denied or insufficient, or when 30 days passed since their last deposit. Records the refund; settle_refund pays it."""
        cid = self._id(claim_id)
        who = gl.message.sender_address
        k = self._key(cid, who)
        mine = self.by_depositor.get(k, u256(0))
        _bad(mine <= 0, "You have no deposit on this claim")
        _bad(cid in self.releases, "This claim is queued or decided, its deposits are committed")
        stale = self._now() >= int(self.deposited_at.get(k, u256(0))) + REFUND_AFTER
        if not stale:
            r = self._seen(cid)
            _bad(r is None, "The arbiter could not be read, nothing recorded")
            _bad(r["status"] not in DEAD, "Refunds open when the claim is denied, or 30 days after your deposit")
        self.by_depositor[k] = u256(0)
        self.deposits[cid] = self.deposits.get(cid, u256(0)) - mine
        self.refunds[k] = self.refunds.get(k, u256(0)) + mine

    @gl.public.write
    def settle_refund(self, claim_id: str, depositor: str) -> None:
        """Pays a recorded refund to its depositor, once. Anyone may call it. Reads nothing."""
        cid = self._id(claim_id)
        who = depositor if isinstance(depositor, Address) else Address(depositor)
        k = self._key(cid, who)
        amount = int(self.refunds.get(k, u256(0)))
        _bad(amount <= 0, "No refund to settle")
        self.refunds[k] = u256(0)
        self._pay(who, amount)

    @gl.public.view
    def get_deposit(self, claim_id: str) -> u256:
        return self.deposits.get(claim_id, u256(0))

    @gl.public.view
    def get_depositor_amount(self, claim_id: str, depositor: str) -> u256:
        who = depositor if isinstance(depositor, Address) else Address(depositor)
        return self.by_depositor.get(self._key(claim_id, who), u256(0))

    @gl.public.view
    def get_pending_refund(self, claim_id: str, depositor: str) -> u256:
        who = depositor if isinstance(depositor, Address) else Address(depositor)
        return self.refunds.get(self._key(claim_id, who), u256(0))

    @gl.public.view
    def get_release(self, claim_id: str) -> dict:
        q = self.releases.get(claim_id)
        if q is None:
            return {"phase": OPEN, "claimant": "", "asset": "", "bound_amount": 0, "challenges": 0, "queued_at": 0, "release_at": 0, "pay": 0}
        return {"phase": q.phase, "claimant": q.claimant.as_hex, "asset": q.asset, "bound_amount": q.bound_amount, "challenges": q.challenges,
                "queued_at": q.queued_at, "release_at": int(q.queued_at) + CHALLENGE_WINDOW, "pay": q.pay}

    @gl.public.view
    def is_released(self, claim_id: str) -> bool:
        q = self.releases.get(claim_id)
        return q is not None and q.phase == SETTLED

    @gl.public.view
    def get_released_asset(self, claim_id: str) -> str:
        q = self.releases.get(claim_id)
        return q.asset if q is not None and q.phase in (DECIDED, SETTLED) else ""

    @gl.public.view
    def get_released_amount(self, claim_id: str) -> u256:
        q = self.releases.get(claim_id)
        return q.bound_amount if q is not None and q.phase in (DECIDED, SETTLED) else u256(0)

    @gl.public.view
    def get_arbiter(self) -> str:
        return self.arbiter_address.as_hex

    @gl.public.view
    def get_accounting(self) -> dict:
        bal = int(self.balance)
        owed = int(self.total_received) - int(self.total_scheduled)
        return {"balance": bal, "total_received": int(self.total_received), "total_scheduled": int(self.total_scheduled),
                "unscheduled": owed, "in_flight": max(bal - owed, 0), "shortfall": max(owed - bal, 0)}
