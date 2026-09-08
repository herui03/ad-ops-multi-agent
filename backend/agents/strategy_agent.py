from backend.agents.base_agent import BaseAgent
from backend.prompts.templates import STRATEGY_SYSTEM


class StrategyAgent(BaseAgent):
    agent_name = "strategy"
    system_prompt = STRATEGY_SYSTEM

    async def run(self, session_id, task, context=None):
        context = context or {}
        insight_output = self.memory.get_agent_output(session_id, "insight")
        if insight_output:
            context["insight_report"] = insight_output
        return await super().run(session_id, task, context)
