from backend.agents.base_agent import BaseAgent
from backend.prompts.templates import INSIGHT_SYSTEM
from backend.tools.ad_api import get_ad_api


class InsightAgent(BaseAgent):
    agent_name = "insight"
    system_prompt = INSIGHT_SYSTEM

    async def run(self, session_id, task, context=None):
        context = context or {}

        industry = context.get("industry", "tourism_hospitality")
        api = get_ad_api()
        try:
            benchmark = await api.get_industry_benchmark(industry)
            context["industry_benchmark"] = benchmark
        except Exception:
            pass

        client_name = context.get("client_name", "")
        if client_name:
            profile = self.memory.get_client_profile(client_name)
            if profile:
                context["existing_profile"] = profile

        return await super().run(session_id, task, context)
