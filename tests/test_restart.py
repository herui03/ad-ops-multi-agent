"""Acceptance cases 2 and 10: restart while pending, and crashes near the action boundary.

A "restart" closes the runner (graph, checkpointer connection, store connection) and builds a new
one on the same SQLite files. A "crash" raises SimulatedCrash (a BaseException, so no
`except Exception` handler swallows it) at a precise point, leaving whatever was committed.
"""
from __future__ import annotations

import json

import pytest

from backend.simulator import SimulatedCrash
from tests.conftest import Harness, ScriptedProvider, key


def crash_at(point: str):
    fired = {"n": 0}

    def hook(p: str):
        if p == point and fired["n"] == 0:
            fired["n"] += 1
            raise SimulatedCrash(point)
    return hook


def approve_direct(h: Harness, rid: str, idem: str | None = None):
    prop = h.pending(rid)
    return h.runner.decide(rid, proposal_id=prop["proposal_id"], revision=prop["revision"],
                           proposal_sha256=prop["sha256"], decision="approve", comment="", changes=None,
                           idempotency_key=idem or key(), actor="bob", role="approver")


def test_ac2_restart_while_pending_then_exact_approval_resumes_same_run(h):
    rid = h.create()
    before = h.detail(rid)
    assert before["status"] == "awaiting_approval" and h.actions() == []
    h.restart()
    after = h.detail(rid)
    assert after["status"] == "awaiting_approval"            # still a real pause after restart
    assert after["checkpoint"]["thread_id"] == before["checkpoint"]["thread_id"]
    assert after["checkpoint"]["pending_interrupt"] == before["checkpoint"]["pending_interrupt"]
    assert not any(e["kind"] == "restart_detected" for e in after["events"])
    r = h.decide(rid)
    assert r.status_code == 200 and r.json()["run"]["status"] == "completed"
    acts = h.actions()
    assert len(acts) == 1 and acts[0]["run_id"] == rid
    assert h.detail(rid)["checkpoint"]["next_nodes"] == []
    assert h.client.get("/api/dashboard/stats").json()["pending_approvals"] == 0


def test_ac10_crash_after_commit_is_reconciled_not_reexecuted(settings):
    h = Harness(settings, crash_hook=crash_at("after_commit"))
    try:
        rid = h.create()
        with pytest.raises(SimulatedCrash):
            approve_direct(h, rid)
        assert len(h.actions()) == 1                    # the ledger row committed before the "crash"
        assert h.runner.store.get_run(rid)["status"] == "resuming"
        h.restart()                                     # new process, no crash hook
        d = h.detail(rid)
        assert d["status"] == "interrupted" and d["error_code"] == "interrupted_by_restart"
        assert any(e["kind"] == "restart_detected" for e in d["events"])
        assert h.recover(rid).status_code == 202
        d = h.detail(rid)
        assert d["status"] == "completed"
        assert len(h.actions()) == 1                    # replay protection: no second action
        assert any(e["kind"] == "simulated_action_replay_detected" for e in d["events"])
        assert d["result"]["replay_detected"] is True
    finally:
        h.stop()


def test_ac10_crash_before_commit_rolls_back_then_executes_once(settings):
    h = Harness(settings, crash_hook=crash_at("before_commit"))
    try:
        rid = h.create()
        with pytest.raises(SimulatedCrash):
            approve_direct(h, rid)
        assert h.actions() == []                        # transaction rolled back
        h.restart()
        assert h.status(rid) == "interrupted"
        assert h.recover(rid).status_code == 202
        d = h.detail(rid)
        assert d["status"] == "completed" and len(h.actions()) == 1
        assert not any(e["kind"] == "simulated_action_replay_detected" for e in d["events"])
    finally:
        h.stop()


def test_ac10_crash_after_decision_recorded_before_graph_resume(h, monkeypatch):
    """Decision committed, process dies before Command(resume=...) is applied: recover re-applies it once."""
    rid = h.create()

    def die(*_a, **_k):
        raise SimulatedCrash("before resume")
    monkeypatch.setattr(h.runner, "_apply_decision", die)
    with pytest.raises(SimulatedCrash):
        approve_direct(h, rid)
    assert h.runner.store.get_run(rid)["status"] == "resuming" and h.actions() == []
    h.restart()
    d = h.detail(rid)
    assert d["status"] == "interrupted" and d["checkpoint"]["next_nodes"] == ["approval_gate"]
    assert h.recover(rid).status_code == 202
    d = h.detail(rid)
    assert d["status"] == "completed" and len(h.actions()) == 1
    assert all(x["applied"] for x in d["decisions"])
    assert any(e["kind"] == "recover_plan" and e["data"]["action"] == "re-apply recorded decision at gate"
               for e in d["events"])


def test_crash_mid_agents_resumes_from_last_checkpoint_without_rerunning_done_steps(settings):
    def die(_payload):
        raise SimulatedCrash("creative")
    crashing = ScriptedProvider({"creative": die})
    h = Harness(settings, provider=crashing)
    try:
        rid = h.create(wait=False)
        with pytest.raises(SimulatedCrash):
            h.runner.wait(rid)
        assert h.runner.store.get_run(rid)["status"] == "running"
        counting = ScriptedProvider()
        h.restart(provider=counting)
        assert h.status(rid) == "interrupted"
        assert h.recover(rid).status_code == 202
        d = h.detail(rid)
        assert d["status"] == "awaiting_approval"
        # insight + strategy + planner were checkpointed before the crash and are not called again
        assert counting.calls == {"creative": 1, "compliance": 1}
    finally:
        h.stop()


def test_restart_while_queued_or_running_is_explicit_not_silent(h):
    rid = h.create()
    h.runner.store.transition(rid, None, "running")   # emulate a worker that died mid-flight
    h.restart()
    d = h.detail(rid)
    assert d["status"] == "interrupted" and d["retryable"] is True
    ev = [e for e in d["events"] if e["kind"] == "restart_detected"][-1]
    assert ev["data"]["previous_status"] == "running"


def test_durable_history_survives_restart(h):
    rid = h.create()
    h.decide(rid, "revise", changes={"budget_total": 45_000})
    h.decide(rid, "reject", comment="<b>too late</b>")
    before = h.detail(rid)
    h.restart()
    after = h.detail(rid)
    assert [e["seq"] for e in after["events"]] == [e["seq"] for e in before["events"]]
    assert [d["decision"] for d in after["decisions"]] == ["revise", "reject"]
    assert after["decisions"][1]["comment"] == "<b>too late</b>"
    assert json.dumps(after["proposals"]) == json.dumps(before["proposals"])
