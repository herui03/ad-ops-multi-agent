"""Shared test harness: a real WorkflowRunner + FastAPI app on a temp SQLite directory.

`Harness.restart()` closes the runner and builds a new one on the same files, which is how the
tests model a process restart (new graph, new checkpointer connection, new store connection).
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.agents.orchestrator import WorkflowRunner
from backend.config import Settings
from backend.main import create_app
from backend.providers import DemoProvider, Provider

REQ = {"X-Demo-Role": "requester", "X-Demo-Actor": "alice"}
APPROVER = {"X-Demo-Role": "approver", "X-Demo-Actor": "bob"}
VIEWER = {"X-Demo-Role": "viewer", "X-Demo-Actor": "vera"}
CAMPAIGN = "Plan a year-end campaign for Harbourlight Hotel with a S$80,000 budget"


def key() -> str:
    return f"test-{uuid.uuid4().hex}"


class ScriptedProvider(Provider):
    """Demo provider with per-role overrides: a string (raw output), an Exception, or a callable."""

    def __init__(self, overrides: dict | None = None, mode: str = "demo"):
        self.inner = DemoProvider()
        self.overrides = overrides or {}
        self.mode, self.name, self.label = mode, "scripted-test", f"TEST scripted provider ({mode})"
        self.calls: Counter = Counter()

    def complete(self, role, system, payload):
        self.calls[role] += 1
        o = self.overrides.get(role)
        if o is None:
            return self.inner.complete(role, system, payload)
        if isinstance(o, BaseException):
            raise o
        if callable(o):
            return o(payload)
        return o if isinstance(o, str) else json.dumps(o)


class Harness:
    def __init__(self, settings: Settings, provider: Provider | None = None, crash_hook=None):
        self.settings = settings
        self.start(provider, crash_hook)

    def start(self, provider=None, crash_hook=None):
        self.provider = provider
        self.runner = WorkflowRunner(self.settings, provider=provider, crash_hook=crash_hook)
        self.app = create_app(self.settings, runner=self.runner)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def stop(self):
        self.client.__exit__(None, None, None)
        self.runner.close()

    def restart(self, provider=None, crash_hook=None):
        self.stop()
        self.start(provider, crash_hook)

    # --- helpers
    def create(self, text: str = CAMPAIGN, fault: dict | None = None, headers=REQ, wait=True) -> str:
        body = {"request": text}
        if fault:
            body["demo_fault"] = fault
        r = self.client.post("/api/runs", json=body, headers=headers)
        assert r.status_code == 202, r.text
        rid = r.json()["run"]["run_id"]
        if wait:
            self.runner.wait(rid)
        return rid

    def detail(self, rid: str) -> dict:
        r = self.client.get(f"/api/runs/{rid}")
        assert r.status_code == 200, r.text
        return r.json()

    def status(self, rid: str) -> str:
        return self.detail(rid)["status"]

    def pending(self, rid: str) -> dict:
        return self.detail(rid)["proposals"][-1]

    def decide(self, rid: str, decision: str = "approve", *, prop: dict | None = None, idem: str | None = None,
               headers=APPROVER, **extra):
        prop = prop or self.pending(rid)
        body = {"proposal_id": prop["proposal_id"], "revision": prop["revision"], "proposal_sha256": prop["sha256"],
                "decision": decision, "idempotency_key": idem or key(), **extra}
        return self.client.post(f"/api/runs/{rid}/decisions", json=body, headers=headers)

    def actions(self, rid: str | None = None) -> list[dict]:
        return self.runner.store.actions(rid)

    def recover(self, rid: str, headers=APPROVER, wait=True):
        r = self.client.post(f"/api/runs/{rid}/recover", headers=headers)
        if wait and r.status_code == 202:
            self.runner.wait(rid)
        return r


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", _env_file=None, provider_timeout_s=0.5, llm_provider="demo",
                    groq_api_key="")


@pytest.fixture
def h(settings):
    harness = Harness(settings)
    yield harness
    try:
        harness.stop()
    except Exception:
        pass
