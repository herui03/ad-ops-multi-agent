"""Read-only mock data (fictional). There is no ad platform client in this project.

These figures are invented sample data for the demo. They are not measurements of any real
campaign or platform.
"""
from __future__ import annotations

MOCK_CAMPAIGN_STATS = {
    "campaign_id": "cmp_demo_001",
    "label": "mock data",
    "date_range": "2026-03-01 to 2026-03-31",
    "impressions": 5_280_000,
    "clicks": 63_360,
    "ctr": 0.012,
    "spend_sgd": 31_680,
    "cpm": 6.0,
    "cvr": 0.02,
    "breakdown_by_placement": {
        "Feed Ads": {"impressions": 3_168_000, "ctr": 0.014, "spend": 19_008},
        "Short-Video Ads": {"impressions": 1_584_000, "ctr": 0.011, "spend": 9_504},
        "Article Banner": {"impressions": 528_000, "ctr": 0.004, "spend": 3_168},
    },
}

MOCK_BENCHMARKS = {
    "tourism_hospitality": {"avg_cpm": 8.4, "avg_ctr": 0.011, "avg_cpa": 42.0, "avg_cvr": 0.018},
    "b2b_software": {"avg_cpm": 14.0, "avg_ctr": 0.008, "avg_cpa": 120.0, "avg_cvr": 0.012},
    "general": {"avg_cpm": 7.0, "avg_ctr": 0.010, "avg_cpa": 35.0, "avg_cvr": 0.015},
}
