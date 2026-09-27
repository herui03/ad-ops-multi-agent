"""Reproduce defects in the ORIGINAL baseline (main @ 5ac2c35) before they were fixed.

This script is evidence, not part of the product. It imports the *baseline* source tree,
replaces the Groq chat model with a scripted stub (no network, no key), and prints one
line per defect: REPRODUCED or NOT REPRODUCED.

Usage (needs the baseline's own requirements: langchain-groq, langgraph 0.2.x, ...):

    git worktree add /tmp/adops-baseline 5ac2c35eb61ff21746ab9252eeddffe3aeefad3a
    python -m venv /tmp/adops-baseline-venv
    /tmp/adops-baseline-venv/bin/pip install -r /tmp/adops-baseline/requirements.txt
    GROQ_API_KEY=placeholder /tmp/adops-baseline-venv/bin/python \
        scripts/repro_baseline_defects.py /tmp/adops-baseline

Recorded output: docs/evidence/baseline-defects.txt
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

BASELINE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "../baseline")
os.environ.setdefault("GROQ_API_KEY", "placeholder-not-a-real-key")
os.environ["REDIS_URL"] = ""
sys.path.insert(0, BASELINE)
os.chdir(BASELINE)

from fastapi.testclient import TestClient  # noqa: E402


class Reply:
    def __init__(self, content: str):
        self.content = content


class ScriptedLLM:
    """Stands in for ChatGroq: returns queued strings, or raises queued exceptions."""

    def __init__(self, replies):
        self.replies = list(replies)

    async def ainvoke(self, _messages):
        item = self.replies.pop(0) if self.replies else "{}"
        if isinstance(item, Exception):
            raise item
        return Reply(item)


results: list[tuple[str, bool, str]] = []


def record(defect_id: str, reproduced: bool, detail: str) -> None:
    results.append((defect_id, reproduced, detail))


def fresh_orchestrator():
    from backend.agents import orchestrator as orch_mod
    from backend.memory import shared_memory

    shared_memory._memory_instance = None  # new in-process store per scenario
    orch = orch_mod.Orchestrator()
    return orch, orch_mod


def patch_synth(orch_mod, text="FINAL BRIEF"):
    class _Synth:
        def __init__(self, *a, **k):
            pass

        async def ainvoke(self, _m):
            return Reply(text)

    orch_mod.ChatGroq = _Synth


async def main() -> None:
    import backend.main as main_mod

    client = TestClient(main_mod.app)

    # D1: HTTP decision on an approval id that does not exist -> success-like response.
    r = client.post("/api/approvals/does-not-exist/decide",
                    json={"approval_id": "does-not-exist", "decision": "approved"})
    record("D1 http-decide-unknown-id", r.status_code == 200 and r.json().get("message") == "Decision recorded",
           f"status={r.status_code} body={r.json()}")

    # D2: WebSocket approval_decision bypass: same no-op resolve, acknowledged as resolved.
    with client.websocket_connect("/ws/s-ws") as ws:
        ws.send_text(json.dumps({"type": "approval_decision", "approval_id": "nope", "decision": "approved"}))
        msg = ws.receive_json()
    record("D2 ws-decide-bypass", msg.get("type") == "approval_resolved", f"ws reply={msg}")

    # D2b: malformed JSON over WS crashes the handler (no validation).
    try:
        with client.websocket_connect("/ws/s-ws2") as ws:
            ws.send_text("{not json")
            ws.receive_json()
        record("D2b ws-malformed-json", False, "handler replied normally")
    except Exception as e:  # noqa: BLE001
        record("D2b ws-malformed-json", True, f"connection error: {type(e).__name__}")

    # D3 + D11: budget > 100k creates a 'pending' approval, but the graph still synthesizes a final
    # answer in the same invocation; approval_decisions is never read.
    orch, orch_mod = fresh_orchestrator()
    patch_synth(orch_mod)
    orch.llm = ScriptedLLM([json.dumps({
        "intent": "campaign", "requires_human_approval": False,
        "plan": [{"step": 1, "agent": "strategy", "task": "plan", "depends_on": []}]})])
    orch.agents["strategy"].llm = ScriptedLLM([json.dumps({"budget": {"total_cny": 250000}})])
    out = await orch.run("s-d3", "plan a big campaign")
    record("D3 pending-approval-not-a-pause",
           bool(out["pending_approvals"]) and out["message"].startswith("FINAL BRIEF"),
           f"pending={len(out['pending_approvals'])} final_message_prefix={out['message'][:11]!r}")
    src = open(os.path.join(BASELINE, "backend/agents/orchestrator.py")).read()
    record("D11 approval-decisions-unused", src.count("approval_decisions") <= 2,
           f"'approval_decisions' occurrences in orchestrator.py={src.count('approval_decisions')} (declared + initialised only)")

    # D4: planner says requires_human_approval=true, but no budget/blocking issue -> zero approvals, finalizes.
    orch, orch_mod = fresh_orchestrator()
    patch_synth(orch_mod)
    orch.llm = ScriptedLLM([json.dumps({
        "intent": "x", "requires_human_approval": True, "approval_reason": "spend",
        "plan": [{"step": 1, "agent": "insight", "task": "t", "depends_on": []}]})])
    orch.agents["insight"].llm = ScriptedLLM([json.dumps({"client_name": "c"})])
    out = await orch.run("s-d4", "x")
    record("D4 llm-approval-flag-yields-no-gate",
           out["pending_approvals"] == [] and out["message"].startswith("FINAL BRIEF"),
           f"pending={out['pending_approvals']} finalized={out['message'][:11]!r}")

    # D5: _group_by_phase fails open on a cycle and on a dangling dependency.
    from backend.agents.orchestrator import Orchestrator
    cyc = Orchestrator._group_by_phase([
        {"agent": "strategy", "depends_on": ["creative"]},
        {"agent": "creative", "depends_on": ["strategy"]}])
    dang = Orchestrator._group_by_phase([{"agent": "strategy", "depends_on": ["ghost"]}])
    record("D5 dag-fails-open", sum(map(len, cyc)) == 2 and sum(map(len, dang)) == 1,
           f"cycle phases={[[s['agent'] for s in p] for p in cyc]} dangling phases={[[s['agent'] for s in p] for p in dang]}")

    # D6: an agent whose model call fails is reported to the UI as 'completed'.
    orch, orch_mod = fresh_orchestrator()
    patch_synth(orch_mod)
    orch.llm = ScriptedLLM([json.dumps({"intent": "x", "plan": [
        {"step": 1, "agent": "strategy", "task": "t", "depends_on": []}]})])
    orch.agents["strategy"].llm = ScriptedLLM([TimeoutError("provider timed out")])
    events = []

    async def cb(e):
        events.append(e)
    out = await orch.run("s-d6", "x", ws_callback=cb)
    strat = [e["status"] for e in events if e.get("agent") == "strategy"]
    trace = [t for t in out["agent_trace"] if t["agent"] == "strategy"]
    record("D6 failed-agent-shown-completed", "completed" in strat and trace and trace[0]["success"] is False,
           f"ui statuses={strat} trace_success={trace[0]['success'] if trace else None} final={out['message'][:11]!r}")

    # D7: malformed planner JSON silently falls back to an unapproved insight task.
    orch, orch_mod = fresh_orchestrator()
    patch_synth(orch_mod)
    orch.llm = ScriptedLLM(["this is not json"])
    orch.agents["insight"].llm = ScriptedLLM([json.dumps({"ok": 1})])
    out = await orch.run("s-d7", "anything")
    ran = [t["agent"] for t in out["agent_trace"] if t["action"] == "execute"]
    record("D7 malformed-plan-fallback-executes", ran == ["insight"], f"agents executed={ran}")

    # D8: invalid agent JSON counts as success.
    from backend.agents.insight_agent import InsightAgent
    a = InsightAgent()
    a.llm = ScriptedLLM(["<<not json>>"])
    res = await a.run("s-d8", "t")
    record("D8 parse-error-counts-as-success", res["success"] is True and res["output"].get("_parse_error"),
           f"success={res['success']} output_keys={sorted(res['output'])}")
    a.llm = ScriptedLLM([json.dumps(["a", "list", "not", "an", "object"])])
    res = await a.run("s-d8b", "t")
    record("D8b wrong-schema-counts-as-success", res["success"] is True, f"success={res['success']} output={res['output']}")

    # D9: dashboard numbers are hard-coded constants.
    s = client.get("/api/dashboard/stats").json()
    record("D9 dashboard-hardcoded", (s["active_campaigns"], s["total_clients"], s["monthly_spend_cny"], s["avg_roas"],
                                      s["pending_approvals"]) == (12, 48, 2_850_000, 2.8, 3), f"stats={ {k: s[k] for k in list(s)[:5]} }")

    # D10: graph compiled without a checkpointer -> nothing to resume after a restart.
    orch, _ = fresh_orchestrator()
    record("D10 no-checkpointer", getattr(orch.graph, "checkpointer", None) is None,
           f"graph.checkpointer={getattr(orch.graph, 'checkpointer', None)!r}")

    for defect_id, ok, detail in results:
        print(f"{'REPRODUCED    ' if ok else 'NOT REPRODUCED'} {defect_id}: {detail}")
    print(f"\n{sum(ok for _, ok, _ in results)}/{len(results)} baseline defects reproduced")


if __name__ == "__main__":
    asyncio.run(main())
