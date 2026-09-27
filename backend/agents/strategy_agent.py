from backend.agents.base_agent import AgentSpec
from backend.contracts import StrategyOutput
from backend.prompts.templates import STRATEGY_SYSTEM

SPEC = AgentSpec(name="strategy", system_prompt=STRATEGY_SYSTEM, contract=StrategyOutput, reads=("insight",),
                 description="Media plan: budget, schedule, placement split, targeting")
