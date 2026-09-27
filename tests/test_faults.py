"""Acceptance cases 8 and 16: bounded, honest failure; plan validation; input/queue/retry limits.

Also covers baseline defects D5-D8 (fail-open DAG, failed agents shown as completed, malformed plan
fallback, parse errors counted as success).
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from backend.contracts import MAX_PLAN_STEPS
from backend.providers import ProviderError
from tests.conftest import APPROVER, CAMPAIGN, REQ, Harness, ScriptedProvider


def step_by_agent(d, agent):
    return next(s for s in d["steps"] if s["agent"] == agent)


@pytest.mark.parametrize("kind,code", [("timeout", "timeout"), ("provider_error", "provider_error"),
                                       ("malformed_json", "malformed_output"), ("wrong_schema", "schema_violation")])
def test_ac8_persistent_fault_fails_bounded_and_honest(h, kind, code):
    rid = h.create(fault={"agent": "strategy", "kind": kind, "fail_attempts": 2})
    d = h.detail(rid)
    assert d["status"] == "failed" and d["error_code"] == code and d["retryable"] is True
    strat = step_by_agent(d, "strategy")
    assert strat["status"] == "failed" and strat["attempts"] == 2 and strat["error_code"] == code
    # downstream steps never ran; nothing was synthesized from a failed prerequisite
    assert step_by_agent(d, "creative")["status"] == "pending"
    assert step_by_agent(d, "compliance")["status"] == "pending"
    assert d["proposals"] == [] and d["result"] is None and h.actions() == []
    attempts = [e for e in d["events"] if e["kind"] == "provider_attempt" and e["data"]["role"] == "strategy"]
    assert [a["data"]["outcome"] for a in attempts] == [code, code]
    assert not any(e["kind"] == "step_completed" and e["data"]["agent"] == "strategy" for e in d["events"])


def test_ac8_recover_after_failure_repeats_only_the_failed_step(h):
    rid = h.create(fault={"agent": "strategy", "kind": "provider_error", "fail_attempts": 2})
    assert h.status(rid) == "failed"
    insight_attempts = step_by_agent(h.detail(rid), "insight")["attempts"]
    assert h.recover(rid).status_code == 202
    d = h.detail(rid)
    assert d["status"] == "awaiting_approval" and d["recover_count"] == 1
    assert step_by_agent(d, "insight")["attempts"] == insight_attempts      # not re-run
    assert step_by_agent(d, "strategy")["status"] == "completed"
    assert h.actions() == []


def test_transient_fault_is_retried_within_budget(h):
    rid = h.create(fault={"agent": "creative", "kind": "malformed_json", "fail_attempts": 1})
    d = h.detail(rid)
    assert d["status"] == "awaiting_approval"
    assert step_by_agent(d, "creative")["attempts"] == 2
    outcomes = [e["data"]["outcome"] for e in d["events"] if e["kind"] == "provider_attempt"
                and e["data"]["role"] == "creative"]
    assert outcomes == ["malformed_output", "ok"]


def test_recovery_budget_is_bounded(settings):
    settings.max_recoveries = 1
    h = Harness(settings)
    try:
        rid = h.create(fault={"agent": "insight", "kind": "provider_error", "fail_attempts": 5})
        assert h.status(rid) == "failed"
        assert h.recover(rid).status_code == 202
        d = h.detail(rid)
        assert d["status"] == "failed" and d["retryable"] is False
        r = h.recover(rid)
        assert r.status_code == 409 and r.json()["error"] in ("not_retryable", "recovery_limit")
    finally:
        h.stop()


def test_planner_failure_does_not_fall_back_to_unapproved_work(settings):
    """Baseline D7: malformed planner output used to run an 'insight' task anyway."""
    p = ScriptedProvider({"planner": "this is not json"})
    h = Harness(settings, provider=p)
    try:
        rid = h.create()
        d = h.detail(rid)
        assert d["status"] == "failed" and d["error_code"] == "malformed_output"
        assert d["steps"] == [] and set(p.calls) == {"planner"} and p.calls["planner"] == 2
    finally:
        h.stop()


BAD_PLANS = {
    "cycle": [{"id": "s1", "agent": "strategy", "task": "t", "depends_on": ["s3"]},
              {"id": "s2", "agent": "creative", "task": "t", "depends_on": ["s1"]},
              {"id": "s3", "agent": "compliance", "task": "t", "depends_on": ["s2"]}],
    "dangling": [{"id": "s1", "agent": "strategy", "task": "t", "depends_on": ["s9"]},
                 {"id": "s2", "agent": "creative", "task": "t", "depends_on": ["s1"]},
                 {"id": "s3", "agent": "compliance", "task": "t", "depends_on": ["s2"]}],
    "unknown_agent": [{"id": "s1", "agent": "launcher", "task": "t", "depends_on": []}],
    "duplicate_ids": [{"id": "s1", "agent": "strategy", "task": "t", "depends_on": []},
                      {"id": "s1", "agent": "creative", "task": "t", "depends_on": []}],
    "compliance_before_creative": [{"id": "s1", "agent": "strategy", "task": "t", "depends_on": []},
                                   {"id": "s2", "agent": "compliance", "task": "t", "depends_on": ["s1"]},
                                   {"id": "s3", "agent": "creative", "task": "t", "depends_on": ["s1"]}],
    "missing_compliance": [{"id": "s1", "agent": "strategy", "task": "t", "depends_on": []},
                           {"id": "s2", "agent": "creative", "task": "t", "depends_on": ["s1"]}],
    "too_many": [{"id": f"s{i}", "agent": "insight", "task": "t", "depends_on": []}
                 for i in range(1, MAX_PLAN_STEPS + 2)],
}


@pytest.mark.parametrize("name", sorted(BAD_PLANS))
def test_invalid_plan_dag_fails_closed_without_execution(settings, name):
    """Baseline D5: cycles and dangling references used to execute every remaining step."""
    plan = {"route": "workflow", "workflow_type": "campaign_launch", "steps": BAD_PLANS[name]}
    p = ScriptedProvider({"planner": plan})
    h = Harness(settings, provider=p)
    try:
        rid = h.create()
        d = h.detail(rid)
        assert d["status"] == "failed" and d["error_code"] == "schema_violation", d["error_message"]
        assert d["steps"] == [] and set(p.calls) == {"planner"}
        assert d["proposals"] == [] and h.actions() == []
    finally:
        h.stop()


@pytest.mark.parametrize("raw", ["<<not json>>", json.dumps(["a", "list"]), json.dumps("scalar"),
                                 json.dumps({"client_name": "x"})])
def test_agent_malformed_or_wrong_schema_is_failure_not_success(settings, raw):
    """Baseline D8: raw_response/_parse_error used to count as success."""
    h = Harness(settings, provider=ScriptedProvider({"insight": raw}))
    try:
        rid = h.create()
        d = h.detail(rid)
        ins = step_by_agent(d, "insight")
        assert d["status"] == "failed" and ins["status"] == "failed" and ins["output"] is None
        assert d["error_code"] in ("malformed_output", "schema_violation")
    finally:
        h.stop()


def test_provider_error_text_is_redacted(settings):
    secret = "gsk_" + "A1b2C3d4E5f6G7h8I9j0"
    h = Harness(settings, provider=ScriptedProvider({"insight": ProviderError(f"401 bad key {secret} Bearer {secret}")}))
    try:
        rid = h.create()
        blob = json.dumps(h.detail(rid)) + h.client.get(f"/api/runs/{rid}/export.csv").text
        assert secret not in blob and "[REDACTED]" in blob
    finally:
        h.stop()


def test_ac16_input_limits(h):
    too_long = h.client.post("/api/runs", json={"request": "x" * 2001}, headers=REQ)
    assert too_long.status_code == 413 and too_long.json()["error"] == "request_too_long"
    assert h.client.post("/api/runs", json={"request": "   "}, headers=REQ).status_code == 400
    assert h.client.post("/api/runs", json={"request": ""}, headers=REQ).status_code == 422
    assert h.client.post("/api/runs", json={"request": "hi", "extra": 1}, headers=REQ).status_code == 422
    huge = h.client.post("/api/runs", content=b"{" + b" " * (70 * 1024) + b"}", headers={**REQ,
                         "Content-Type": "application/json"})
    assert huge.status_code == 413
    bad_fault = h.client.post("/api/runs", json={"request": CAMPAIGN, "demo_fault": {"kind": "meltdown"}}, headers=REQ)
    assert bad_fault.status_code == 422
    rid = h.create()
    long_comment = h.decide(rid, comment="c" * 501)
    assert long_comment.status_code == 413
    bad_key = h.decide(rid, idem="short")
    assert bad_key.status_code == 422
    assert h.status(rid) == "awaiting_approval" and h.actions() == []


def test_ac16_queue_limit_returns_429_and_releases_slots(settings):
    settings.max_active_runs = 1
    release = threading.Event()

    def slow(payload):
        release.wait(5)
        from backend.demo_generators import plan
        return json.dumps(plan(payload))

    h = Harness(settings, provider=ScriptedProvider({"planner": slow}))
    try:
        first = h.create(wait=False)
        second = h.client.post("/api/runs", json={"request": CAMPAIGN}, headers=REQ)
        assert second.status_code == 429 and second.json()["error"] == "queue_full"
        release.set()
        h.runner.wait(first)
        time.sleep(0.05)
        third = h.client.post("/api/runs", json={"request": CAMPAIGN}, headers=REQ)
        assert third.status_code == 202
        assert len(h.client.get("/api/runs").json()["runs"]) == 2   # the rejected request created nothing
    finally:
        release.set()
        h.stop()


def test_demo_fault_rejected_for_live_provider(settings):
    h = Harness(settings, provider=ScriptedProvider(mode="live"))
    try:
        r = h.client.post("/api/runs", json={"request": CAMPAIGN,
                                             "demo_fault": {"kind": "timeout", "agent": "strategy"}}, headers=REQ)
        assert r.status_code == 400 and r.json()["error"] == "fault_injection_unavailable"
    finally:
        h.stop()


def test_pitch_workflow_completes_without_gate_because_it_has_no_action(h):
    rid = h.create("Prepare a pitch comparing channels for NovaByte")
    d = h.detail(rid)
    assert d["status"] == "completed" and d["result"]["kind"] == "deliverable"
    assert d["proposals"] == [] and h.actions() == []
