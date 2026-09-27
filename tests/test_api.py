"""Acceptance cases 13 and 14, WebSocket hardening, retired endpoints, and real dashboard aggregates."""
from __future__ import annotations

import csv
import io
import json
import socket

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import APPROVER, CAMPAIGN, REQ, Harness, key

XSS = '<img src=x onerror="alert(1)"><script>alert("x")</script>'
FORMULAS = ["=HYPERLINK(\"http://evil.example\",\"click\")", "+1+1", "-2+3", "@SUM(A1:A2)"]


def test_ac13_user_text_is_stored_verbatim_and_exported_safely(h):
    rid = h.create(f"Plan a campaign for Harbourlight Hotel {XSS} S$30,000")
    d = h.detail(rid)
    assert XSS in d["request_text"]                         # data is preserved, not mangled
    for f in FORMULAS:
        r = h.decide(rid, "reject" if f == FORMULAS[-1] else "revise",
                     **({"changes": {"budget_total": 30_000 + FORMULAS.index(f)}} if f != FORMULAS[-1] else {}),
                     comment=f)
        assert r.status_code == 200, r.text
    j = h.client.get(f"/api/runs/{rid}/export.json")
    assert j.headers["content-type"].startswith("application/json")
    assert j.headers["x-content-type-options"] == "nosniff" and "attachment" in j.headers["content-disposition"]
    assert XSS in j.json()["request_text"]
    c = h.client.get(f"/api/runs/{rid}/export.csv")
    assert c.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(c.text)))
    cells = [cell for row in rows for cell in row]
    assert not any(cell.startswith(("=", "+", "-", "@")) for cell in cells), "formula-leading cell in CSV"
    comments = [row[3] for row in rows if row[0] == "decision"]
    assert comments == ["'" + f for f in FORMULAS]


def test_ac14_full_demo_runs_without_key_or_network(settings, monkeypatch):
    assert settings.groq_api_key.get_secret_value() == "" and settings.is_demo

    def no_network(*_a, **_k):
        raise AssertionError("network access attempted in demo mode")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    h = Harness(settings)
    try:
        meta = h.client.get("/api/meta").json()
        assert meta["provider_mode"] == "demo" and "no network" in meta["provider_label"]
        rid = h.create()
        assert h.status(rid) == "awaiting_approval"
        assert h.decide(rid).json()["run"]["status"] == "completed"
        assert len(h.actions()) == 1
        q = h.create("Who must approve a campaign launch?")
        assert h.detail(q)["result"]["answer"]["outcome"] == "answered"
    finally:
        h.stop()


def test_settings_never_expose_key():
    from backend.config import Settings
    s = Settings(_env_file=None, groq_api_key="gsk_" + "Z" * 20)
    assert "gsk_" not in repr(s) and "gsk_" not in str(s.model_dump())


def test_live_provider_requires_key():
    from backend.config import Settings
    from backend.providers import build_provider
    with pytest.raises(RuntimeError):
        build_provider(Settings(_env_file=None, llm_provider="groq", groq_api_key=""))


def test_websocket_is_read_only_and_validates_input(h):
    rid = h.create()
    prop = h.pending(rid)
    with h.client.websocket_connect(f"/ws/runs/{rid}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["run"]["status"] == "awaiting_approval"
        ws.send_text("{not json")
        assert ws.receive_json()["code"] == "malformed_json"
        ws.send_text(json.dumps([1, 2]))
        assert ws.receive_json()["code"] == "invalid_message"
        ws.send_text("x" * 5000)
        assert ws.receive_json()["code"] == "message_too_large"
        ws.send_text(json.dumps({"type": "approval_decision", "approval_id": prop["proposal_id"],
                                 "proposal_id": prop["proposal_id"], "decision": "approved"}))
        assert ws.receive_json()["code"] == "unsupported_message"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
    d = h.detail(rid)
    assert d["status"] == "awaiting_approval" and d["decisions"] == [] and h.actions() == []


def test_websocket_streams_persisted_events_and_reconnect_reads_state(h):
    rid = h.create()
    with h.client.websocket_connect(f"/ws/runs/{rid}") as ws:
        ws.receive_json()
        h.decide(rid)
        msg = ws.receive_json()
        while msg["type"] != "events":
            msg = ws.receive_json()
        kinds = [e["kind"] for e in msg["events"]]
        assert "decision_recorded" in kinds
    with h.client.websocket_connect(f"/ws/runs/{rid}") as ws:   # reconnect: state comes from the store
        snap = ws.receive_json()
        assert snap["run"]["status"] == "completed" and len(snap["run"]["actions"]) == 1


def test_websocket_disconnect_does_not_affect_workflow(h):
    rid = h.create(wait=False)
    with h.client.websocket_connect(f"/ws/runs/{rid}") as ws:
        ws.receive_json()
    h.runner.wait(rid)
    assert h.status(rid) == "awaiting_approval" and h.actions() == []


def test_websocket_unknown_run(h):
    with h.client.websocket_connect("/ws/runs/run_doesnotexist") as ws:
        assert ws.receive_json()["code"] == "run_not_found"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_retired_endpoints_are_closed_and_change_nothing(h):
    rid = h.create()
    prop = h.pending(rid)
    r = h.client.post(f"/api/approvals/{prop['proposal_id']}/decide",
                      json={"approval_id": prop["proposal_id"], "decision": "approved"})
    assert r.status_code == 410
    assert h.client.post("/api/chat", json={"message": "hi"}).status_code == 410
    with h.client.websocket_connect("/ws/legacy-session") as ws:
        assert ws.receive_json()["code"] == "endpoint_removed"
    d = h.detail(rid)
    assert d["status"] == "awaiting_approval" and d["decisions"] == [] and h.actions() == []


def test_dashboard_counts_come_from_the_store(h):
    empty = h.client.get("/api/dashboard/stats").json()
    assert empty["runs_total"] == 0 and empty["pending_approvals"] == 0 and empty["simulated_actions"] == 0
    a, b, c = h.create(), h.create(), h.create()
    assert h.client.get("/api/dashboard/stats").json()["pending_approvals"] == 3
    h.decide(a)
    h.decide(b, "reject")
    s = h.client.get("/api/dashboard/stats").json()
    assert s["pending_approvals"] == 1 and s["simulated_actions"] == 1 and s["simulated_amount_committed"] == 80_000
    assert s["runs_by_status"] == {"completed": 1, "rejected": 1, "awaiting_approval": 1}
    h.restart()
    s2 = h.client.get("/api/dashboard/stats").json()
    assert s2["pending_approvals"] == 1 and s2["simulated_actions"] == 1 and s2["runs_total"] == 3
    h.client.post(f"/api/runs/{c}/cancel", json={"idempotency_key": key()}, headers=REQ)
    assert h.client.get("/api/dashboard/stats").json()["pending_approvals"] == 0


def test_meta_labels_demo_limits(h):
    m = h.client.get("/api/meta").json()
    assert "not authentication" in m["role_note"]
    assert "No real ad platform" in m["integration"]
    assert m["limits"]["max_request_chars"] == 2000


def test_unknown_run_and_source(h):
    assert h.client.get("/api/runs/run_missing").status_code == 404
    assert h.client.get("/api/source", params={"chunk_id": "nope"}).status_code == 404
