from backend.agents.base_agent import BaseAgent
from backend.prompts.templates import COMPLIANCE_SYSTEM
from backend.rag import search_documents

class ComplianceAgent(BaseAgent):
    agent_name = "compliance"
    system_prompt = COMPLIANCE_SYSTEM
    use_fast_model = True

    async def run(self, session_id, task, context=None):
        context = context or {}

        creative_output = self.memory.get_agent_output(session_id, "creative")
        if creative_output:
            context["creatives_to_review"] = creative_output

        search_query = task
        if creative_output and isinstance(creative_output, dict):
            search_query = str(creative_output.get("creatives", task))
        elif creative_output and isinstance(creative_output, str):
            search_query = creative_output

        relevant_docs = search_documents(search_query, k=3)
        if relevant_docs:
            context["retrieved_regulations_from_rag"] = relevant_docs

        return await super().run(session_id, task, context)