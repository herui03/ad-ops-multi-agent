"""The simulated action executor ("SimAds sandbox").

There is no real ad integration. "Executing" an approved proposal means writing one row to the
`sim_actions` ledger in the application database. That row is the whole side effect, so the
transaction boundary is exact:

  * The gate check (an `approve` decision exists for this exact proposal id, revision and sha256,
    and the proposal is marked approved) and the ledger insert happen in ONE SQLite write
    transaction.
  * The ledger row is keyed by `run_id:proposal_id:revision` (UNIQUE). A replay of the execute node
    after a crash finds the row and returns it instead of writing a second one.

Crash windows and what happens:
  * Crash before commit: the transaction rolls back and there is no action. Recover re-runs the node
    and commits it once.
  * Crash after commit, before LangGraph checkpoints the node: Recover re-runs the node, which finds
    the existing row and reports `replayed=True` (reconciled, not re-executed).
A real ad API would add a third window (remote call succeeded, local commit lost) that a local
transaction cannot close; it would need the remote side to honour an idempotency key, or a
reconciliation read against the platform. This project does not claim exactly-once delivery to any
external system.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from backend.errors import Conflict
from backend.store import Store, canonical_json, new_id


class SimulatedCrash(BaseException):
    """Test-only: emulates the process dying at a precise point (not caught by `except Exception`)."""


class GateViolation(Conflict):
    pass


class Simulator:
    def __init__(self, store: Store, crash_hook: Callable[[str], None] | None = None):
        self.store = store
        self.crash_hook = crash_hook

    def _hook(self, point: str) -> None:
        if self.crash_hook:
            self.crash_hook(point)

    def execute(self, run_id: str, proposal_id: str, revision: int, proposal_sha256: str) -> tuple[dict, bool]:
        key = f"{run_id}:{proposal_id}:{revision}"
        with self.store.tx() as c:
            existing = c.execute("SELECT * FROM sim_actions WHERE idempotency_key=?", (key,)).fetchone()
            if existing is not None:
                Store._event(c, run_id, "simulated_action_replay_detected",
                             {"action_id": existing["action_id"], "idempotency_key": key,
                              "note": "execute node re-ran after an interruption; existing ledger row reused"})
                return Store._action_dict(existing), True
            prop = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            approved = c.execute(
                "SELECT decision_id FROM decisions WHERE run_id=? AND proposal_id=? AND revision=? AND"
                " proposal_sha256=? AND decision='approve'", (run_id, proposal_id, revision, proposal_sha256)).fetchone()
            if (prop is None or prop["run_id"] != run_id or prop["revision"] != revision
                    or prop["sha256"] != proposal_sha256 or prop["status"] != "approved" or approved is None):
                raise GateViolation("gate_violation", "no approve decision recorded for this exact proposal revision")
            payload = json.loads(prop["payload_json"])
            action_id = new_id("simact")
            self._hook("before_commit")  # raising here rolls the transaction back
            c.execute("INSERT INTO sim_actions(action_id, idempotency_key, run_id, proposal_id, revision, proposal_sha256,"
                      " action_type, amount, currency, payload_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (action_id, key, run_id, proposal_id, revision, proposal_sha256, payload["action_type"],
                       float(payload["amount"]), payload["currency"], canonical_json(payload), time.time()))
            Store._event(c, run_id, "simulated_action_committed",
                         {"action_id": action_id, "action_type": payload["action_type"], "amount": payload["amount"],
                          "approval_decision_id": approved["decision_id"], "integration": payload["integration"]})
        self._hook("after_commit")
        return self.store.sim_action_by_key(key), False


def demo_crash_hook(point_setting: str, marker: Path) -> Callable[[str], None]:
    """Demo recovery drill: kill the process once at the configured point (demo mode only)."""
    def hook(point: str) -> None:
        if point == point_setting and not marker.exists():
            marker.write_text(f"crash drill fired at {point} {time.time()}\n")
            os._exit(70)
    return hook
