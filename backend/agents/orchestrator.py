"""LangGraph workflow with a durable approval gate, plus the runner that drives it.

Graph (thread_id = runs.thread_id, checkpointer = SqliteSaver, durability="sync"):

    plan ─┬─ question ─► answer ─► END
          └─ workflow ─► step ⟲ (one validated plan step per super-step)
                             ├─ no gated action ─► finalize_deliverable ─► END
                             └─ gated action ───► build_proposal ─► approval_gate (interrupt)
                                                        ▲                 ├─ approve ─► execute_action ─► finalize ─► END
                                                        └──── revise ─────┤─ reject  ─► rejected ─► END
                                                                          └─ cancel  ─► cancelled ─► END

Durability rules this file follows:
  * State holds only JSON data. The runner, store, provider and any sockets live outside it and are
    reached through closures.
  * interrupt() re-runs its node from the start on resume, so approval_gate does nothing before the
    interrupt() call. build_proposal runs in an earlier super-step, and its only side effect
    (upsert_proposal) is idempotent per (run_id, revision).
  * A failing node raises. LangGraph does not checkpoint that node, so Recover resumes from the last
    good checkpoint and repeats only the failed step (earlier steps are not re-run).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import traceback
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.agents import REGISTRY
from backend.config import Settings
from backend.contracts import Plan, PlanStep, _ancestors, topological_order
from backend.errors import BadRequest, Conflict, Forbidden, NotFound, TooLarge, TooManyRequests
from backend.grounding import answer_question
from backend.policy import GATED_WORKFLOWS, build_proposal_payload, check_role
from backend.prompts.templates import PLANNER_SYSTEM
from backend.providers import FaultInjectingProvider, Provider, StepFailed, build_provider, invoke_structured, redact
from backend.simulator import Simulator, demo_crash_hook
from backend.store import TERMINAL, Store

log = logging.getLogger("adops.runner")


class RunCancelled(Exception):
    pass


class RunState(TypedDict, total=False):
    run_id: str
    plan: dict
    order: list[str]
    done: list[str]
    outputs: dict[str, dict]
    answer: dict
    revision: int
    proposal: dict
    changes: list[dict]
    decision: Optional[dict]
    action: dict


class WorkflowRunner:
    def __init__(self, settings: Settings, *, provider: Provider | None = None, crash_hook=None):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(settings.store_path)
        self.provider = provider or build_provider(settings)
        if crash_hook is None and settings.is_demo and settings.demo_crash_point:
            crash_hook = demo_crash_hook(settings.demo_crash_point, settings.data_dir / ".crash_drill_fired")
        self.simulator = Simulator(self.store, crash_hook=crash_hook)
        self._cp_conn = sqlite3.connect(str(settings.checkpoint_path), check_same_thread=False)
        self.checkpointer = SqliteSaver(self._cp_conn)
        self.checkpointer.setup()
        self.graph = self._build_graph().compile(checkpointer=self.checkpointer)
        self._executor = ThreadPoolExecutor(max_workers=settings.worker_threads, thread_name_prefix="run")
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()
        self._jobs: dict[str, Future] = {}
        self._active = 0
        self._active_lock = threading.Lock()

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._cp_conn.close()
        self.store.close()

    # ------------------------------------------------------------------ helpers
    def _config(self, run: dict) -> dict:
        return {"configurable": {"thread_id": run["thread_id"]}}

    def _lock(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[run_id]

    def _provider_for(self, run: dict) -> Provider:
        fault = run.get("demo_fault")
        if fault and self.provider.mode == "demo":
            return FaultInjectingProvider(self.provider, fault, lambda role: self.store.bump_fault_counter(
                run["run_id"], role), self.settings.provider_timeout_s)
        return self.provider

    def _check_cancel(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run and run["cancel_requested"]:
            raise RunCancelled()

    def _attempt_logger(self, run_id: str, role: str):
        def on_attempt(attempt: int, outcome: str, message: str) -> None:
            self.store.add_event(run_id, "provider_attempt", {"role": role, "attempt": attempt, "outcome": outcome,
                                                              "message": message})
        return on_attempt

    # ------------------------------------------------------------------ graph
    def _build_graph(self) -> StateGraph:
        g = StateGraph(RunState)
        g.add_node("plan", self._n_plan)
        g.add_node("answer", self._n_answer)
        g.add_node("step", self._n_step)
        g.add_node("finalize_deliverable", self._n_finalize_deliverable)
        g.add_node("build_proposal", self._n_build_proposal)
        g.add_node("approval_gate", self._n_gate)
        g.add_node("execute_action", self._n_execute)
        g.add_node("finalize", self._n_finalize)
        g.add_node("rejected", self._n_rejected)
        g.add_node("cancelled", self._n_cancelled)
        g.add_edge(START, "plan")
        g.add_conditional_edges("plan", lambda s: "answer" if s["plan"]["route"] == "question" else "step",
                                ["answer", "step"])
        g.add_edge("answer", END)
        g.add_conditional_edges("step", self._after_step, ["step", "build_proposal", "finalize_deliverable"])
        g.add_edge("finalize_deliverable", END)
        g.add_edge("build_proposal", "approval_gate")
        g.add_conditional_edges("approval_gate", self._after_gate,
                                ["execute_action", "rejected", "cancelled", "build_proposal"])
        g.add_edge("execute_action", "finalize")
        g.add_edge("finalize", END)
        g.add_edge("rejected", END)
        g.add_edge("cancelled", END)
        return g

    def _n_plan(self, state: RunState) -> dict:
        run_id = state["run_id"]
        self._check_cancel(run_id)
        run = self.store.get_run(run_id)
        self.store.add_event(run_id, "node_started", {"node": "plan"})
        try:
            plan, attempts = invoke_structured(
                self._provider_for(run), "planner", PLANNER_SYSTEM, {"request": run["request_text"]}, Plan,
                timeout_s=self.settings.provider_timeout_s, max_attempts=self.settings.provider_max_attempts,
                on_attempt=self._attempt_logger(run_id, "planner"))
        except StepFailed as e:
            e.step_id, e.agent = "plan", "planner"
            raise
        plan_d = plan.model_dump(mode="json")
        order = topological_order(plan.steps) if plan.route == "workflow" else []
        self.store.set_fields(run_id, route=plan.route, workflow_type=plan.workflow_type, plan=plan_d)
        for s in plan.steps:
            self.store.upsert_step(run_id, s.id, s.agent, "pending")
        self.store.add_event(run_id, "plan_validated", {"route": plan.route, "workflow_type": plan.workflow_type,
                                                        "order": order, "attempts": attempts,
                                                        "gated": plan.workflow_type in GATED_WORKFLOWS})
        return {"plan": plan_d, "order": order, "done": [], "outputs": {}, "changes": [], "revision": 0}

    def _n_answer(self, state: RunState) -> dict:
        run_id = state["run_id"]
        run = self.store.get_run(run_id)
        ans = answer_question(run["request_text"])
        # finish() ends the run cancelled instead if a cancel was accepted while planning (R5-01)
        self.store.finish(run_id, "completed", event="run_completed", data={"kind": "answer", "outcome": ans["outcome"]},
                          result={"kind": "answer", "answer": ans})
        return {"answer": ans}

    def _n_step(self, state: RunState) -> dict:
        run_id = state["run_id"]
        self._check_cancel(run_id)
        run = self.store.get_run(run_id)
        steps = [PlanStep(**s) for s in state["plan"]["steps"]]
        by_id = {s.id: s for s in steps}
        done, outputs = list(state.get("done", [])), dict(state.get("outputs", {}))
        step = by_id[next(i for i in state["order"] if i not in done)]
        spec = REGISTRY[step.agent]
        # context: outputs of this step's ancestors only (all of them completed; failures raise)
        context = {by_id[a].agent: outputs[a] for a in sorted(_ancestors(step.id, steps))}
        if spec.extra_context:
            context.update(spec.extra_context(context))
        payload = {"request": run["request_text"], "task": step.task, "context": context}
        self.store.upsert_step(run_id, step.id, step.agent, "running")
        self.store.add_event(run_id, "step_started", {"step_id": step.id, "agent": step.agent})
        check = (lambda o: spec.semantic_check(o, context)) if spec.semantic_check else None
        try:
            out, attempts = invoke_structured(
                self._provider_for(run), step.agent, spec.system_prompt, payload, spec.contract,
                timeout_s=self.settings.provider_timeout_s, max_attempts=self.settings.provider_max_attempts,
                on_attempt=self._attempt_logger(run_id, step.agent), semantic_check=check)
        except StepFailed as e:
            e.step_id, e.agent = step.id, step.agent
            self.store.upsert_step(run_id, step.id, step.agent, "failed", attempts=e.attempts, error_code=e.code,
                                   error_message=e.message)
            self.store.add_event(run_id, "step_failed", {"step_id": step.id, "agent": step.agent, "code": e.code,
                                                         "message": e.message, "attempts": e.attempts})
            raise
        out_d = out.model_dump(mode="json")
        self.store.upsert_step(run_id, step.id, step.agent, "completed", attempts=attempts, output=out_d)
        self.store.add_event(run_id, "step_completed", {"step_id": step.id, "agent": step.agent, "attempts": attempts})
        outputs[step.id] = out_d
        return {"done": done + [step.id], "outputs": outputs}

    def _after_step(self, state: RunState) -> str:
        if len(state["done"]) < len(state["order"]):
            return "step"
        return "build_proposal" if state["plan"]["workflow_type"] in GATED_WORKFLOWS else "finalize_deliverable"

    def _outputs_by_agent(self, state: RunState) -> dict[str, dict]:
        agent_of = {s["id"]: s["agent"] for s in state["plan"]["steps"]}
        return {agent_of[k]: v for k, v in state.get("outputs", {}).items()}

    def _n_finalize_deliverable(self, state: RunState) -> dict:
        run_id = state["run_id"]
        self.store.finish(run_id, "completed", event="run_completed", data={"kind": "deliverable"},
                          result={"kind": "deliverable", "outputs": self._outputs_by_agent(state),
                                  "note": "No action was proposed, so nothing needed approval."})
        return {}

    def _n_build_proposal(self, state: RunState) -> dict:
        run_id = state["run_id"]
        self._check_cancel(run_id)
        revision = state.get("revision", 0) + 1
        payload = build_proposal_payload(state["plan"]["workflow_type"], self._outputs_by_agent(state),
                                         state.get("changes", []),
                                         high_spend_threshold=self.settings.high_spend_threshold,
                                         hard_budget_cap=self.settings.hard_budget_cap)
        prop = self.store.upsert_proposal(run_id, revision, payload)  # idempotent per (run_id, revision)
        ref = {"proposal_id": prop["proposal_id"], "revision": revision, "sha256": prop["sha256"]}
        return {"revision": revision, "proposal": ref, "decision": None}

    def _n_gate(self, state: RunState) -> dict:
        ref = state["proposal"]
        # Nothing before interrupt(): this node re-runs from the top when resumed.
        decision = interrupt({"type": "approval_required", **ref})
        if (not isinstance(decision, dict) or decision.get("proposal_id") != ref["proposal_id"]
                or decision.get("revision") != ref["revision"] or decision.get("proposal_sha256") != ref["sha256"]):
            raise StepFailed("decision_mismatch", "resume value does not match the pending proposal", retryable=False)
        update: dict[str, Any] = {"decision": decision}
        if decision["decision"] == "revise":
            update["changes"] = list(state.get("changes", [])) + [decision.get("changes") or {}]
        return update

    @staticmethod
    def _after_gate(state: RunState) -> str:
        return {"approve": "execute_action", "reject": "rejected", "cancel": "cancelled",
                "revise": "build_proposal"}[state["decision"]["decision"]]

    def _n_execute(self, state: RunState) -> dict:
        ref = state["proposal"]
        action, replayed = self.simulator.execute(state["run_id"], ref["proposal_id"], ref["revision"], ref["sha256"])
        return {"action": {"action_id": action["action_id"], "replayed": replayed}}

    def _n_finalize(self, state: RunState) -> dict:
        run_id = state["run_id"]
        action = next(a for a in self.store.actions(run_id) if a["action_id"] == state["action"]["action_id"])
        p = action["payload"]
        summary = (f"Simulated {p['action_type']} committed for {p['campaign_name']}: {p['amount']:,.2f} {p['currency']}. "
                   f"Ledger action {action['action_id']}. {p['integration']}")
        # an action is committed: completion must win (cancel is refused while a decision is being applied)
        self.store.transition(run_id, {"resuming", "running"}, "completed", event="run_completed",
                              data={"kind": "action"}, idempotent=True, result={"kind": "action", "summary": summary, "action_id": action["action_id"],
                                      "replay_detected": state["action"]["replayed"]})
        return {}

    def _n_rejected(self, state: RunState) -> dict:
        self.store.transition(state["run_id"], {"resuming", "running"}, "rejected", event="run_rejected", idempotent=True,
                              data={"proposal": state["proposal"]},
                              result={"kind": "rejected", "summary": "Rejected by the approver. No action executed."})
        return {}

    def _n_cancelled(self, state: RunState) -> dict:
        self.store.transition(state["run_id"], {"resuming", "running"}, "cancelled", event="run_cancelled",
                              idempotent=True, data={"proposal": state["proposal"]},
                              result={"kind": "cancelled", "summary": "Cancelled at the approval gate. No action executed."})
        return {}

    # ------------------------------------------------------------------ driving the graph
    def _drive(self, run_id: str, graph_input: Any) -> None:
        with self._lock(run_id):
            self._drive_locked(run_id, graph_input)

    def _drive_locked(self, run_id: str, graph_input: Any) -> None:
        run = self.store.get_run(run_id)
        config = self._config(run)
        try:
            self.graph.invoke(graph_input, config, durability="sync")
        except StepFailed as e:
            retryable = e.retryable and run["recover_count"] < self.settings.max_recoveries
            self.store.finish(run_id, "failed", event="run_failed",
                              data={"code": e.code, "message": e.message, "step_id": e.step_id, "agent": e.agent,
                                    "retryable": retryable},
                              error_code=e.code, error_message=f"{e.step_id or ''} {e.agent or ''}: {e.message}".strip(),
                              retryable=retryable)
            return
        except RunCancelled:
            self.store.transition(run_id, None, "cancelled", event="run_cancelled", idempotent=True,
                                  data={"at": "between steps (cooperative cancel)"},
                                  result={"kind": "cancelled", "summary": "Cancelled before any action."})
            return
        except Exception as e:  # noqa: BLE001
            log.error("run %s internal error: %s", run_id, redact(traceback.format_exc(), self.provider.secrets(),
                                                                      limit=4000))
            self.store.finish(run_id, "failed", event="run_failed",
                              data={"code": "internal_error", "message": type(e).__name__},
                              error_code="internal_error", error_message=type(e).__name__, retryable=True)
            return
        snap = self.graph.get_state(config)
        pending = [i.value for t in snap.tasks for i in t.interrupts]
        if pending:
            self._settle_gate(run_id, pending[0])

    def _settle_gate(self, run_id: str, ref: dict) -> None:
        """The graph is paused at the gate. Expose the pause, or honour a cancel accepted meanwhile
        by resuming into the cancel branch (R5-01). Caller holds the run lock."""
        outcome, dec = self.store.settle_gate(run_id, ref)
        if outcome == "cancel":
            self._drive_locked(run_id, Command(resume=self._decision_payload(dec)))
            self.store.mark_decision_applied(dec["decision_id"])

    def _reserve_slot(self) -> None:
        with self._active_lock:
            if self._active >= self.settings.max_active_runs:
                raise TooManyRequests("queue_full", f"{self._active} runs are queued or running; "
                                      f"limit is {self.settings.max_active_runs}. Try again shortly.")
            self._active += 1

    def _release_slot(self) -> None:
        with self._active_lock:
            self._active -= 1

    def _submit(self, run_id: str, fn, *args) -> None:
        def job():
            try:
                fn(*args)
            finally:
                self._release_slot()
        self._jobs[run_id] = self._executor.submit(job)

    def wait(self, run_id: str, timeout: float = 30) -> dict:
        fut = self._jobs.get(run_id)
        if fut is not None:
            fut.result(timeout=timeout)
        return self.store.get_run(run_id)

    # ------------------------------------------------------------------ public operations
    def create_run(self, request: str, *, actor: str, role: str, demo_fault: dict | None = None) -> dict:
        if not check_role(role, "create_run"):
            raise Forbidden("role_not_permitted", f"role {role!r} cannot create runs; requester role required")
        text = request.strip()
        if not text:
            raise BadRequest("empty_request", "request must not be empty")
        if len(text) > self.settings.max_request_chars:
            raise TooLarge("request_too_long", f"request is {len(text)} characters; limit is "
                           f"{self.settings.max_request_chars}")
        if demo_fault and self.provider.mode != "demo":
            raise BadRequest("fault_injection_unavailable", "demo_fault is only accepted in demo mode")
        self._reserve_slot()
        try:
            run = self.store.create_run(requester=actor, request_text=text, provider_mode=self.provider.mode,
                                        demo_fault=demo_fault)
        except BaseException:
            self._release_slot()
            raise
        self._submit(run["run_id"], self._start, run["run_id"])
        return run

    def _start(self, run_id: str) -> None:
        try:
            self.store.transition(run_id, {"queued"}, "running", event="run_started")
        except Conflict:
            return  # cancelled while queued
        run = self.store.get_run(run_id)
        if run["cancel_requested"]:
            self.store.transition(run_id, None, "cancelled", event="run_cancelled", data={"at": "queued"},
                                  result={"kind": "cancelled", "summary": "Cancelled before it started."})
            return
        self._drive(run_id, {"run_id": run_id})

    def decide(self, run_id: str, *, proposal_id: str, revision: int, proposal_sha256: str, decision: str,
               comment: str, changes: dict | None, idempotency_key: str, actor: str, role: str) -> dict:
        if len(comment) > self.settings.max_comment_chars:
            raise TooLarge("comment_too_long", f"comment limit is {self.settings.max_comment_chars} characters")
        if decision != "revise" and changes:
            raise BadRequest("unexpected_changes", "changes are only accepted with decision 'revise'")
        resp, replayed = self.store.record_decision(
            run_id, proposal_id=proposal_id, revision=revision, proposal_sha256=proposal_sha256, decision=decision,
            actor=actor, role=role, comment=comment, changes=changes, idempotency_key=idempotency_key,
            hard_budget_cap=self.settings.hard_budget_cap)
        if not replayed:
            self._apply_decision(run_id, resp["decision_id"])
        return {"decision": resp, "replayed": replayed, "run": self.store.get_run(run_id)}

    def _decision_payload(self, dec: dict) -> dict:
        return {"decision_id": dec["decision_id"], "decision": dec["decision"], "proposal_id": dec["proposal_id"],
                "revision": dec["revision"], "proposal_sha256": dec["proposal_sha256"], "changes": dec["changes"],
                "actor": dec["actor"]}

    def _apply_decision(self, run_id: str, decision_id: str) -> None:
        dec = next(d for d in self.store.decisions(run_id) if d["decision_id"] == decision_id)
        self._drive(run_id, Command(resume=self._decision_payload(dec)))
        self.store.mark_decision_applied(decision_id)

    def cancel(self, run_id: str, *, actor: str, role: str, idempotency_key: str, comment: str = "") -> dict:
        if not check_role(role, "cancel"):
            raise Forbidden("role_not_permitted", f"role {role!r} cannot cancel")
        run, outcome = self.store.request_cancel(run_id, actor, role)
        if outcome == "gate":
            prop = self.store.latest_proposal(run_id)
            resp, replayed = self.store.record_decision(
                run_id, proposal_id=prop["proposal_id"], revision=prop["revision"], proposal_sha256=prop["sha256"],
                decision="cancel", actor=actor, role=role, comment=comment, changes=None,
                idempotency_key=idempotency_key, hard_budget_cap=self.settings.hard_budget_cap)
            if not replayed:
                self._apply_decision(run_id, resp["decision_id"])
            outcome = "cancelled"
        elif outcome == "cancel_requested":
            fut = self._jobs.get(run_id)
            if fut is not None:
                try:
                    fut.result(timeout=self.settings.provider_timeout_s * self.settings.provider_max_attempts + 5)
                except Exception:  # noqa: BLE001 - the job records its own outcome
                    pass
        return {"outcome": outcome, "run": self.store.get_run(run_id)}

    def recover(self, run_id: str, *, actor: str, role: str) -> dict:
        if not check_role(role, "recover"):
            raise Forbidden("role_not_permitted", f"role {role!r} cannot recover runs; approver role required")
        self.store.require_run(run_id)
        self._reserve_slot()
        try:
            # eligibility check + recover_count bump in one write transaction (R5-02)
            self.store.claim_recovery(run_id, actor, self.settings.max_recoveries)
        except BaseException:
            self._release_slot()
            raise
        self._submit(run_id, self._recover_job, run_id)
        return {"run": self.store.get_run(run_id)}

    def _recover_job(self, run_id: str) -> None:
        with self._lock(run_id):
            self._recover_locked(run_id)

    def _recover_locked(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        config = self._config(run)
        snap = self.graph.get_state(config)
        pending = [i.value for t in snap.tasks for i in t.interrupts]
        dec = self.store.unapplied_decision(run_id)
        if not snap.values:  # never checkpointed: start from the beginning
            self.store.add_event(run_id, "recover_plan", {"action": "start from the beginning (no checkpoint)"})
            self._drive_locked(run_id, {"run_id": run_id})
            return
        if pending:
            ref = pending[0]
            if dec and dec["proposal_id"] == ref["proposal_id"] and dec["revision"] == ref["revision"]:
                self.store.add_event(run_id, "recover_plan", {"action": "re-apply recorded decision at gate",
                                                              "decision_id": dec["decision_id"]})
                self._drive_locked(run_id, Command(resume=self._decision_payload(dec)))
                self.store.mark_decision_applied(dec["decision_id"])
                return
            if dec:
                self.store.mark_decision_applied(dec["decision_id"])
            self.store.add_event(run_id, "recover_plan", {"action": "graph is paused at the gate; await decision"})
            self._settle_gate(run_id, ref)
            return
        if dec:
            self.store.mark_decision_applied(dec["decision_id"])
        if not snap.next:
            self._reconcile_finished(run_id, snap.values)
            return
        self.store.add_event(run_id, "recover_plan", {"action": "continue from last checkpoint",
                                                      "next_nodes": list(snap.next)})
        self._drive_locked(run_id, None)

    def _reconcile_finished(self, run_id: str, values: dict) -> None:
        """The checkpoint says the graph reached END but the store is not terminal (e.g. a lost terminal
        write). Derive the terminal status from the checkpoint and the ledger, explicitly (R5-02)."""
        actions = self.store.actions(run_id)
        decision = (values.get("decision") or {}).get("decision")
        if actions:
            to, result = "completed", {"kind": "action", "action_id": actions[-1]["action_id"],
                                       "summary": "Reconciled from the ledger: simulated action "
                                                  f"{actions[-1]['action_id']} was already committed."}
        elif decision == "reject":
            to, result = "rejected", {"kind": "rejected", "summary": "Rejected by the approver. No action executed."}
        elif decision == "cancel":
            to, result = "cancelled", {"kind": "cancelled", "summary": "Cancelled. No action executed."}
        elif values.get("answer"):
            to, result = "completed", {"kind": "answer", "answer": values["answer"]}
        elif values.get("plan", {}).get("workflow_type") and values["plan"]["workflow_type"] not in GATED_WORKFLOWS:
            to, result = "completed", {"kind": "deliverable", "outputs": self._outputs_by_agent(values)}
        else:
            to, result = "failed", None
        self.store.add_event(run_id, "recover_plan", {"action": f"graph already finished; reconciled status to {to} "
                                                                "from checkpoint and ledger"})
        if to == "failed":
            self.store.transition(run_id, {"running"}, "failed", event="run_failed",
                                  data={"code": "inconsistent_state"}, error_code="inconsistent_state",
                                  error_message="checkpoint finished but no terminal outcome could be derived",
                                  retryable=False)
        else:
            self.store.transition(run_id, {"running"}, to, event="run_reconciled", result=result)

    def reconcile_on_startup(self) -> list[str]:
        """After a restart, no worker owns runs that were mid-flight. Mark them interrupted, explicitly."""
        touched = []
        for run in self.store.runs_with_status({"queued", "running", "resuming", "awaiting_approval"}):
            snap = self.graph.get_state(self._config(run))
            pending = [i.value for t in snap.tasks for i in t.interrupts]
            if run["status"] == "awaiting_approval" and pending:
                continue  # a real pause: the checkpoint holds the interrupt; decisions resume it
            self.store.transition(run["run_id"], None, "interrupted", event="restart_detected",
                                  data={"previous_status": run["status"], "checkpoint_next": list(snap.next)},
                                  error_code="interrupted_by_restart",
                                  error_message=f"server restarted while run was {run['status']}; use Recover",
                                  retryable=True)
            touched.append(run["run_id"])
        return touched

    def checkpoint_info(self, run: dict) -> dict:
        snap = self.graph.get_state(self._config(run))
        pending = [i.value for t in snap.tasks for i in t.interrupts]
        return {"thread_id": run["thread_id"], "next_nodes": list(snap.next),
                "checkpoint_id": (snap.config or {}).get("configurable", {}).get("checkpoint_id"),
                "pending_interrupt": pending[0] if pending else None}

    def run_detail(self, run_id: str) -> dict:
        run = self.store.require_run(run_id)
        return {**run, "terminal": run["status"] in TERMINAL, "steps": self.store.steps(run_id),
                "proposals": self.store.proposals(run_id), "decisions": self.store.decisions(run_id),
                "actions": self.store.actions(run_id), "events": self.store.events(run_id),
                "checkpoint": self.checkpoint_info(run)}


def ensure_found(value, what: str):
    if value is None:
        raise NotFound(f"{what}_not_found", f"{what} not found")
    return value
