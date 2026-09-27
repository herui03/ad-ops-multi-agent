"""Durable application store (SQLite).

Holds everything the UI and the approval gate rely on: runs, the event history, agent step
results, proposal revisions, human decisions, idempotency records and the simulated action
ledger. LangGraph's checkpointer lives in a separate SQLite file (see runner.py).

Every multi-row change runs inside `BEGIN IMMEDIATE`, so SQLite takes the write lock up front:
two concurrent approvals for the same proposal serialize, and exactly one of them can move the
run out of `awaiting_approval`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.errors import Conflict, Forbidden, NotFound, Unprocessable

TERMINAL = {"completed", "rejected", "cancelled"}
DECISIONS = {"approve", "reject", "revise", "cancel"}
APPROVER_DECISIONS = {"approve", "reject", "revise"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    requester TEXT NOT NULL,
    request_text TEXT NOT NULL,
    provider_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    route TEXT,
    workflow_type TEXT,
    plan_json TEXT,
    error_code TEXT,
    error_message TEXT,
    retryable INTEGER NOT NULL DEFAULT 0,
    recover_count INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    demo_fault_json TEXT,
    result_json TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_run ON run_events(run_id, seq);
CREATE TABLE IF NOT EXISTS run_steps (
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    output_json TEXT,
    error_code TEXT,
    error_message TEXT,
    duration_ms INTEGER,
    PRIMARY KEY (run_id, step_id)
);
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (run_id, revision)
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    proposal_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    changes_json TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    applied INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sim_actions (
    action_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    proposal_sha256 TEXT NOT NULL,
    action_type TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fault_counters (
    run_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (run_id, agent)
);
"""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: Any) -> str:
    data = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ plumbing
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    @staticmethod
    def _event(conn: sqlite3.Connection, run_id: str, kind: str, data: dict | None = None) -> None:
        conn.execute("INSERT INTO run_events(run_id, ts, kind, data_json) VALUES (?,?,?,?)",
                     (run_id, time.time(), kind, canonical_json(data or {})))

    # ------------------------------------------------------------------ runs
    def create_run(self, *, requester: str, request_text: str, provider_mode: str,
                   demo_fault: dict | None) -> dict:
        run_id = new_id("run")
        now = time.time()
        with self.tx() as c:
            c.execute(
                "INSERT INTO runs(run_id, thread_id, created_at, updated_at, requester, request_text, provider_mode,"
                " status, demo_fault_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, f"thread-{run_id}", now, now, requester, request_text, provider_mode, "queued",
                 canonical_json(demo_fault) if demo_fault else None))
            self._event(c, run_id, "run_created", {"requester": requester, "provider_mode": provider_mode,
                                                   "demo_fault": demo_fault})
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict | None:
        rows = self._q("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return self._run_dict(rows[0]) if rows else None

    def require_run(self, run_id: str) -> dict:
        run = self.get_run(run_id)
        if run is None:
            raise NotFound("run_not_found", f"no run with id {run_id!r}")
        return run

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for key in ("plan_json", "demo_fault_json", "result_json"):
            raw = d.pop(key)
            d[key[:-5]] = json.loads(raw) if raw else None
        d["retryable"] = bool(d["retryable"])
        d["cancel_requested"] = bool(d["cancel_requested"])
        return d

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self._q("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (int(limit),))
        return [self._run_dict(r) for r in rows]

    def runs_with_status(self, statuses: set[str]) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        return [self._run_dict(r) for r in self._q(f"SELECT * FROM runs WHERE status IN ({marks})", tuple(statuses))]

    def transition(self, run_id: str, allowed_from: set[str] | None, to: str, event: str | None = None,
                   data: dict | None = None, *, idempotent: bool = False, **fields: Any) -> dict:
        """Move a run to `to` only if its current status is in `allowed_from` (None = any non-terminal).

        Strict by default. `idempotent=True` additionally accepts current == to; graph nodes that may be
        replayed after a crash use it for their own terminal write, nothing else does.
        """
        with self.tx() as c:
            row = c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("run_not_found", f"no run with id {run_id!r}")
            current = row["status"]
            if idempotent and current == to:
                return self.get_run(run_id)
            ok = (current not in TERMINAL) if allowed_from is None else (current in allowed_from)
            if not ok:
                raise Conflict("invalid_transition", f"run is {current!r}; cannot move to {to!r}", status=current)
            self._set(c, run_id, status=to, **fields)
            if event:
                self._event(c, run_id, event, {"from": current, "to": to, **(data or {})})
        return self.get_run(run_id)

    def finish(self, run_id: str, to: str, *, event: str, data: dict | None = None, result: dict | None = None,
               cancel_result: dict | None = None, **fields: Any) -> str:
        """Terminal/failed write that honours an accepted cancel atomically.

        If a cancel was accepted (cancel_requested) before this transaction, the run ends `cancelled`
        instead of `to`. Because request_cancel and finish both take the write lock, a cancel is either
        accepted before the run finishes (and wins) or refused because the run is already terminal.
        Returns the status actually written.
        """
        with self.tx() as c:
            row = c.execute("SELECT status, cancel_requested FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("run_not_found", f"no run with id {run_id!r}")
            current = row["status"]
            if current in TERMINAL:
                if current == to:
                    return current  # replayed terminal node
                raise Conflict("invalid_transition", f"run is already {current!r}", status=current)
            committed = self._committed_action_ids(c, run_id)
            if row["cancel_requested"] and committed:
                # cannot happen through request_cancel (it refuses atomically); defensive: the ledger fact wins
                self._set(c, run_id, cancel_requested=False)
                self._event(c, run_id, "cancel_not_applied", {"reason": "simulated action already committed",
                                                              "action_ids": committed})
            elif row["cancel_requested"]:
                self._set(c, run_id, status="cancelled", retryable=False,
                          result=cancel_result or {"kind": "cancelled", "summary": "Cancelled before it finished. "
                                                   "No action executed."})
                self._event(c, run_id, "run_cancelled", {"from": current, "at": f"instead of {to}"})
                return "cancelled"
            if result is not None:
                fields["result"] = result
            self._set(c, run_id, status=to, **fields)
            self._event(c, run_id, event, {"from": current, "to": to, **(data or {})})
            return to

    def settle_gate(self, run_id: str, pending_ref: dict) -> tuple[str, dict | None]:
        """Called once the graph is paused at interrupt(). Atomically either expose the pause as
        `awaiting_approval`, or, if a cancel was accepted while the run was still `running`, record a
        system cancel decision on the pending proposal so the graph resumes into its cancel branch.
        Returns ("await", None) or ("cancel", decision_row)."""
        with self.tx() as c:
            row = c.execute("SELECT status, cancel_requested, requester FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row["status"] not in ("running", "resuming", "interrupted"):
                raise Conflict("invalid_transition", f"run is {row['status']!r}; cannot settle gate",
                               status=row["status"])
            if row["cancel_requested"] and self._committed_action_ids(c, run_id):
                raise Conflict("action_already_committed", "cannot settle a gate for a run with a committed action")
            if not row["cancel_requested"]:
                self._set(c, run_id, status="awaiting_approval", error_code=None, error_message=None)
                self._event(c, run_id, "awaiting_approval", {"from": row["status"], "to": "awaiting_approval",
                                                             **pending_ref})
                return "await", None
            prop = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (pending_ref["proposal_id"],)).fetchone()
            decision_id = new_id("dec")
            idem = f"system-cancel:{prop['proposal_id']}:{prop['revision']}"
            c.execute(
                "INSERT OR IGNORE INTO decisions(decision_id, run_id, proposal_id, revision, proposal_sha256, decision,"
                " actor, role, comment, changes_json, idempotency_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, run_id, prop["proposal_id"], prop["revision"], prop["sha256"], "cancel", "system",
                 "system", "cancel was accepted before the proposal reached the approval gate", None, idem,
                 time.time()))
            c.execute("UPDATE proposals SET status='cancelled' WHERE proposal_id=?", (prop["proposal_id"],))
            self._set(c, run_id, status="resuming")
            self._event(c, run_id, "gate_cancelled_before_approval", {"proposal_id": prop["proposal_id"],
                                                                      "revision": prop["revision"]})
            dec = c.execute("SELECT * FROM decisions WHERE idempotency_key=?", (idem,)).fetchone()
            d = dict(dec)
            d["changes"] = None
            return "cancel", d

    def claim_recovery(self, run_id: str, actor: str, max_recoveries: int) -> dict:
        """Atomically claim one recovery: check eligibility and bump recover_count in one write
        transaction, so concurrent Recover calls cannot both succeed."""
        with self.tx() as c:
            row = c.execute("SELECT status, retryable, recover_count FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("run_not_found", f"no run with id {run_id!r}")
            if row["status"] not in ("failed", "interrupted"):
                raise Conflict("not_recoverable", f"run is {row['status']!r}; only failed or interrupted runs recover",
                               status=row["status"])
            if row["status"] == "failed" and not row["retryable"]:
                raise Conflict("not_retryable", "run failed with a non-retryable error or used all recoveries")
            if row["recover_count"] >= max_recoveries:
                raise Conflict("recovery_limit", f"run already used {row['recover_count']} recoveries")
            attempt = row["recover_count"] + 1
            self._set(c, run_id, status="running", recover_count=attempt, error_code=None, error_message=None,
                      retryable=False)
            self._event(c, run_id, "recover_started", {"from": row["status"], "to": "running", "actor": actor,
                                                       "attempt": attempt})
        return self.get_run(run_id)

    def set_fields(self, run_id: str, **fields: Any) -> None:
        with self.tx() as c:
            self._set(c, run_id, **fields)

    @staticmethod
    def _committed_action_ids(c: sqlite3.Connection, run_id: str) -> list[str]:
        return [r["action_id"] for r in c.execute("SELECT action_id FROM sim_actions WHERE run_id=?", (run_id,))]

    @staticmethod
    def _set(c: sqlite3.Connection, run_id: str, **fields: Any) -> None:
        # Invariant (R5-01f): a run with a committed simulated action can never be recorded as cancelled or
        # rejected. Enforced at the lowest write level, inside the caller's transaction, for every path.
        if fields.get("status") in ("cancelled", "rejected") and Store._committed_action_ids(c, run_id):
            raise Conflict("action_already_committed", "a simulated action is already committed for this run; "
                           "it cannot be recorded as cancelled or rejected. Recover to reconcile it.",
                           action_ids=Store._committed_action_ids(c, run_id))
        cols = {}
        for k, v in fields.items():
            if k in ("plan", "result", "demo_fault"):
                cols[f"{k}_json"] = canonical_json(v) if v is not None else None
            elif isinstance(v, bool):
                cols[k] = int(v)
            else:
                cols[k] = v
        cols["updated_at"] = time.time()
        assigns = ", ".join(f"{k}=?" for k in cols)
        c.execute(f"UPDATE runs SET {assigns} WHERE run_id=?", (*cols.values(), run_id))

    def add_event(self, run_id: str, kind: str, data: dict | None = None) -> None:
        with self.tx() as c:
            self._event(c, run_id, kind, data)

    def events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]:
        rows = self._q("SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                       (run_id, after_seq, limit))
        return [{"seq": r["seq"], "ts": r["ts"], "kind": r["kind"], "data": json.loads(r["data_json"])} for r in rows]

    # ------------------------------------------------------------------ steps
    def upsert_step(self, run_id: str, step_id: str, agent: str, status: str, *, attempts: int = 0,
                    output: Any = None, error_code: str | None = None, error_message: str | None = None,
                    duration_ms: int | None = None) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO run_steps(run_id, step_id, agent, status, attempts, output_json, error_code, error_message,"
                " duration_ms) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id, step_id) DO UPDATE SET"
                " status=excluded.status, attempts=excluded.attempts, output_json=excluded.output_json,"
                " error_code=excluded.error_code, error_message=excluded.error_message, duration_ms=excluded.duration_ms",
                (run_id, step_id, agent, status, attempts, canonical_json(output) if output is not None else None,
                 error_code, error_message, duration_ms))

    def steps(self, run_id: str) -> list[dict]:
        out = []
        for r in self._q("SELECT * FROM run_steps WHERE run_id=? ORDER BY step_id", (run_id,)):
            d = dict(r)
            d["output"] = json.loads(d.pop("output_json")) if d["output_json"] else None
            out.append(d)
        return out

    def bump_fault_counter(self, run_id: str, agent: str) -> int:
        with self.tx() as c:
            c.execute("INSERT INTO fault_counters(run_id, agent, count) VALUES (?,?,1) ON CONFLICT(run_id, agent)"
                      " DO UPDATE SET count=count+1", (run_id, agent))
            return c.execute("SELECT count FROM fault_counters WHERE run_id=? AND agent=?",
                             (run_id, agent)).fetchone()["count"]

    # ------------------------------------------------------------------ proposals
    def upsert_proposal(self, run_id: str, revision: int, payload: dict) -> dict:
        """Idempotent: the same (run_id, revision) always maps to one proposal row.

        Called from a graph node that may be replayed after a crash, so it must not create
        duplicates. The hash covers run_id and revision, so it cannot match another run's proposal.
        """
        body = {"run_id": run_id, "revision": revision, **payload}
        digest = sha256_hex(body)
        with self.tx() as c:
            row = c.execute("SELECT * FROM proposals WHERE run_id=? AND revision=?", (run_id, revision)).fetchone()
            if row is None:
                pid = new_id("prop")
                c.execute("UPDATE proposals SET status='superseded' WHERE run_id=? AND status='pending'", (run_id,))
                c.execute("INSERT INTO proposals(proposal_id, run_id, revision, sha256, payload_json, status, created_at)"
                          " VALUES (?,?,?,?,?,?,?)", (pid, run_id, revision, digest, canonical_json(body), "pending",
                                                      time.time()))
                self._event(c, run_id, "proposal_created", {"proposal_id": pid, "revision": revision,
                                                            "sha256": digest})
        return self.proposal_by_revision(run_id, revision)

    @staticmethod
    def _proposal_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        return d

    def proposal_by_revision(self, run_id: str, revision: int) -> dict | None:
        rows = self._q("SELECT * FROM proposals WHERE run_id=? AND revision=?", (run_id, revision))
        return self._proposal_dict(rows[0]) if rows else None

    def get_proposal(self, proposal_id: str) -> dict | None:
        rows = self._q("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,))
        return self._proposal_dict(rows[0]) if rows else None

    def proposals(self, run_id: str) -> list[dict]:
        return [self._proposal_dict(r) for r in
                self._q("SELECT * FROM proposals WHERE run_id=? ORDER BY revision", (run_id,))]

    def latest_proposal(self, run_id: str) -> dict | None:
        rows = self._q("SELECT * FROM proposals WHERE run_id=? ORDER BY revision DESC LIMIT 1", (run_id,))
        return self._proposal_dict(rows[0]) if rows else None

    # ------------------------------------------------------------------ decisions
    def record_decision(self, run_id: str, *, proposal_id: str, revision: int, proposal_sha256: str,
                        decision: str, actor: str, role: str, comment: str, changes: dict | None,
                        idempotency_key: str, hard_budget_cap: float) -> tuple[dict, bool]:
        """Validate and record one human decision atomically. Returns (response, replayed).

        All checks and the status change happen in one write transaction, so for a given run at most
        one decision can take it out of `awaiting_approval`; the loser sees a 409.
        """
        request = {"run_id": run_id, "proposal_id": proposal_id, "revision": revision,
                   "proposal_sha256": proposal_sha256, "decision": decision, "actor": actor, "role": role,
                   "comment": comment, "changes": changes}
        request_hash = sha256_hex(request)
        with self.tx() as c:
            prior = c.execute("SELECT * FROM idempotency WHERE key=?", (idempotency_key,)).fetchone()
            if prior is not None:
                if prior["request_hash"] == request_hash:
                    return json.loads(prior["response_json"]), True
                raise Conflict("idempotency_key_reused",
                               "this idempotency key was already used with a different request")
            if decision not in DECISIONS:
                raise Unprocessable("invalid_decision", f"decision must be one of {sorted(DECISIONS)}")
            run = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise NotFound("run_not_found", f"no run with id {run_id!r}")
            if decision in APPROVER_DECISIONS and role != "approver":
                raise Forbidden("role_not_permitted", f"role {role!r} cannot {decision}; approver role required")
            if decision == "cancel" and role not in ("approver", "requester"):
                raise Forbidden("role_not_permitted", f"role {role!r} cannot cancel")
            if decision in APPROVER_DECISIONS and actor == run["requester"]:
                raise Forbidden("separation_of_duties", "the requester of a run cannot approve, reject or revise it")
            if run["status"] != "awaiting_approval":
                raise Conflict("run_not_awaiting_approval", f"run is {run['status']!r}", status=run["status"])
            if decision in ("cancel", "reject") and self._committed_action_ids(c, run_id):
                raise Conflict("action_already_committed", "a simulated action is already committed for this run")
            prop = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if prop is None:
                raise NotFound("proposal_not_found", f"no proposal with id {proposal_id!r}")
            if prop["run_id"] != run_id:
                raise Conflict("proposal_run_mismatch", "proposal belongs to a different run")
            current = c.execute("SELECT * FROM proposals WHERE run_id=? AND status='pending' ORDER BY revision DESC"
                                " LIMIT 1", (run_id,)).fetchone()
            if current is None or prop["proposal_id"] != current["proposal_id"] or revision != current["revision"]:
                raise Conflict("stale_revision", "decision does not target the current pending revision",
                               current_revision=current["revision"] if current else None,
                               current_proposal_id=current["proposal_id"] if current else None)
            if proposal_sha256 != current["sha256"]:
                raise Conflict("proposal_hash_mismatch", "proposal content hash does not match the pending revision")
            payload = json.loads(current["payload_json"])
            if decision == "approve" and not payload.get("policy", {}).get("approvable", False):
                raise Unprocessable("proposal_not_approvable", "proposal has policy blockers; reject or revise it",
                                    blockers=payload.get("policy", {}).get("blockers", []))
            if decision == "revise":
                self._validate_changes(changes, payload, hard_budget_cap)
            decision_id = new_id("dec")
            now = time.time()
            c.execute(
                "INSERT INTO decisions(decision_id, run_id, proposal_id, revision, proposal_sha256, decision, actor, role,"
                " comment, changes_json, idempotency_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, run_id, proposal_id, revision, proposal_sha256, decision, actor, role, comment,
                 canonical_json(changes) if changes else None, idempotency_key, now))
            new_prop_status = {"approve": "approved", "reject": "rejected", "revise": "revision_requested",
                               "cancel": "cancelled"}[decision]
            c.execute("UPDATE proposals SET status=? WHERE proposal_id=?", (new_prop_status, proposal_id))
            self._set(c, run_id, status="resuming")
            self._event(c, run_id, "decision_recorded", {"decision_id": decision_id, "decision": decision,
                                                         "actor": actor, "role": role, "proposal_id": proposal_id,
                                                         "revision": revision})
            response = {"decision_id": decision_id, "run_id": run_id, "proposal_id": proposal_id,
                        "revision": revision, "decision": decision}
            c.execute("INSERT INTO idempotency(key, scope, request_hash, response_json, created_at) VALUES (?,?,?,?,?)",
                      (idempotency_key, f"decision:{run_id}", request_hash, canonical_json(response), now))
            return response, False

    @staticmethod
    def _validate_changes(changes: dict | None, payload: dict, cap: float) -> None:
        if not changes:
            raise Unprocessable("invalid_changes", "revise requires at least one change")
        allowed = {"budget_total", "remove_creative_ids"}
        unknown = set(changes) - allowed
        if unknown:
            raise Unprocessable("invalid_changes", f"unsupported change fields: {sorted(unknown)}")
        if "budget_total" in changes:
            b = changes["budget_total"]
            if not isinstance(b, (int, float)) or isinstance(b, bool) or not (0 < b <= cap):
                raise Unprocessable("invalid_changes", f"budget_total must be a number in (0, {cap:,.0f}]")
        if "remove_creative_ids" in changes:
            ids = changes["remove_creative_ids"]
            existing = {cr["creative_id"] for cr in payload.get("creatives", [])}
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or not set(ids) <= existing:
                raise Unprocessable("invalid_changes", "remove_creative_ids must list creatives in this proposal")
            if set(ids) >= existing:
                raise Unprocessable("invalid_changes", "a revision must keep at least one creative")

    def decisions(self, run_id: str) -> list[dict]:
        out = []
        for r in self._q("SELECT * FROM decisions WHERE run_id=? ORDER BY created_at", (run_id,)):
            d = dict(r)
            d["changes"] = json.loads(d.pop("changes_json")) if d["changes_json"] else None
            d["applied"] = bool(d["applied"])
            out.append(d)
        return out

    def unapplied_decision(self, run_id: str) -> dict | None:
        for d in reversed(self.decisions(run_id)):
            if not d["applied"]:
                return d
        return None

    def mark_decision_applied(self, decision_id: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE decisions SET applied=1 WHERE decision_id=?", (decision_id,))

    def request_cancel(self, run_id: str, actor: str, role: str) -> tuple[dict, str]:
        """Cancel outside the approval gate. Returns (run, outcome)."""
        if role not in ("approver", "requester"):
            raise Forbidden("role_not_permitted", f"role {role!r} cannot cancel")
        with self.tx() as c:
            row = c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("run_not_found", f"no run with id {run_id!r}")
            status = row["status"]
            committed = self._committed_action_ids(c, run_id)
            if status == "cancelled":
                outcome = "already_cancelled"
            elif status in ("completed", "rejected"):
                raise Conflict("run_terminal", f"run is already {status!r}", status=status)
            elif committed:
                # every acceptance path (queued, running incl. a claimed recovery, failed, interrupted, gate)
                raise Conflict("action_already_committed",
                               "a simulated action was already committed for this run; it cannot be cancelled "
                               "as if nothing happened. Recover to reconcile it.", action_ids=committed)
            elif status in ("failed", "interrupted"):
                open_props = c.execute("SELECT proposal_id, status FROM proposals WHERE run_id=? AND status IN "
                                       "('pending','approved')", (run_id,)).fetchall()
                c.execute("UPDATE proposals SET status='cancelled' WHERE run_id=? AND status IN ('pending','approved')",
                          (run_id,))
                self._set(c, run_id, status="cancelled", retryable=False,
                          result={"kind": "cancelled", "summary": "Cancelled. No action executed."})
                self._event(c, run_id, "run_cancelled", {
                    "actor": actor, "role": role, "from": status,
                    "voided_proposals": [dict(r) for r in open_props],
                    "note": "any recorded approve for these proposals was never executed and is now void"})
                outcome = "cancelled"
            elif status in ("queued", "running"):
                self._set(c, run_id, cancel_requested=True)
                self._event(c, run_id, "cancel_requested", {"actor": actor, "role": role})
                outcome = "cancel_requested"
            elif status == "awaiting_approval":
                outcome = "gate"  # handled through record_decision so the graph resumes into its cancel branch
            else:  # resuming: a decision is already being applied
                raise Conflict("run_busy", f"run is {status!r}; try again when it settles", status=status)
        return self.get_run(run_id), outcome

    # ------------------------------------------------------------------ simulated actions
    def sim_action_by_key(self, key: str) -> dict | None:
        rows = self._q("SELECT * FROM sim_actions WHERE idempotency_key=?", (key,))
        return self._action_dict(rows[0]) if rows else None

    @staticmethod
    def _action_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        return d

    def actions(self, run_id: str | None = None) -> list[dict]:
        if run_id is None:
            rows = self._q("SELECT * FROM sim_actions ORDER BY created_at")
        else:
            rows = self._q("SELECT * FROM sim_actions WHERE run_id=? ORDER BY created_at", (run_id,))
        return [self._action_dict(r) for r in rows]

    # ------------------------------------------------------------------ aggregates
    def stats(self) -> dict:
        by_status = {r["status"]: r["n"] for r in self._q("SELECT status, COUNT(*) n FROM runs GROUP BY status")}
        act = self._q("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM sim_actions")[0]
        decisions = {r["decision"]: r["n"] for r in
                     self._q("SELECT decision, COUNT(*) n FROM decisions GROUP BY decision")}
        return {
            "runs_total": sum(by_status.values()),
            "runs_by_status": by_status,
            "pending_approvals": by_status.get("awaiting_approval", 0),
            "decisions_by_type": decisions,
            "simulated_actions": act["n"],
            "simulated_amount_committed": act["s"],
        }
