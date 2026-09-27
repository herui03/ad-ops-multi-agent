"""Deterministic stand-ins for model output in demo mode.

Same input, same output, no randomness, no network. The generators read only the payload they
are given (request text, task, upstream outputs). They produce the same JSON shapes a live model
is asked for, and that output then goes through the same schema validation, gate and simulator.
They are rules, not intelligence, and the UI labels every demo run accordingly.
"""
from __future__ import annotations

import re

from backend.tools.data_tools import detect_anomalies, recommend_shift
from backend.tools.mock_data import MOCK_BENCHMARKS, MOCK_CAMPAIGN_STATS

QUESTION_START = re.compile(r"^(what|how|why|when|where|who|which|is|are|can|could|do|does|should|may|must|explain)\b",
                            re.I)
_WORK_VERBS = r"(plan|create|launch|draft|generate|build|prepare|write|analy[sz]e|review|report|optimi[sz]e|compare|pitch|shift)"
IMPERATIVE = re.compile(rf"^(please\s+)?{_WORK_VERBS}\b", re.I)
REQUEST_FOR_WORK = re.compile(rf"^(please\s+)?(can|could|would|will)\s+you\s+(please\s+)?{_WORK_VERBS}\b", re.I)
PERFORMANCE = re.compile(r"\b(performance|report|anomal\w*|underperform\w*|optimi[sz]e|reallocat\w*|shift)\b", re.I)
PITCH = re.compile(r"\b(pitch|competitor\w*|compare|comparison|versus|vs\.?)\b", re.I)
BUDGET = re.compile(r"(?:s\$|sgd\s?|\$)\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?\b|\b(\d[\d,]*(?:\.\d+)?)\s?(k)?\s?(?:sgd|budget)\b",
                    re.I)


def parse_budget(text: str, default: float = 60_000) -> float:
    m = BUDGET.search(text)
    if not m:
        return default
    num, k = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    value = float(num.replace(",", "")) * (1000 if k else 1)
    return value if value > 0 else default


def _client(text: str) -> tuple[str, str]:
    low = text.lower()
    if "novabyte" in low:
        return "NovaByte Technologies (fictional)", "b2b_software"
    if "harbourlight" in low or "hotel" in low:
        return "Harbourlight Hotel (fictional)", "tourism_hospitality"
    return "Sample client (fictional)", "general"


def plan(payload: dict) -> dict:
    text = payload["request"].strip()
    asks_for_work = bool(IMPERATIVE.match(text) or REQUEST_FOR_WORK.match(text))
    is_question = bool(text.endswith("?") or QUESTION_START.match(text)) and not asks_for_work
    if is_question:
        return {"route": "question", "steps": []}
    if PERFORMANCE.search(text) and not re.search(r"\b(launch|create)\b", text, re.I):
        return {"route": "workflow", "workflow_type": "performance_review",
                "steps": [{"id": "s1", "agent": "analytics", "task": "Review mock campaign performance against "
                           "benchmarks and recommend a budget shift", "depends_on": []}]}
    if PITCH.search(text) and not re.search(r"\b(launch|campaign plan|creatives?)\b", text, re.I):
        return {"route": "workflow", "workflow_type": "pitch_support",
                "steps": [{"id": "s1", "agent": "insight", "task": "Profile the client and audience", "depends_on": []},
                          {"id": "s2", "agent": "ci", "task": "Prepare channel comparison and talking points",
                           "depends_on": ["s1"]}]}
    return {"route": "workflow", "workflow_type": "campaign_launch", "steps": [
        {"id": "s1", "agent": "insight", "task": "Profile the client, audience and benchmarks", "depends_on": []},
        {"id": "s2", "agent": "strategy", "task": "Build the media plan and budget split", "depends_on": ["s1"]},
        {"id": "s3", "agent": "creative", "task": "Draft ad copy per placement", "depends_on": ["s2"]},
        {"id": "s4", "agent": "compliance", "task": "Check creatives against the policy corpus", "depends_on": ["s3"]},
    ]}


def insight(payload: dict) -> dict:
    name, industry = _client(payload["request"])
    b = MOCK_BENCHMARKS[industry]
    return {"client_name": name, "industry": industry,
            "audience_summary": "Leisure travellers planning a 2-4 night city stay, plus families in school holidays."
            if industry == "tourism_hospitality" else "Analytics and data leaders at mid-sized companies.",
            "key_insights": ["Mock benchmark data only; no real audience data was used.",
                             "Short-video placements suit discovery; search suits high-intent users."],
            "benchmark": {"cpm": b["avg_cpm"], "ctr": b["avg_ctr"], "cpa": b["avg_cpa"]},
            "risks": ["Price messaging must state validity periods (see SimAds policy)."]}


def strategy(payload: dict) -> dict:
    name = payload.get("context", {}).get("insight", {}).get("client_name", "Sample client (fictional)")
    return {"campaign_name": f"{name.split(' (')[0]} - Year-end stays",
            "objective": "Direct bookings", "budget_total": parse_budget(payload["request"]), "currency": "SGD",
            "schedule": {"start": "2026-11-02", "end": "2026-11-29"},
            "placements": [{"placement": "Feed Ads", "budget_pct": 50}, {"placement": "Short-Video Ads", "budget_pct": 30},
                           {"placement": "Search Ads", "budget_pct": 20}],
            "targeting": {"geo": ["Singapore"], "age_range": "25-54", "interests": ["city breaks", "dining"]}}


def creative(payload: dict) -> dict:
    req = payload["request"].lower()
    brand = payload.get("context", {}).get("strategy", {}).get("campaign_name", "Harbourlight").split(" - ")[0]
    second_headline = f"{brand}: harbour views, two nights from S$320"
    second_body = "Rooftop garden, late checkout. Valid for stays 2-29 Nov 2026; T&Cs apply."
    if re.search(r"\b(best|no\.?\s?1|number one)\b", req):
        second_headline = f"Singapore's best harbour view at {brand}"
    if "guarantee" in req:
        second_body = "Guaranteed room upgrade on every booking."
    if re.search(r"\b(no|without) dates?\b", req):
        second_body = "Rooftop garden, late checkout. From S$320 per night."
    return {"creatives": [
        {"creative_id": "cr_a1", "placement": "Feed Ads", "headline": f"Dusk on the harbour at {brand}",
         "body": "Walk to the food street, then watch the lights from the rooftop garden.", "cta": "See rooms"},
        {"creative_id": "cr_b2", "placement": "Short-Video Ads", "headline": second_headline, "body": second_body,
         "cta": "Book now"},
    ]}


def compliance(payload: dict) -> dict:
    from backend.policy import deterministic_findings
    creatives = payload.get("context", {}).get("creative", {}).get("creatives", [])
    return {"findings": [{k: v for k, v in f.items() if k != "source"} for f in deterministic_findings(creatives)]}


def ci(payload: dict) -> dict:
    return {"comparisons": [
        {"platform": "Search advertising (generic)", "strength": "Captures users already searching for stays.",
         "weakness": "Little room for visual storytelling."},
        {"platform": "Short-video social (generic)", "strength": "Strong discovery for younger travellers.",
         "weakness": "Creative wears out quickly; needs frequent refresh."}],
        "talking_points": ["Illustrative comparison only: no market-share or audience-size figures are claimed.",
                           "Recommend a test budget with a clear success metric before scaling."]}


def analytics(payload: dict) -> dict:
    stats = MOCK_CAMPAIGN_STATS
    bench = MOCK_BENCHMARKS["tourism_hospitality"]
    anomalies = detect_anomalies(stats, bench)
    for name, p in stats["breakdown_by_placement"].items():
        for a in detect_anomalies({"ctr": p["ctr"]}, {"avg_ctr": bench["avg_ctr"]}):
            anomalies.append({**a, "metric": f"{name} {a['metric']}"})
    return {"summary": "Mock campaign cmp_demo_001: Article Banner CTR is well below the other placements.",
            "anomalies": anomalies, "recommended_shifts": recommend_shift(stats["breakdown_by_placement"])}


GENERATORS = {"planner": plan, "insight": insight, "strategy": strategy, "creative": creative,
              "compliance": compliance, "ci": ci, "analytics": analytics}


def generate(role: str, payload: dict) -> dict:
    return GENERATORS[role](payload)
