from backend.agents.base_agent import AgentSpec
from backend.contracts import AnalyticsOutput
from backend.prompts.templates import ANALYTICS_SYSTEM
from backend.tools.mock_data import MOCK_BENCHMARKS, MOCK_CAMPAIGN_STATS


def _mock_stats(_context: dict) -> dict:
    return {"mock_campaign_stats": MOCK_CAMPAIGN_STATS, "mock_benchmark": MOCK_BENCHMARKS["tourism_hospitality"]}


SPEC = AgentSpec(name="analytics", system_prompt=ANALYTICS_SYSTEM, contract=AnalyticsOutput,
                 extra_context=_mock_stats, description="Mock performance review and budget-shift recommendation")
