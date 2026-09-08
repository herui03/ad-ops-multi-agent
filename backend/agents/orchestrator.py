from __future__ import annotations
import json
import uuid
import time
from typing import Any, TypedDict

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph import graph
from langgraph.graph import StateGraph, END

from backend.config import get_settings
from backend.memory.shared_memory import get_memory
from backend.prompts.templates import ORCHESTRATOR_SYSTEM, ORCHESTRATOR_SYNTHESIZE

from backend.agents.insight_agent import InsightAgent
from backend.agents.strategy_agent import StrategyAgent
from backend.agents.creative_agent import CreativeAgent
from backend.agents.analytics_agent import AnalyticsAgent
from backend.agents.compliance_agent import ComplianceAgent
from backend.agents.ci_agent import CIAgent


class OrchestratorState(TypedDict):
    session_id: str
    user_input: str
    intent: str
    plan: list[dict]
    requires_human_approval: bool
    approval_reason: str
    insight_result: dict | None
    strategy_result: dict | None
    creative_result: dict | None
    analytics_result: dict | None
    compliance_result: dict | None
    ci_result: dict | None
    agents_to_run: list[str]
    agent_trace: list[dict]
    pending_approvals: list[dict]
    approval_decisions: dict
    final_output: str
    error: str
    ws_callback: Any


class Orchestrator:

    def __init__(self):
        settings = get_settings()
        self.llm = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0.2,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.memory = get_memory()
        self.agents = {
            "insight": InsightAgent(),
            "strategy": StrategyAgent(),
            "creative": CreativeAgent(),
            "analytics": AnalyticsAgent(),
            "compliance": ComplianceAgent(),
            "ci": CIAgent(),
        }
        self.graph = self._build_graph()

    # =============================================
    # Change 1: _build_graph — add conditional branch + new node
    # =============================================
    def _build_graph(self) -> StateGraph:
        graph = StateGraph(OrchestratorState)

        graph.add_node("planning", self._plan_node)
        graph.add_node("direct_answer", self._direct_answer_node)    # New node
        graph.add_node("execute_agents", self._execute_agents_node)
        graph.add_node("human_review", self._human_review_node)
        graph.add_node("synthesize", self._synthesize_node)

        graph.set_entry_point("planning")

        # Change: after planning, check if plan is empty before executing agents
        graph.add_conditional_edges(
            "planning",
            self._should_execute_or_direct_answer,
            {
                "direct_answer": "direct_answer",
                "execute_agents": "execute_agents",
            },
        )

        graph.add_edge("direct_answer", END)                         # New edge

        graph.add_conditional_edges(
            "execute_agents",
            self._should_human_review,
            {"human_review": "human_review", "synthesize": "synthesize"},
        )
        graph.add_edge("human_review", "synthesize")
        graph.add_edge("synthesize", END)
        return graph.compile()

    # =============================================
    # Routing: empty plan -> direct answer; non-empty plan -> execute agents
    # =============================================
    def _should_execute_or_direct_answer(self, state: OrchestratorState) -> str:
        """If plan is empty, answer directly. Otherwise execute agents."""
        plan = state.get("plan", [])
        if not plan:
            return "direct_answer"
        return "execute_agents"

    # =============================================
    # New node: direct answer for general knowledge questions
    # =============================================
    async def _direct_answer_node(self, state: OrchestratorState) -> dict:
        """General knowledge questions: return the intent field as the final output."""
        ws = state.get("ws_callback")

        if ws:
            await ws({
                "type": "agent_status",
                "agent": "orchestrator",
                "status": "direct_answer",
            })

        intent = state.get("intent", "")

        if ws:
            await ws({
                "type": "agent_status",
                "agent": "orchestrator",
                "status": "completed",
            })

        return {
            "final_output": intent,
            "agent_trace": state.get("agent_trace", []) + [{
                "agent": "orchestrator",
                "action": "direct_answer",
                "output_summary": "Answered directly without specialist agents",
                "timestamp": time.time(),
            }],
        }

    async def _plan_node(self, state: OrchestratorState) -> dict:
        ws = state.get("ws_callback")
        if ws:
            await ws({"type": "agent_status", "agent": "orchestrator", "status": "planning"})

        messages = [
            SystemMessage(content=ORCHESTRATOR_SYSTEM),
            HumanMessage(content=state["user_input"]),
        ]

        response = await self.llm.ainvoke(messages)
        try:
            plan_data = json.loads(response.content)
        except json.JSONDecodeError:
            plan_data = {
                "intent": "general_query",
                "requires_human_approval": False,
                "plan": [{"step": 1, "agent": "insight", "task": state["user_input"], "depends_on": []}],
            }

        plan = plan_data.get("plan", [])
        agents_to_run = list({s["agent"] for s in plan if s["agent"] in self.agents})

        return {
            "intent": plan_data.get("intent", ""),
            "plan": plan,
            "requires_human_approval": plan_data.get("requires_human_approval", False),
            "approval_reason": plan_data.get("approval_reason", ""),
            "agents_to_run": agents_to_run,
            "agent_trace": state.get("agent_trace", []) + [{
                "agent": "orchestrator", "action": "plan",
                "output_summary": plan_data.get("intent", ""), "timestamp": time.time(),
            }],
        }

    async def _execute_agents_node(self, state: OrchestratorState) -> dict:
        ws = state.get("ws_callback")
        plan = state.get("plan", [])
        session_id = state["session_id"]
        context = {"session_id": session_id}

        results = {}
        trace = list(state.get("agent_trace", []))
        phases = self._group_by_phase(plan)

        for phase_steps in phases:
            for step in phase_steps:
                agent_name = step["agent"]
                task = step.get("task", state["user_input"])
                if agent_name not in self.agents:
                    continue

                if ws:
                    await ws({"type": "agent_status", "agent": agent_name, "status": "running"})

                try:
                    result = await self.agents[agent_name].run(session_id, task, context)
                    results[f"{agent_name}_result"] = result
                    trace.append({
                        "agent": agent_name, "action": "execute",
                        "output_summary": f"Done — {result.get('duration_ms', 0)}ms",
                        "success": result.get("success", False), "timestamp": time.time(),
                    })
                    if ws:
                        await ws({"type": "agent_status", "agent": agent_name,
                                  "status": "completed", "duration_ms": result.get("duration_ms", 0)})
                except Exception as e:
                    results[f"{agent_name}_result"] = {"error": str(e), "output": {}}
                    trace.append({
                        "agent": agent_name, "action": "execute",
                        "output_summary": f"Failed: {str(e)[:100]}", "success": False, "timestamp": time.time(),
                    })
                    if ws:
                        await ws({"type": "agent_status", "agent": agent_name, "status": "failed"})

        return {**results, "agent_trace": trace}

    async def _human_review_node(self, state: OrchestratorState) -> dict:
        ws = state.get("ws_callback")
        pending = []

        strategy = state.get("strategy_result", {})
        if strategy and strategy.get("output"):
            budget = strategy["output"].get("budget", {})
            total = budget.get("total_cny", 0)
            if total > 100000:
                approval = {
                    "approval_id": str(uuid.uuid4())[:8],
                    "session_id": state["session_id"],
                    "agent": "strategy",
                    "approval_type": "budget",
                    "title": f"Budget Confirmation: ¥{total:,.0f}",
                    "description": f"Campaign budget ¥{total:,.0f} exceeds ¥100K threshold. Please confirm.",
                    "data": strategy["output"],
                    "status": "pending",
                }
                pending.append(approval)
                self.memory.save_approval(approval)

        compliance = state.get("compliance_result", {})
        if compliance and compliance.get("output"):
            issues = compliance["output"].get("issues", [])
            blocking = [i for i in issues if i.get("severity") == "block"]
            if blocking:
                approval = {
                    "approval_id": str(uuid.uuid4())[:8],
                    "session_id": state["session_id"],
                    "agent": "compliance",
                    "approval_type": "compliance",
                    "title": f"Compliance Issues: {len(blocking)} blocking",
                    "description": "Blocking compliance issues found. Please review and decide.",
                    "data": {"issues": blocking},
                    "status": "pending",
                }
                pending.append(approval)
                self.memory.save_approval(approval)

        if ws and pending:
            await ws({"type": "human_approval_required", "approvals": pending})

        return {"pending_approvals": pending}

    async def _synthesize_node(self, state: OrchestratorState) -> dict:
        ws = state.get("ws_callback")
        if ws:
            await ws({"type": "agent_status", "agent": "orchestrator", "status": "synthesizing"})

        agent_outputs = {}
        for key in ["insight_result", "strategy_result", "creative_result",
                     "analytics_result", "compliance_result", "ci_result"]:
            val = state.get(key)
            if val and val.get("output"):
                agent_outputs[key.replace("_result", "")] = val["output"]

        synth_llm = ChatGroq(
            model=get_settings().groq_model,
            api_key=get_settings().groq_api_key,
            temperature=0.4,
        )

        prompt = ORCHESTRATOR_SYNTHESIZE.format(
            user_input=state["user_input"],
            agent_outputs=json.dumps(agent_outputs, ensure_ascii=False, indent=2)[:8000],
        )

        response = await synth_llm.ainvoke([HumanMessage(content=prompt)])
        final = response.content

        pending = state.get("pending_approvals", [])
        if pending:
            final += "\n\n---\n⚠️ **Items requiring your approval:**\n"
            for a in pending:
                final += f"- [{a['approval_type'].upper()}] {a['title']}: {a['description']}\n"

        if ws:
            await ws({"type": "agent_status", "agent": "orchestrator", "status": "completed"})

        return {"final_output": final}

    def _should_human_review(self, state: OrchestratorState) -> str:
        if state.get("requires_human_approval"):
            return "human_review"
        strategy = state.get("strategy_result", {})
        if strategy and strategy.get("output"):
            if strategy["output"].get("budget", {}).get("total_cny", 0) > 100000:
                return "human_review"
        compliance = state.get("compliance_result", {})
        if compliance and compliance.get("output"):
            if not compliance["output"].get("overall_pass", True):
                return "human_review"
        return "synthesize"

    @staticmethod
    def _group_by_phase(plan: list[dict]) -> list[list[dict]]:
        if not plan:
            return []
        phases, completed, remaining = [], set(), list(plan)
        while remaining:
            current, still_remaining = [], []
            for step in remaining:
                if set(step.get("depends_on", [])).issubset(completed):
                    current.append(step)
                else:
                    still_remaining.append(step)
            if not current:
                current, still_remaining = still_remaining, []
            phases.append(current)
            for step in current:
                completed.add(step.get("agent", ""))
            remaining = still_remaining
        return phases

    async def run(self, session_id: str, user_input: str, ws_callback=None) -> dict[str, Any]:
        initial_state: OrchestratorState = {
            "session_id": session_id, "user_input": user_input,
            "intent": "", "plan": [],
            "requires_human_approval": False, "approval_reason": "",
            "insight_result": None, "strategy_result": None,
            "creative_result": None, "analytics_result": None,
            "compliance_result": None, "ci_result": None,
            "agents_to_run": [], "agent_trace": [],
            "pending_approvals": [], "approval_decisions": {},
            "final_output": "", "error": "", "ws_callback": ws_callback,
        }

        self.memory.append_message(session_id, {"role": "user", "content": user_input})
        result = await self.graph.ainvoke(initial_state)
        self.memory.append_message(session_id, {"role": "assistant", "content": result.get("final_output", "")})

        return {
            "session_id": session_id,
            "message": result.get("final_output", "Processing complete."),
            "agent_trace": result.get("agent_trace", []),
            "pending_approvals": result.get("pending_approvals", []),
            "intent": result.get("intent", ""),
        }