"""Direct-mode tests for RecoveryReleaseVault v2.

Direct mode cannot run two contracts against each other, so a FakeArbiter answers the vault's cross-contract calls. It models the
fields the vault depends on (status, claimant, drained asset and amount, challenge count) and records every call, including which
state each call asked for, so these tests pin down exactly what the vault asks, of which state, and what it does with each answer.
The real cross-contract path is covered by the live Bradbury run (see README).
"""

from datetime import datetime, timezone

import pytest

CONTRACT = "contracts/recovery_release_vault.py"
ARBITER = "0x" + "ab" * 20
LATEST_FINAL = 1
T0 = "2026-01-01T00:00:00Z"
T0_TS = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
WINDOW = 3600
BEFORE_WINDOW = "2026-01-01T00:59:59Z"
AT_WINDOW = "2026-01-01T01:00:00Z"
AFTER = "2026-01-01T02:00:00Z"
STALE_REFUND = "2026-01-31T00:00:00Z"  # exactly 30 days after T0
JUST_BEFORE_STALE = "2026-01-30T23:59:59Z"
CID = "claim-1"
ASSET = "native"
BOUND = 5000


class FakeArbiter:
    """Stands in for the deployed RecoveryArbiter and records every call made to it."""

    def __init__(self):
        self.claims = {}
        self.calls = []
        self.fail = False  # the arbiter errors
        self.junk = None  # a wrong-shaped answer for every call
        self.mutate = None  # a function(dict) -> dict applied to every answer

    def put(self, cid, claimant, status="approved", token=ASSET, amount=BOUND, challenges=0):
        self.claims[cid] = dict(id=cid, claimant=bytes(claimant), status=status, drained_token=token, drained_amount=amount, challenge_count=challenges)

    def set(self, cid, **kw):
        alias = {"challenges": "challenge_count", "token": "drained_token", "amount": "drained_amount"}
        self.claims[cid].update({alias.get(k, k): v for k, v in kw.items()})

    def install(self, vm):
        def hook(_vm, request):
            from genlayer import Address
            from genlayer.py import calldata

            if "CallContract" not in request:
                return None
            req = request["CallContract"]
            addr = req["address"]
            addr_hex = "0x" + (addr.as_bytes.hex() if hasattr(addr, "as_bytes") else bytes(addr).hex())
            cd = req["calldata"]
            self.calls.append({"address": addr_hex, "method": cd["method"], "args": list(cd["args"]), "state": req.get("state")})
            if self.fail:
                return bytes([1]) + b"simulated arbiter error"
            if addr_hex != ARBITER:
                return bytes([1]) + b"unexpected address"
            if self.junk is not None:
                return bytes([0]) + calldata.encode(self.junk)
            if cd["method"] != "get_claim":
                return bytes([1]) + b"unexpected method"
            cid = cd["args"][0]
            if cid not in self.claims:
                return bytes([1]) + b"Claim not found"
            c = dict(self.claims[cid])
            c["claimant"] = Address(c["claimant"])
            if self.mutate is not None:
                c = self.mutate(c)
            return bytes([0]) + calldata.encode(c)

        vm._gl_call_hook = hook


def _hex(a):
    return ("0x" + bytes(a).hex()).lower()


def _capture_sends(vm):
    sends = []
    inner = vm._gl_call_hook if hasattr(vm, "_gl_call_hook") else None

    def hook(v, request):
        if isinstance(request, dict) and "EthSend" in request:
            s = request["EthSend"]
            sends.append((s["address"].as_hex.lower(), int(s["value"])))
            return None
        return inner(v, request) if inner else None

    vm._gl_call_hook = hook
    return sends


def _setup(vm, deploy):
    fake = FakeArbiter()
    fake.install(vm)
    return deploy(CONTRACT, ARBITER), fake


def _deposit(vm, c, who, value, cid=CID):
    vm.sender = who
    vm.value = value
    try:
        c.deposit_for_claim(cid)
    finally:
        vm.value = 0


def _queued(vm, c, fake, claimant, depositor, value=1000, cid=CID):
    fake.put(cid, claimant)
    _deposit(vm, c, depositor, value, cid)
    vm.sender = depositor
    c.queue_release(cid)


def _decided(vm, c, fake, claimant, depositor, value=1000, cid=CID):
    _queued(vm, c, fake, claimant, depositor, value, cid)
    vm.warp(AT_WINDOW)
    c.release(cid)


# ---------------------------------------------------------------------------
# deposits
# ---------------------------------------------------------------------------


def test_deposits_accumulate_per_claim_and_per_depositor(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _deposit(direct_vm, c, direct_alice, 100)
    _deposit(direct_vm, c, direct_alice, 50)
    _deposit(direct_vm, c, direct_bob, 7)
    assert c.get_deposit(CID) == 157 and c.get_deposit("other") == 0
    assert c.get_depositor_amount(CID, _hex(direct_alice)) == 150 and c.get_depositor_amount(CID, _hex(direct_bob)) == 7
    assert c.get_accounting()["total_received"] == 157


def test_a_deposit_needs_value_and_a_sane_claim_id(direct_vm, direct_deploy, direct_alice):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("positive amount"):
        c.deposit_for_claim(CID)
    for bad in ("", "x" * 201):
        direct_vm.value = 10
        with direct_vm.expect_revert("claim_id must be"):
            c.deposit_for_claim(bad)
    direct_vm.value = 0
    assert c.get_accounting()["total_received"] == 0
    _deposit(direct_vm, c, direct_alice, 10, "x" * 200)  # the limit itself is fine
    assert c.get_deposit("x" * 200) == 10


def test_a_deposit_is_refused_once_the_payout_is_decided_or_paid(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _decided(direct_vm, c, fake, direct_bob, direct_alice)
    direct_vm.value = 5
    with direct_vm.expect_revert("already decided"):
        c.deposit_for_claim(CID)
    c.settle(CID)
    with direct_vm.expect_revert("already decided"):
        c.deposit_for_claim(CID)
    direct_vm.value = 0
    assert c.get_accounting()["total_received"] == 1000


def test_a_deposit_is_still_welcome_while_queued(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice, 1000)
    _deposit(direct_vm, c, direct_charlie, 500)
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    c.settle(CID)
    assert sends == [(_hex(direct_bob), 1500)]


# ---------------------------------------------------------------------------
# queue_release
# ---------------------------------------------------------------------------


def test_queueing_reads_the_finalized_claim_and_records_what_it_saw(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, challenges=2)
    _deposit(direct_vm, c, direct_alice, 1000)
    direct_vm.sender = direct_charlie  # anyone
    c.queue_release(CID)
    assert fake.calls == [{"address": ARBITER, "method": "get_claim", "args": [CID], "state": LATEST_FINAL}]
    r = c.get_release(CID)
    assert (r["phase"], r["asset"], r["bound_amount"], r["challenges"], r["queued_at"], r["release_at"], r["pay"]) == ("queued", ASSET, BOUND, 2, T0_TS, T0_TS + WINDOW, 0)
    assert r["claimant"].lower() == _hex(direct_bob)
    assert sends == []  # a queue moves no money


@pytest.mark.parametrize("status", ["pending", "denied", "insufficient", "challenged", "weird"])
def test_only_an_approved_claim_can_be_queued(direct_vm, direct_deploy, direct_alice, direct_bob, status):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status=status)
    _deposit(direct_vm, c, direct_alice, 1000)
    with direct_vm.expect_revert("has not approved"):
        c.queue_release(CID)
    assert c.get_release(CID)["phase"] == "open"


def test_a_claim_with_nothing_bound_to_it_cannot_be_queued(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _deposit(direct_vm, c, direct_alice, 1000)
    for kw in (dict(token=""), dict(amount=0)):
        fake.put(CID, direct_bob, **kw)
        with direct_vm.expect_revert("No verified drained asset"):
            c.queue_release(CID)


def test_queueing_needs_a_deposit(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Nothing deposited"):
        c.queue_release(CID)


def test_an_unreadable_arbiter_is_never_taken_for_a_verdict(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob)
    _deposit(direct_vm, c, direct_alice, 1000)
    for how in ("fail", "junk", "gone", "no status", "bad status type", "bad asset type", "bad amount", "bad count", "bool amount", "negative amount", "bad claimant"):
        fake.fail = how == "fail"
        fake.junk = [] if how == "junk" else None
        fake.mutate = {
            "no status": lambda c: {k: v for k, v in c.items() if k != "status"},
            "bad status type": lambda c: {**c, "status": 5},
            "bad asset type": lambda c: {**c, "drained_token": 5},
            "bad amount": lambda c: {**c, "drained_amount": "5000"},
            "bad count": lambda c: {**c, "challenge_count": "0"},
            "bool amount": lambda c: {**c, "drained_amount": True},
            "negative amount": lambda c: {**c, "drained_amount": -1},
            "bad claimant": lambda c: {**c, "claimant": 12345},
        }.get(how)
        fake.claims.pop("gone", None)
        cid = "gone" if how == "gone" else CID
        if how == "gone":
            _deposit(direct_vm, c, direct_alice, 10, "gone")
        with direct_vm.expect_revert("could not be read"):
            direct_vm.sender = direct_alice
            c.queue_release(cid)
        assert c.get_release(cid)["phase"] == "open", how


def test_a_claim_can_only_be_queued_once(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    with direct_vm.expect_revert("Already queued"):
        c.queue_release(CID)
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    with direct_vm.expect_revert("Already queued"):
        c.queue_release(CID)


# ---------------------------------------------------------------------------
# the challenge window and release
# ---------------------------------------------------------------------------


def test_release_waits_for_the_whole_window_and_the_boundary_is_inclusive(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    direct_vm.warp(BEFORE_WINDOW)
    with direct_vm.expect_revert("window is still open"):
        c.release(CID)
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    assert c.get_release(CID)["phase"] == "decided"


def test_the_bound_asset_is_only_reported_once_the_payout_is_decided(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    assert (c.get_released_asset(CID), c.get_released_amount(CID)) == ("", 0)  # queued is not released
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    assert (c.get_released_asset(CID), c.get_released_amount(CID)) == (ASSET, BOUND)


def test_release_records_the_decision_and_moves_no_money(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice, 1001)
    direct_vm.warp(AFTER)
    c.release(CID)
    assert sends == []
    r = c.get_release(CID)
    assert (r["phase"], r["pay"]) == ("decided", 1001)
    assert c.get_deposit(CID) == 0  # committed to the payout, no longer an open deposit
    assert not c.is_released(CID)  # decided is not paid
    assert (c.get_released_asset(CID), c.get_released_amount(CID)) == (ASSET, BOUND)
    a = c.get_accounting()
    assert (a["total_received"], a["total_scheduled"], a["unscheduled"]) == (1001, 0, 1001)


def test_release_asks_the_finalized_state_again(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.calls.clear()
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    assert fake.calls == [{"address": ARBITER, "method": "get_claim", "args": [CID], "state": LATEST_FINAL}]


@pytest.mark.parametrize(
    "change",
    [
        dict(status="challenged"),
        dict(status="denied"),
        dict(status="pending"),
        dict(challenges=1),  # challenged and re-approved while queued: status looks fine, the history does not
        dict(token="0xdac17f958d2ee523a2206206994597c13d831ec7"),
        dict(amount=BOUND + 1),
    ],
)
def test_a_claim_that_changed_since_it_was_queued_is_not_released(direct_vm, direct_deploy, direct_alice, direct_bob, change):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.set(CID, **change)
    direct_vm.warp(AT_WINDOW)
    with direct_vm.expect_revert("changed since it was queued"):
        c.release(CID)
    assert c.get_release(CID)["phase"] == "queued" and sends == []


def test_a_claim_whose_claimant_changed_is_not_released(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.set(CID, claimant=bytes(direct_charlie))
    direct_vm.warp(AT_WINDOW)
    with direct_vm.expect_revert("changed since it was queued"):
        c.release(CID)


def test_release_never_acts_on_an_unreadable_arbiter(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    direct_vm.warp(AT_WINDOW)
    for how in ("fail", "junk"):
        fake.fail = how == "fail"
        fake.junk = [] if how == "junk" else None
        with direct_vm.expect_revert("could not be read"):
            c.release(CID)
        assert c.get_release(CID)["phase"] == "queued"


def test_release_needs_a_queue(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob)
    _deposit(direct_vm, c, direct_alice, 1000)
    with direct_vm.expect_revert("Not queued"):
        c.release(CID)
    with direct_vm.expect_revert("Not queued"):
        c.release("never-heard-of-it")


def test_release_can_only_record_once(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _decided(direct_vm, c, fake, direct_bob, direct_alice)
    with direct_vm.expect_revert("Not queued"):
        c.release(CID)


# ---------------------------------------------------------------------------
# cancel_queue
# ---------------------------------------------------------------------------


def test_a_queue_that_still_looks_right_cannot_be_cancelled(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    with direct_vm.expect_revert("still looks the way"):
        c.cancel_queue(CID)
    assert c.get_release(CID)["phase"] == "queued"


@pytest.mark.parametrize("change", [dict(status="challenged"), dict(status="denied"), dict(challenges=1), dict(amount=1)])
def test_a_queue_that_changed_is_cancelled_by_anyone_and_the_deposit_stays(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, change):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.set(CID, **change)
    direct_vm.sender = direct_charlie
    c.cancel_queue(CID)
    assert c.get_release(CID)["phase"] == "open" and c.get_deposit(CID) == 1000 and sends == []


def test_cancelling_never_happens_on_an_unreadable_arbiter(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.fail = True
    with direct_vm.expect_revert("could not be read"):
        c.cancel_queue(CID)
    assert c.get_release(CID)["phase"] == "queued"


def test_only_a_queue_can_be_cancelled(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    with direct_vm.expect_revert("Not queued"):
        c.cancel_queue(CID)
    _decided(direct_vm, c, fake, direct_bob, direct_alice)
    fake.set(CID, status="challenged")
    with direct_vm.expect_revert("Not queued"):
        c.cancel_queue(CID)  # a recorded decision is not undone by a later challenge


def test_a_cancelled_claim_can_be_queued_again_after_a_fresh_approval(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.set(CID, status="challenged", challenges=1)
    c.cancel_queue(CID)
    fake.set(CID, status="approved", challenges=1)  # the claimant won the challenge
    direct_vm.warp("2026-01-01T05:00:00Z")
    c.queue_release(CID)
    assert c.get_release(CID)["challenges"] == 1 and c.get_release(CID)["queued_at"] == T0_TS + 5 * 3600
    direct_vm.warp("2026-01-01T06:00:00Z")
    c.release(CID)
    c.settle(CID)
    assert sends == [(_hex(direct_bob), 1000)]


# ---------------------------------------------------------------------------
# settle
# ---------------------------------------------------------------------------


def test_settle_pays_the_claimant_the_whole_deposit_once_and_reads_nothing(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _decided(direct_vm, c, fake, direct_bob, direct_alice, 1001)
    fake.calls.clear()
    direct_vm.sender = direct_charlie
    c.settle(CID)
    assert sends == [(_hex(direct_bob), 1001)]
    assert fake.calls == []  # no payment shares a transaction with a read of the arbiter
    assert c.is_released(CID) and c.get_release(CID)["phase"] == "settled"
    a = c.get_accounting()
    assert (a["total_received"], a["total_scheduled"], a["unscheduled"]) == (1001, 1001, 0)
    for call in (lambda: c.settle(CID), lambda: c.release(CID), lambda: c.queue_release(CID), lambda: c.cancel_queue(CID)):
        with direct_vm.expect_revert():
            call()
    assert sends == [(_hex(direct_bob), 1001)]


def test_settle_needs_a_recorded_decision(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    with direct_vm.expect_revert("No payout decision"):
        c.settle(CID)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    with direct_vm.expect_revert("No payout decision"):
        c.settle(CID)
    assert sends == []


def test_several_depositors_are_paid_out_together_to_the_one_claimant(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob)
    _deposit(direct_vm, c, direct_alice, 333)
    _deposit(direct_vm, c, direct_charlie, 444)
    direct_vm.sender = direct_alice
    c.queue_release(CID)
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    c.settle(CID)
    assert sends == [(_hex(direct_bob), 777)]


def test_two_claims_never_touch_each_other(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _decided(direct_vm, c, fake, direct_bob, direct_alice, 100, "a")
    fake.put("b", direct_charlie, status="denied")
    _deposit(direct_vm, c, direct_alice, 50, "b")
    c.settle("a")
    assert sends == [(_hex(direct_bob), 100)]
    assert c.get_deposit("b") == 50 and c.get_release("b")["phase"] == "open"


# ---------------------------------------------------------------------------
# refunds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["denied", "insufficient"])
def test_a_depositor_can_take_their_own_deposit_back_when_the_claim_is_denied(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, status):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status=status)
    _deposit(direct_vm, c, direct_alice, 300)
    _deposit(direct_vm, c, direct_charlie, 70)
    direct_vm.sender = direct_alice
    c.refund(CID)
    assert fake.calls[-1] == {"address": ARBITER, "method": "get_claim", "args": [CID], "state": LATEST_FINAL}
    assert sends == []  # a refund request moves no money
    assert c.get_depositor_amount(CID, _hex(direct_alice)) == 0 and c.get_pending_refund(CID, _hex(direct_alice)) == 300
    assert c.get_deposit(CID) == 70  # the other depositor's money is untouched
    direct_vm.sender = direct_charlie  # anyone may pay it
    fake.calls.clear()
    c.settle_refund(CID, _hex(direct_alice))
    assert sends == [(_hex(direct_alice), 300)] and fake.calls == []
    assert c.get_pending_refund(CID, _hex(direct_alice)) == 0
    a = c.get_accounting()
    assert (a["total_received"], a["total_scheduled"], a["unscheduled"]) == (370, 300, 70)


@pytest.mark.parametrize("status", ["approved", "pending", "challenged"])
def test_nobody_can_pull_money_out_of_a_live_claim(direct_vm, direct_deploy, direct_alice, direct_bob, status):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status=status)
    _deposit(direct_vm, c, direct_alice, 300)
    with direct_vm.expect_revert("Refunds open when"):
        c.refund(CID)
    assert c.get_depositor_amount(CID, _hex(direct_alice)) == 300


def test_a_refund_is_only_ever_your_own_deposit(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status="denied")
    _deposit(direct_vm, c, direct_alice, 300)
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("no deposit"):
        c.refund(CID)
    direct_vm.sender = direct_alice
    c.refund(CID)
    with direct_vm.expect_revert("no deposit"):
        c.refund(CID)  # nothing left to take twice


def test_a_refund_cannot_be_paid_twice_and_unrequested_ones_cannot_be_paid(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status="denied")
    _deposit(direct_vm, c, direct_alice, 300)
    with direct_vm.expect_revert("No refund to settle"):
        c.settle_refund(CID, _hex(direct_alice))  # nothing requested yet
    direct_vm.sender = direct_alice
    c.refund(CID)
    c.settle_refund(CID, _hex(direct_alice))
    with direct_vm.expect_revert("No refund to settle"):
        c.settle_refund(CID, _hex(direct_alice))
    with direct_vm.expect_revert("No refund to settle"):
        c.settle_refund(CID, _hex(direct_charlie))
    assert sends == [(_hex(direct_alice), 300)]


def test_a_stale_claim_refunds_after_thirty_days_without_asking_the_arbiter(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status="pending")
    _deposit(direct_vm, c, direct_alice, 300)
    direct_vm.warp(JUST_BEFORE_STALE)
    with direct_vm.expect_revert("Refunds open when"):
        c.refund(CID)
    direct_vm.warp(STALE_REFUND)
    fake.calls.clear()
    fake.fail = True  # a dead arbiter must not trap a depositor forever
    c.refund(CID)
    assert fake.calls == []
    c.settle_refund(CID, _hex(direct_alice))
    assert sends == [(_hex(direct_alice), 300)]


def test_a_claim_nobody_ever_filed_can_still_be_reclaimed_after_the_stale_period(direct_vm, direct_deploy, direct_alice):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _deposit(direct_vm, c, direct_alice, 300, "typo-claim-id")
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("could not be read"):
        c.refund("typo-claim-id")  # the arbiter has no such claim, and that is not a verdict
    direct_vm.warp(STALE_REFUND)
    c.refund("typo-claim-id")
    c.settle_refund("typo-claim-id", _hex(direct_alice))
    assert sends == [(_hex(direct_alice), 300)]


def test_a_new_deposit_restarts_that_depositors_stale_clock(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status="pending")
    _deposit(direct_vm, c, direct_alice, 100)
    direct_vm.warp(JUST_BEFORE_STALE)
    _deposit(direct_vm, c, direct_alice, 1)
    direct_vm.warp(STALE_REFUND)
    with direct_vm.expect_revert("Refunds open when"):
        c.refund(CID)


def test_a_queued_or_decided_claim_cannot_be_refunded_even_when_stale(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    direct_vm.warp(STALE_REFUND)
    with direct_vm.expect_revert("queued or decided"):
        c.refund(CID)
    direct_vm.warp(AT_WINDOW)
    c.release(CID)
    with direct_vm.expect_revert("queued or decided"):
        c.refund(CID)
    c.settle(CID)
    with direct_vm.expect_revert("queued or decided"):
        c.refund(CID)
    assert sends == [(_hex(direct_bob), 1000)]


def test_a_denied_claim_that_is_cancelled_out_of_the_queue_can_be_refunded(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    fake.set(CID, status="denied")
    c.cancel_queue(CID)
    direct_vm.sender = direct_alice
    c.refund(CID)
    c.settle_refund(CID, _hex(direct_alice))
    assert sends == [(_hex(direct_alice), 1000)]


def test_a_depositor_can_deposit_again_after_a_refund_and_be_refunded_again(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status="denied")
    for amount in (100, 40):
        _deposit(direct_vm, c, direct_alice, amount)
        c.refund(CID)
        c.settle_refund(CID, _hex(direct_alice))
    assert sends == [(_hex(direct_alice), 100), (_hex(direct_alice), 40)]
    a = c.get_accounting()
    assert (a["total_received"], a["total_scheduled"], a["unscheduled"]) == (140, 140, 0)


def test_refund_does_not_act_on_an_unreadable_arbiter_before_the_stale_period(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    fake.put(CID, direct_bob, status="denied")
    _deposit(direct_vm, c, direct_alice, 300)
    for how in ("fail", "junk"):
        fake.fail = how == "fail"
        fake.junk = [] if how == "junk" else None
        with direct_vm.expect_revert("could not be read"):
            c.refund(CID)
    assert c.get_depositor_amount(CID, _hex(direct_alice)) == 300


# ---------------------------------------------------------------------------
# accounting, ids, safety
# ---------------------------------------------------------------------------


def test_the_books_balance_on_every_path_together(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, fake = _setup(direct_vm, direct_deploy)
    sends = _capture_sends(direct_vm)
    direct_vm.warp(T0)
    _decided(direct_vm, c, fake, direct_bob, direct_alice, 700, "paid")
    fake.put("denied", direct_charlie, status="denied")
    _deposit(direct_vm, c, direct_alice, 333, "denied")
    _deposit(direct_vm, c, direct_bob, 91, "still-open")
    c.settle("paid")
    direct_vm.sender = direct_alice
    c.refund("denied")
    c.settle_refund("denied", _hex(direct_alice))
    assert sorted(sends) == sorted([(_hex(direct_bob), 700), (_hex(direct_alice), 333)])
    a = c.get_accounting()
    assert (a["total_received"], a["total_scheduled"], a["unscheduled"]) == (1124, 1033, 91)
    assert a["total_received"] == a["total_scheduled"] + a["unscheduled"]


def test_accounting_reports_money_in_flight_and_a_shortfall(direct_vm, direct_deploy, direct_alice):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _deposit(direct_vm, c, direct_alice, 1000)
    me = direct_vm._contract_address
    direct_vm.deal(me, 1005)  # 5 wei more than anyone is owed
    a = c.get_accounting()
    assert (a["balance"], a["unscheduled"], a["in_flight"], a["shortfall"]) == (1005, 1000, 5, 0)
    direct_vm.deal(me, 990)
    a = c.get_accounting()
    assert (a["in_flight"], a["shortfall"]) == (0, 10)


def test_claim_ids_containing_the_separator_cannot_collide(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    a_id = "x|" + _hex(direct_bob)
    _deposit(direct_vm, c, direct_alice, 10, "x")
    _deposit(direct_vm, c, direct_alice, 20, a_id)
    assert (c.get_depositor_amount("x", _hex(direct_alice)), c.get_depositor_amount(a_id, _hex(direct_alice))) == (10, 20)
    assert c.get_depositor_amount("x", _hex(direct_bob)) == 0


def test_the_arbiter_is_fixed_for_the_life_of_the_contract(direct_vm, direct_deploy):
    c, fake = _setup(direct_vm, direct_deploy)
    assert c.get_arbiter().lower() == ARBITER
    assert not any(n.startswith(("set_", "update_", "change_", "transfer_owner")) for n in dir(c) if not n.startswith("_"))


def test_only_the_arbiter_that_was_deployed_is_ever_asked(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.warp(T0)
    _queued(direct_vm, c, fake, direct_bob, direct_alice)
    assert {call["address"] for call in fake.calls} == {ARBITER}


def test_unknown_claims_revert_without_touching_state(direct_vm, direct_deploy, direct_alice):
    c, fake = _setup(direct_vm, direct_deploy)
    direct_vm.sender = direct_alice
    for call in (lambda: c.queue_release("nope"), lambda: c.cancel_queue("nope"), lambda: c.release("nope"), lambda: c.settle("nope"),
                 lambda: c.refund("nope"), lambda: c.settle_refund("nope", _hex(direct_alice))):
        with direct_vm.expect_revert():
            call()
    assert c.get_accounting()["total_received"] == 0


def test_views_default_to_empty(direct_vm, direct_deploy, direct_alice):
    c, fake = _setup(direct_vm, direct_deploy)
    assert c.get_deposit("nope") == 0 and not c.is_released("nope")
    assert (c.get_released_asset("nope"), c.get_released_amount("nope")) == ("", 0)
    r = c.get_release("nope")
    assert (r["phase"], r["claimant"], r["pay"]) == ("open", "", 0)


def test_the_contract_has_no_model_and_no_nondeterministic_block():
    src = open(CONTRACT, encoding="utf-8").read()
    assert "nondet" not in src and "run_nondet" not in src and "exec_prompt" not in src
