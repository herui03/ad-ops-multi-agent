from backend.agents.base_agent import BaseAgent
from backend.prompts.templates import ANALYTICS_SYSTEM
from backend.tools.ad_api import get_ad_api
from backend.tools.data_tools import detect_anomalies, generate_report_summary


class AnalyticsAgent(BaseAgent):
    agent_name = "analytics"
    system_prompt = ANALYTICS_SYSTEM

    async def run(self, session_id, task, context=None):
        context = context or {}
        api = get_ad_api()

        campaign_id = context.get("campaign_id", "")
        if campaign_id:
            try:
                stats = await api.get_campaign_stats(campaign_id, ("2026-03-01", "2026-03-31"))
                context["campaign_stats"] = stats
                context["report_summary"] = generate_report_summary(stats)
                industry = context.get("industry", "tourism_hospitality")
                benchmark = await api.get_industry_benchmark(industry)
                context["anomalies"] = detect_anomalies(stats, benchmark)
            except Exception:
                pass

        return await super().run(session_id, task, context)
