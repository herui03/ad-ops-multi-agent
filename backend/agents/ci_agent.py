from backend.agents.base_agent import BaseAgent
from backend.prompts.templates import CI_SYSTEM


class CIAgent(BaseAgent):
    agent_name = "ci"
    system_prompt = CI_SYSTEM

    async def run(self, session_id, task, context=None):
        context = context or {}
        insight_output = self.memory.get_agent_output(session_id, "insight")
        if insight_output:
            context["client_insight"] = insight_output
        return await super().run(session_id, task, context)
