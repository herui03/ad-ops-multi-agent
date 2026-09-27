"""Workflow policy: which actions are gated, deterministic compliance rules, proposal assembly.

The approval gate is decided here, by code, from the workflow type. It does not read any flag a
model produced, and no source document can change it.
"""
from __future__ import annotations

import re
from typing import Any

from backend.grounding import get_corpus

SIM_INTEGRATION = ("SimAds sandbox (simulated). No real ad platform is called, no campaign is created "
                   "and no money is spent.")

# Every workflow that ends in an action is gated. There is no ungated action path.
GATED_WORKFLOWS = {
    "campaign_launch": "simulated_launch_campaign",
    "performance_review": "simulated_budget_shift",
}
ROLES = {
    "requester": {"create_run", "cancel"},
    "approver": {"decide", "cancel", "recover"},
    "viewer": set(),
}

# rule_id -> (pattern, severity, citation chunk id). Citations must resolve in the corpus;
# tests/test_grounding.py checks this so a corpus edit cannot silently orphan a rule.
COMPLIANCE_RULES: dict[str, tuple[re.Pattern, str, str]] = {
    "superlative-claim": (re.compile(r"\b(best|no\.?\s?1|number one|top-rated|most popular|the only)\b", re.I),
                          "block", "simads-ad-policy@2.1#superlatives"),
    "guarantee-claim": (re.compile(r"\bguarantee(d|s)?\b|100% effective", re.I),
                        "block", "simads-ad-policy@2.1#guarantees"),
}
PRICE = re.compile(r"(s\$|sgd|\$)\s?\d|\d+\s?%\s?off", re.I)
VALIDITY = re.compile(r"\bvalid\b|\buntil\b|\bthrough\b|t&cs|terms apply|\b\d{1,2}\s?(jan|feb|mar|apr|may|jun|jul|"
                      r"aug|sep|oct|nov|dec)", re.I)
PRICE_RULE_CHUNK = "simads-ad-policy@2.1#price-claims"


def check_role(role: str, permission: str) -> bool:
    return permission in ROLES.get(role, set())


def deterministic_findings(creatives: list[dict]) -> list[dict]:
    findings = []
    for cr in creatives:
        text = f"{cr['headline']} {cr['body']}"
        for rule_id, (pattern, severity, chunk) in COMPLIANCE_RULES.items():
            m = pattern.search(text)
            if m:
                findings.append({"creative_id": cr["creative_id"], "rule_id": rule_id, "severity": severity,
                                 "description": f"contains {m.group(0)!r}", "citation_chunk_id": chunk,
                                 "source": "rule-engine"})
        if PRICE.search(text) and not VALIDITY.search(text):
            findings.append({"creative_id": cr["creative_id"], "rule_id": "price-without-validity",
                             "severity": "block", "description": "price claim without a validity period",
                             "citation_chunk_id": PRICE_RULE_CHUNK, "source": "rule-engine"})
    return findings


def _merge_findings(rule: list[dict], agent: list[dict], creative_ids: set[str]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for f in agent:
        if f["creative_id"] in creative_ids:
            merged[(f["creative_id"], f["rule_id"])] = {**f, "source": "compliance-agent"}
    for f in rule:  # the rule engine wins on duplicates; it is the backstop
        merged[(f["creative_id"], f["rule_id"])] = f
    return sorted(merged.values(), key=lambda f: (f["creative_id"], f["rule_id"]))


def _evidence(findings: list[dict]) -> list[dict]:
    corpus = get_corpus()
    out, seen = [], set()
    for f in findings:
        cid = f["citation_chunk_id"]
        c = corpus.by_id.get(cid)
        if c and cid not in seen:
            seen.add(cid)
            out.append({"chunk_id": cid, "title": c.title, "version": c.version, "kind": c.kind,
                        "sha256": c.sha256, "quote": c.text})
    return out


def build_proposal_payload(workflow_type: str, outputs: dict[str, dict], changes: list[dict], *,
                           high_spend_threshold: float, hard_budget_cap: float) -> dict[str, Any]:
    action_type = GATED_WORKFLOWS[workflow_type]
    blockers: list[str] = []
    risk_flags: list[str] = []
    applied = {"budget_total": None, "remove_creative_ids": []}
    for ch in changes:
        if "budget_total" in ch:
            applied["budget_total"] = ch["budget_total"]
        applied["remove_creative_ids"] += ch.get("remove_creative_ids", [])

    if workflow_type == "campaign_launch":
        strat, creative, comp = outputs["strategy"], outputs["creative"], outputs.get("compliance", {"findings": []})
        creatives = [c for c in creative["creatives"] if c["creative_id"] not in applied["remove_creative_ids"]]
        ids = {c["creative_id"] for c in creatives}
        findings = _merge_findings(deterministic_findings(creatives), comp.get("findings", []), ids)
        budget = float(applied["budget_total"] or strat["budget_total"])
        placements = [{"placement": p["placement"], "budget_pct": p["budget_pct"],
                       "amount": round(budget * p["budget_pct"] / 100, 2)} for p in strat["placements"]]
        blocking = [f for f in findings if f["severity"] == "block"]
        if blocking:
            blockers.append(f"{len(blocking)} blocking compliance finding(s); revise to remove the creative(s)")
        body: dict[str, Any] = {
            "campaign_name": strat["campaign_name"], "objective": strat["objective"],
            "schedule": strat["schedule"], "placements": placements, "targeting": strat.get("targeting", {}),
            "creatives": creatives,
            "compliance": {"findings": findings, "blocking_count": len(blocking),
                           "note": "Checked against fictional/unverified corpus text; not legal review."},
            "evidence": _evidence(findings),
        }
    else:  # performance_review
        ana = outputs["analytics"]
        shifts = ana["recommended_shifts"]
        budget = float(applied["budget_total"] or sum(s["amount"] for s in shifts))
        if not shifts:
            blockers.append("analytics recommended no budget shift; nothing to execute")
        body = {"campaign_name": "Sample campaign cmp_demo_001 (mock data)", "summary": ana["summary"],
                "anomalies": ana["anomalies"], "shifts": shifts, "creatives": [], "evidence": [],
                "compliance": {"findings": [], "blocking_count": 0, "note": "No creatives in this action."}}
    if budget > hard_budget_cap:
        blockers.append(f"amount {budget:,.0f} exceeds the hard cap {hard_budget_cap:,.0f}; revise the budget")
    if budget > high_spend_threshold:
        risk_flags.append(f"high_spend: {budget:,.0f} SGD is above {high_spend_threshold:,.0f}")
    return {
        "action_type": action_type,
        "integration": SIM_INTEGRATION,
        "amount": budget,
        "currency": "SGD",
        **body,
        "risk_flags": risk_flags,
        "policy": {"requires_approval": True, "approvable": not blockers, "blockers": blockers,
                   "rule": "Every simulated action requires a recorded decision from the approver role on this "
                           "exact proposal revision and hash. The rule is code (backend/policy.py), not model output."},
        "changes_applied": applied,
    }
