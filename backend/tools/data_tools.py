"""Pure analytics helpers used by the analytics agent."""
from __future__ import annotations


def detect_anomalies(current: dict, benchmark: dict) -> list[dict]:
    """Flag metrics that deviate from the benchmark by more than a per-metric threshold."""
    anomalies = []
    for curr_key, bench_key, threshold, label in (("ctr", "avg_ctr", 0.3, "CTR"), ("cpm", "avg_cpm", 0.4, "CPM"),
                                                  ("cvr", "avg_cvr", 0.3, "Conversion Rate")):
        curr_val, bench_val = current.get(curr_key, 0), benchmark.get(bench_key, 0)
        if not bench_val:
            continue
        deviation = (curr_val - bench_val) / bench_val
        if abs(deviation) > threshold:
            anomalies.append({"metric": label, "deviation_pct": round(deviation * 100, 1),
                              "severity": "warning" if abs(deviation) < 0.5 else "critical"})
    return anomalies


def recommend_shift(breakdown: dict[str, dict], share: float = 0.5) -> list[dict]:
    """Move `share` of the weakest-CTR placement's spend to the strongest-CTR placement."""
    if len(breakdown) < 2:
        return []
    ranked = sorted(breakdown.items(), key=lambda kv: kv[1]["ctr"])
    (worst, w), (best, _) = ranked[0], ranked[-1]
    amount = round(w["spend"] * share, 2)
    return [{"from_placement": worst, "to_placement": best, "amount": amount}] if amount > 0 else []
