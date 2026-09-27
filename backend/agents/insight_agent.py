from backend.agents.base_agent import AgentSpec
from backend.contracts import InsightOutput
from backend.prompts.templates import INSIGHT_SYSTEM

SPEC = AgentSpec(name="insight", system_prompt=INSIGHT_SYSTEM, contract=InsightOutput,
                 description="Client and audience profile with mock benchmarks")
