from backend.agents.base_agent import BaseAgent
from backend.prompts.templates import CREATIVE_SYSTEM


class CreativeAgent(BaseAgent):
    agent_name = "creative"
    system_prompt = CREATIVE_SYSTEM

    async def run(self, session_id, task, context=None):
        context = context or {}
        strategy_output = self.memory.get_agent_output(session_id, "strategy")
        if strategy_output:
            context["media_plan"] = strategy_output
        insight_output = self.memory.get_agent_output(session_id, "insight")
        if insight_output:
            context["audience_insight"] = insight_output
        return await super().run(session_id, task, context)
