"""Review round 5 (Codex review of c149c38): cancellation windows (R5-01) and concurrent recovery (R5-02).

Every race here is forced with threading Events/Barriers placed at exact code points, not sleeps.
These tests were first run against c149c38 to record the old behaviour
(docs/evidence/review-r5-old-c149c38.txt), then against the fix.
"""
from __future__ import annotations

import json
import threading

import pytest

from backend.demo_generators import generate
from backend.simulator import SimulatedCrash
from tests.conftest import APPROVER, CAMPAIGN, REQ, Harness, ScriptedProvider, key

WAIT = 10  # seconds; only an upper bound for a hung test, never a synchronisation mechanism


class Pause:
    """Blocks a code path at an exact point until the test releases it."""

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def hold(self):
        self.entered.set()
        assert self.release.wait(WAIT), "test never released the pause"


def paused_role(pause: Pause, role: str):
    def fn(payload):
        pause.hold()
        return json.dumps(generate(role, payload))
    return fn


def cancel_while_paused(h: Harness, rid: str, pause: Pause, headers=REQ) -> dict:
    """Wait until the run is inside the paused point, submit a cancel, wait until the cancel is
    committed to the store, then release the paused code path. Returns the cancel HTTP response."""
    committed = threading.Event()
    original = h.runner.store.request_cancel

    def spy(*a, **k):
        try:
            return original(*a, **k)
        finally:
            committed.set()
    h.runner.store.request_cancel = spy
    assert pause.entered.wait(WAIT)
    out = {}
    t = threading.Thread(target=lambda: out.update(r=h.client.post(
        f"/api/runs/{rid}/cancel", json={"idempotency_key": key()}, headers=headers)))
    t.start()
    assert committed.wait(WAIT)
    pause.release.set()
    t.join(WAIT)
    h.runner.wait(rid)
    h.runner.store.request_cancel = original
    return out["r"]


# ----------------------------------------------------------------------------- R5-01 cancellation
def test_r5_01_cancel_during_question_planner_is_not_completed(settings):
    pause = Pause()
    h = Harness(settings, provider=ScriptedProvider({"planner": paused_role(pause, "planner")}))
    try:
        rid = h.create("Who must approve a campaign launch?", wait=False)
        r = cancel_while_paused(h, rid, pause)
        assert r.status_code == 200, r.text
        d = h.detail(rid)
        assert d["status"] == "cancelled", f"accepted cancel ended as {d['status']}"
    finally:
        h.stop()


def test_r5_01_cancel_during_last_step_of_deliverable_is_not_completed(settings):
    pause = Pause()
    h = Harness(settings, provider=ScriptedProvider({"ci": paused_role(pause, "ci")}))
    try:
        rid = h.create("Prepare a pitch comparing channels for NovaByte", wait=False)
        r = cancel_while_paused(h, rid, pause)
        assert r.status_code == 200, r.text
        assert h.detail(rid)["status"] == "cancelled"
    finally:
        h.stop()


def test_r5_01_cancel_during_last_campaign_step_never_reaches_gate(settings):
    pause = Pause()
    h = Harness(settings, provider=ScriptedProvider({"compliance": paused_role(pause, "compliance")}))
    try:
        rid = h.create(wait=False)
        cancel_while_paused(h, rid, pause)
        d = h.detail(rid)
        assert d["status"] == "cancelled" and d["proposals"] == [] and h.actions() == []
    finally:
        h.stop()


def test_r5_01_cancel_between_proposal_and_interrupt_never_executes(h):
    """Cancel lands after build_proposal's cancel check but before interrupt(): the run must not
    end up awaiting approval with an accepted cancel, and a later approve must not execute."""
    pause = Pause()
    original = h.runner.store.upsert_proposal

    def upsert_then_pause(*a, **k):
        result = original(*a, **k)   # after the node's cancel check, before approval_gate
        pause.hold()
        return result
    h.runner.store.upsert_proposal = upsert_then_pause
    rid = h.create(wait=False)
    r = cancel_while_paused(h, rid, pause)
    h.runner.store.upsert_proposal = original
    assert r.status_code == 200, r.text
    d = h.detail(rid)
    assert d["status"] == "cancelled", f"status={d['status']} cancel_requested={d['cancel_requested']}"
    late = h.decide(rid, prop=d["proposals"][-1])
    assert late.status_code == 409
    assert h.actions() == []
    assert h.detail(rid)["status"] == "cancelled"


def test_r5_01_simulator_refuses_a_cancelled_run(h):
    """Defence in depth at the action boundary: even a recorded approve does not execute once the
    run is cancelled."""
    rid = h.create()
    prop = h.pending(rid)
    store = h.runner.store
    resp, _ = store.record_decision(rid, proposal_id=prop["proposal_id"], revision=1,
                                    proposal_sha256=prop["sha256"], decision="approve", actor="bob",
                                    role="approver", comment="", changes=None, idempotency_key=key(),
                                    hard_budget_cap=1e9)
    store.transition(rid, {"resuming"}, "cancelled")   # e.g. an operator cancelled via the store
    with pytest.raises(Exception) as e:
        h.runner.simulator.execute(rid, prop["proposal_id"], 1, prop["sha256"])
    assert getattr(e.value, "code", "") in ("gate_violation", "run_cancelled")
    assert h.actions() == []


def crash_once(point):
    fired = []

    def hook(p):
        if p == point and not fired:
            fired.append(p)
            raise SimulatedCrash(p)
    return hook


def test_r5_01_cancel_after_committed_action_is_refused_not_hidden(settings):
    h = Harness(settings, crash_hook=crash_once("after_commit"))
    try:
        rid = h.create()
        prop = h.pending(rid)
        with pytest.raises(SimulatedCrash):
            h.runner.decide(rid, proposal_id=prop["proposal_id"], revision=1, proposal_sha256=prop["sha256"],
                            decision="approve", comment="", changes=None, idempotency_key=key(), actor="bob",
                            role="approver")
        h.restart()
        assert h.status(rid) == "interrupted" and len(h.actions(rid)) == 1
        c = h.client.post(f"/api/runs/{rid}/cancel", json={"idempotency_key": key()}, headers=APPROVER)
        assert c.status_code == 409, f"cancel of a run with a committed action returned {c.status_code}: {c.text}"
        assert c.json()["error"] == "action_already_committed"
        assert h.status(rid) == "interrupted"
        assert h.recover(rid).status_code == 202
        d = h.detail(rid)
        assert d["status"] == "completed" and len(h.actions(rid)) == 1
    finally:
        h.stop()


def test_r5_01_cancel_after_recorded_but_unexecuted_approve_stays_cancelled(settings):
    h = Harness(settings, crash_hook=crash_once("before_commit"))
    try:
        rid = h.create()
        prop = h.pending(rid)
        with pytest.raises(SimulatedCrash):
            h.runner.decide(rid, proposal_id=prop["proposal_id"], revision=1, proposal_sha256=prop["sha256"],
                            decision="approve", comment="", changes=None, idempotency_key=key(), actor="bob",
                            role="approver")
        h.restart()
        assert h.status(rid) == "interrupted" and h.actions() == []
        c = h.client.post(f"/api/runs/{rid}/cancel", json={"idempotency_key": key()}, headers=APPROVER)
        assert c.status_code == 200 and c.json()["run"]["status"] == "cancelled"
        assert h.recover(rid).status_code == 409
        assert h.actions() == [] and h.status(rid) == "cancelled"
        assert any(e["kind"] == "run_cancelled" for e in h.detail(rid)["events"])
    finally:
        h.stop()


# ----------------------------------------------------------------------------- R5-02 concurrent recovery
def test_r5_02_concurrent_recover_claims_once(settings):
    h = Harness(settings)
    try:
        rid = h.create(fault={"agent": "strategy", "kind": "provider_error", "fail_attempts": 2})
        assert h.status(rid) == "failed"
        both_read = threading.Barrier(2, timeout=WAIT)
        original = h.runner.store.require_run

        def read_then_meet(run_id):
            run = original(run_id)
            both_read.wait()          # both callers have read 'failed' before either writes
            return run
        h.runner.store.require_run = read_then_meet
        results = []

        def call():
            results.append(h.client.post(f"/api/runs/{rid}/recover", headers=APPROVER))
        threads = [threading.Thread(target=call) for _ in range(2)]
        [t.start() for t in threads]
        [t.join(WAIT) for t in threads]
        h.runner.store.require_run = original
        h.runner._executor.shutdown(wait=True)   # every scheduled recovery job has finished
        codes = sorted(r.status_code for r in results)
        d = h.runner.run_detail(rid)
        starts = [e for e in d["events"] if e["kind"] == "recover_started"]
        assert codes == [202, 409], f"recover responses {codes}"
        assert len(starts) == 1, f"{len(starts)} recover_started events"
        assert d["recover_count"] == 1
        assert d["status"] == "awaiting_approval"
    finally:
        h.stop()


def test_r5_02_transition_is_strict_unless_marked_idempotent(h):
    rid = h.create()
    with pytest.raises(Exception) as e:
        h.runner.store.transition(rid, {"failed", "interrupted"}, "awaiting_approval")
    assert getattr(e.value, "code", "") == "invalid_transition"


def test_r5_02_recover_on_finished_checkpoint_does_not_leave_run_running(h):
    """If the checkpoint says the graph finished but the store is not terminal, recovery must
    reconcile explicitly instead of leaving the run 'running'."""
    rid = h.create()
    assert h.decide(rid).status_code == 200
    store = h.runner.store
    with store.tx() as c:   # simulate an inconsistent store (e.g. lost terminal write)
        c.execute("UPDATE runs SET status='interrupted', retryable=1 WHERE run_id=?", (rid,))
    assert h.recover(rid).status_code == 202
    d = h.detail(rid)
    assert d["status"] != "running"
    assert d["status"] == "completed" and len(h.actions(rid)) == 1
    assert any(e["kind"] == "recover_plan" and "finished" in e["data"]["action"] for e in d["events"])


def test_r5_01f_cancel_during_recovery_of_committed_action_is_refused(settings):
    """Follow-up review of 3860c12: crash AFTER the ledger commit -> restart -> Recover claims the run
    (status running) -> pause the recovery job -> cancel. The committed-action check must apply to every
    cancel acceptance path, and the final state must never claim 'No action executed'."""
    h = Harness(settings, crash_hook=crash_once("after_commit"))
    try:
        rid = h.create()
        prop = h.pending(rid)
        with pytest.raises(SimulatedCrash):
            h.runner.decide(rid, proposal_id=prop["proposal_id"], revision=1, proposal_sha256=prop["sha256"],
                            decision="approve", comment="", changes=None, idempotency_key=key(), actor="bob",
                            role="approver")
        h.restart()
        assert h.status(rid) == "interrupted" and len(h.actions(rid)) == 1
        pause = Pause()
        original = h.runner._recover_locked

        def paused_recovery(run_id):
            pause.hold()             # run is claimed (status running) but recovery has not resumed the graph
            return original(run_id)
        h.runner._recover_locked = paused_recovery
        assert h.client.post(f"/api/runs/{rid}/recover", headers=APPROVER).status_code == 202
        assert pause.entered.wait(WAIT)
        assert h.status(rid) == "running"
        c = h.client.post(f"/api/runs/{rid}/cancel", json={"idempotency_key": key()}, headers=APPROVER)
        pause.release.set()
        h.runner.wait(rid)
        h.runner._recover_locked = original
        d = h.detail(rid)
        assert c.status_code == 409 and c.json()["error"] == "action_already_committed", c.text
        assert d["status"] == "completed" and len(h.actions(rid)) == 1
        assert "No action executed" not in json.dumps(d["result"])
        assert d["cancel_requested"] is False
    finally:
        h.stop()


def test_r5_01f_store_invariant_committed_action_cannot_be_cancelled_or_rejected(h):
    rid = h.create()
    assert h.decide(rid).status_code == 200 and len(h.actions(rid)) == 1
    for status in ("cancelled", "rejected"):
        with pytest.raises(Exception) as e:
            h.runner.store.transition(rid, None if status == "cancelled" else {"completed"}, status)
        assert getattr(e.value, "code", "") in ("action_already_committed", "invalid_transition")
    with h.runner.store.tx() as c:  # even a direct low-level write is refused
        with pytest.raises(Exception) as e:
            h.runner.store._set(c, rid, status="cancelled")
    assert e.value.code == "action_already_committed"
    assert h.status(rid) == "completed"
