from __future__ import annotations
from typing import Any
from backend.config import get_settings


class AdPlatformAPI:

    def __init__(self):
        settings = get_settings()
        self.app_id = settings.ad_platform_app_id
        self.app_secret = settings.ad_platform_app_secret
        self.access_token = settings.ad_platform_access_token
        self.is_mock = not bool(self.access_token)

    async def get_campaign_stats(
        self, campaign_id: str, date_range: tuple[str, str]
    ) -> dict[str, Any]:
        if self.is_mock:
            return self._mock_campaign_stats(campaign_id)
        raise NotImplementedError("Real API integration pending")

    async def get_industry_benchmark(self, industry: str) -> dict[str, Any]:
        if self.is_mock:
            return self._mock_benchmark(industry)
        raise NotImplementedError("Real API integration pending")

    async def create_campaign(self, plan: dict) -> dict[str, Any]:
        if self.is_mock:
            return {
                "status": "mock_created",
                "campaign_id": "mock_camp_001",
                "message": "Mock mode — no real campaign created",
            }
        raise NotImplementedError("Real API integration pending")

    async def get_ad_creatives(self, campaign_id: str) -> list[dict]:
        if self.is_mock:
            return self._mock_creatives()
        raise NotImplementedError

    @staticmethod
    def _mock_campaign_stats(campaign_id: str) -> dict[str, Any]:
        return {
            "campaign_id": campaign_id,
            "date_range": "2026-03-01 to 2026-03-31",
            "impressions": 5_280_000,
            "clicks": 63_360,
            "ctr": 0.012,
            "spend_cny": 158_400,
            "cpm": 30.0,
            "cpc": 2.5,
            "conversions": 1_267,
            "cvr": 0.02,
            "cpa": 125.0,
            "roas": 3.2,
            "breakdown_by_placement": {
                "Moments Feed": {"impressions": 3_168_000, "ctr": 0.014, "spend": 95_040},
                "Channels Feed": {"impressions": 1_584_000, "ctr": 0.011, "spend": 47_520},
                "Official Account Banner": {"impressions": 528_000, "ctr": 0.006, "spend": 15_840},
            },
        }

    @staticmethod
    def _mock_benchmark(industry: str) -> dict[str, Any]:
        benchmarks = {
            "tourism_hospitality": {
                "avg_cpm": 42, "avg_ctr": 0.011, "avg_cpc": 3.8,
                "avg_cvr": 0.018, "avg_cpa": 210,
                "top_format": "Moments Video Ad (15s)",
                "peak_seasons": ["Chinese New Year", "Golden Week May", "Summer", "National Day Oct"],
            },
            "retail_luxury": {
                "avg_cpm": 55, "avg_ctr": 0.009, "avg_cpc": 6.1,
                "avg_cvr": 0.012, "avg_cpa": 510,
                "top_format": "Moments Brand Ad",
                "peak_seasons": ["Singles Day 11.11", "CNY", "618"],
            },
            "fnb": {
                "avg_cpm": 28, "avg_ctr": 0.015, "avg_cpc": 1.9,
                "avg_cvr": 0.025, "avg_cpa": 76,
                "top_format": "Moments Local Promotion",
                "peak_seasons": ["CNY", "Golden Week May", "National Day Oct"],
            },
        }
        return benchmarks.get(industry, benchmarks["tourism_hospitality"])

    @staticmethod
    def _mock_creatives() -> list[dict]:
        return [
            {
                "creative_id": "cr_001", "format": "Moments Video Ad",
                "status": "active", "headline": "This CNY, discover Singapore like never before",
                "ctr": 0.018, "impressions": 1_200_000,
            },
            {
                "creative_id": "cr_002", "format": "Moments Image Ad",
                "status": "active", "headline": "CNY Special | Save 20% on Singapore stays",
                "ctr": 0.012, "impressions": 800_000,
            },
        ]


_api_instance = None


def get_ad_api() -> AdPlatformAPI:
    global _api_instance
    if _api_instance is None:
        _api_instance = AdPlatformAPI()
    return _api_instance
