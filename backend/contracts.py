"""Strict contracts for everything a model produces, plus API request bodies.

Model output is untrusted input. The planner's plan is validated as a bounded DAG before
anything runs, and each agent's JSON must parse into its own schema or the step fails.
Unknown keys the model adds (e.g. "requires_human_approval", "auto_approve") are ignored:
the approval gate is workflow policy (policy.py), not a planner field.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

AGENTS = ("insight", "strategy", "creative", "analytics", "compliance", "ci")
MAX_PLAN_STEPS = 8
WORKFLOW_REQUIREMENTS = {
    # workflow type -> agents that must be present for the workflow to be meaningful
    "campaign_launch": {"strategy", "creative", "compliance"},
    "performance_review": {"analytics"},
    "pitch_support": {"ci"},
}
# Ordering constraints the plan must respect: key must (transitively) depend on each value.
REQUIRED_EDGES = {"creative": {"strategy"}, "compliance": {"creative"}}


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------------------------------------------------------------- plan
class PlanStep(_Model):
    id: str = Field(pattern=r"^s[1-9]$")
    agent: Literal["insight", "strategy", "creative", "analytics", "compliance", "ci"]
    task: str = Field(min_length=1, max_length=500)
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)


class Plan(_Model):
    route: Literal["workflow", "question"]
    workflow_type: Optional[Literal["campaign_launch", "performance_review", "pitch_support"]] = None
    steps: list[PlanStep] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)

    @model_validator(mode="after")
    def _check(self) -> "Plan":
        if self.route == "question":
            if self.steps:
                raise ValueError("a question route must not contain steps")
            return self
        if not self.workflow_type:
            raise ValueError("workflow route requires workflow_type")
        if not self.steps:
            raise ValueError("workflow route requires at least one step")
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate step ids")
        agents = [s.agent for s in self.steps]
        if len(set(agents)) != len(agents):
            raise ValueError("each agent may appear at most once")
        known = set(ids)
        for s in self.steps:
            missing = [d for d in s.depends_on if d not in known]
            if missing:
                raise ValueError(f"step {s.id} depends on unknown step(s) {missing}")
            if s.id in s.depends_on:
                raise ValueError(f"step {s.id} depends on itself")
        topological_order(self.steps)  # raises on cycles
        need = WORKFLOW_REQUIREMENTS[self.workflow_type] - set(agents)
        if need:
            raise ValueError(f"{self.workflow_type} requires agents {sorted(need)}")
        by_agent = {s.agent: s for s in self.steps}
        for agent, prereqs in REQUIRED_EDGES.items():
            if agent in by_agent:
                ancestors = _ancestors(by_agent[agent].id, self.steps)
                ancestor_agents = {s.agent for s in self.steps if s.id in ancestors}
                if not prereqs <= ancestor_agents:
                    raise ValueError(f"{agent} must depend on {sorted(prereqs)}")
        return self


def _ancestors(step_id: str, steps: list[PlanStep]) -> set[str]:
    by_id = {s.id: s for s in steps}
    seen: set[str] = set()
    stack = list(by_id[step_id].depends_on)
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(by_id[cur].depends_on)
    return seen


def topological_order(steps: list[PlanStep]) -> list[str]:
    """Kahn's algorithm, ties broken by step id. Raises ValueError on a cycle (fails closed)."""
    remaining = {s.id: set(s.depends_on) for s in steps}
    order: list[str] = []
    while remaining:
        ready = sorted(i for i, deps in remaining.items() if deps <= set(order))
        if not ready:
            raise ValueError(f"dependency cycle among steps {sorted(remaining)}")
        order.append(ready[0])
        del remaining[ready[0]]
    return order


# ---------------------------------------------------------------- agent outputs
class Benchmark(_Model):
    cpm: float = Field(ge=0)
    ctr: float = Field(ge=0, le=1)
    cpa: float = Field(ge=0)


class InsightOutput(_Model):
    client_name: str = Field(min_length=1, max_length=120)
    industry: str = Field(min_length=1, max_length=80)
    audience_summary: str = Field(min_length=1, max_length=800)
    key_insights: list[str] = Field(min_length=1, max_length=6)
    benchmark: Benchmark
    risks: list[str] = Field(default_factory=list, max_length=6)


class Comparison(_Model):
    platform: str = Field(min_length=1, max_length=60)
    strength: str = Field(min_length=1, max_length=300)
    weakness: str = Field(min_length=1, max_length=300)


class CIOutput(_Model):
    comparisons: list[Comparison] = Field(min_length=1, max_length=5)
    talking_points: list[str] = Field(min_length=1, max_length=6)


class Placement(_Model):
    placement: str = Field(min_length=1, max_length=60)
    budget_pct: float = Field(gt=0, le=100)


class Schedule(_Model):
    start: date
    end: date

    @model_validator(mode="after")
    def _order(self) -> "Schedule":
        if self.end < self.start:
            raise ValueError("schedule end precedes start")
        return self


class StrategyOutput(_Model):
    campaign_name: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=200)
    budget_total: float = Field(gt=0, le=10_000_000)
    currency: Literal["SGD"]
    schedule: Schedule
    placements: list[Placement] = Field(min_length=1, max_length=6)
    targeting: dict[str, str | list[str]] = Field(default_factory=dict)

    @field_validator("placements")
    @classmethod
    def _sum_to_100(cls, v: list[Placement]) -> list[Placement]:
        total = sum(p.budget_pct for p in v)
        if abs(total - 100) > 0.5:
            raise ValueError(f"placement budget_pct must sum to 100 (got {total:g})")
        return v


class Creative(_Model):
    creative_id: str = Field(pattern=r"^cr_[a-z0-9]{1,12}$")
    placement: str = Field(min_length=1, max_length=60)
    headline: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=400)
    cta: str = Field(min_length=1, max_length=40)


class CreativeOutput(_Model):
    creatives: list[Creative] = Field(min_length=1, max_length=6)


class ComplianceFinding(_Model):
    creative_id: str
    rule_id: str = Field(min_length=1, max_length=60)
    severity: Literal["block", "warning"]
    description: str = Field(min_length=1, max_length=400)
    citation_chunk_id: str = Field(min_length=1, max_length=120)


class ComplianceOutput(_Model):
    findings: list[ComplianceFinding] = Field(default_factory=list, max_length=20)


class Anomaly(_Model):
    metric: str
    deviation_pct: float
    severity: Literal["warning", "critical"]


class BudgetShift(_Model):
    from_placement: str
    to_placement: str
    amount: float = Field(gt=0)


class AnalyticsOutput(_Model):
    summary: str = Field(min_length=1, max_length=800)
    anomalies: list[Anomaly] = Field(default_factory=list, max_length=10)
    recommended_shifts: list[BudgetShift] = Field(default_factory=list, max_length=5)


AGENT_CONTRACTS: dict[str, type[_Model]] = {
    "insight": InsightOutput,
    "ci": CIOutput,
    "strategy": StrategyOutput,
    "creative": CreativeOutput,
    "compliance": ComplianceOutput,
    "analytics": AnalyticsOutput,
    "planner": Plan,
}


def validation_summary(err: ValidationError, limit: int = 3) -> str:
    """Short, content-free description of a validation error (no echo of model output)."""
    parts = []
    for e in err.errors()[:limit]:
        loc = ".".join(str(x) for x in e.get("loc", ())) or "<root>"
        detail = e.get("type")
        if detail == "value_error":  # messages from our own validators (DAG rules etc.)
            detail = str(e.get("msg", ""))[:160]
        parts.append(f"{loc}: {detail}")
    more = len(err.errors()) - limit
    return "; ".join(parts) + (f" (+{more} more)" if more > 0 else "")


# ---------------------------------------------------------------- API bodies
DemoFaultKind = Literal["provider_error", "timeout", "malformed_json", "wrong_schema"]


class DemoFault(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: Literal["planner", "insight", "strategy", "creative", "analytics", "compliance", "ci"] = "strategy"
    kind: DemoFaultKind
    fail_attempts: int = Field(default=2, ge=1, le=5)


class CreateRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=1)
    demo_fault: Optional[DemoFault] = None


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "reject", "revise"]
    comment: str = ""
    changes: Optional[dict] = None
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")
    comment: str = ""


SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
