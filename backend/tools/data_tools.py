from __future__ import annotations
from typing import Any
from datetime import datetime


def generate_report_summary(
    campaign_data: dict, period: str = "weekly"
) -> dict[str, Any]:
    impressions = campaign_data.get("impressions", 0)
    clicks = campaign_data.get("clicks", 0)
    ctr = campaign_data.get("ctr", 0)
    spend = campaign_data.get("spend_cny", 0)
    roas = campaign_data.get("roas", 0)

    return {
        "period": period,
        "generated_at": datetime.utcnow().isoformat(),
        "headline_metrics": {
            "impressions": f"{impressions:,}",
            "clicks": f"{clicks:,}",
            "ctr": f"{ctr:.1%}",
            "spend": f"¥{spend:,.0f}",
            "roas": f"{roas:.1f}x",
        },
        "status": "healthy" if ctr > 0.008 else "needs_attention",
    }


def detect_anomalies(current: dict, benchmark: dict) -> list[dict]:
    anomalies = []
    checks = [
        ("ctr", "avg_ctr", 0.3, "CTR"),
        ("cpm", "avg_cpm", 0.4, "CPM"),
        ("cvr", "avg_cvr", 0.3, "Conversion Rate"),
    ]
    for curr_key, bench_key, threshold, label in checks:
        curr_val = current.get(curr_key, 0)
        bench_val = benchmark.get(bench_key, 0)
        if bench_val == 0:
            continue
        deviation = (curr_val - bench_val) / bench_val
        if abs(deviation) > threshold:
            direction = "above" if deviation > 0 else "below"
            anomalies.append({
                "metric": label,
                "current": curr_val,
                "benchmark": bench_val,
                "deviation": f"{deviation:+.1%}",
                "severity": "warning" if abs(deviation) < 0.5 else "critical",
                "message": f"{label} is {abs(deviation):.0%} {direction} industry benchmark",
            })
    return anomalies


def calculate_budget_allocation(
    total_budget: float, placements: list[dict]
) -> list[dict]:
    result = []
    for p in placements:
        pct = p.get("budget_pct", 0) / 100
        result.append({**p, "budget_absolute_cny": round(total_budget * pct, 2)})
    return result
