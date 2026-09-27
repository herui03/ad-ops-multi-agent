from backend.agents.base_agent import AgentSpec
from backend.contracts import CIOutput
from backend.prompts.templates import CI_SYSTEM

SPEC = AgentSpec(name="ci", system_prompt=CI_SYSTEM, contract=CIOutput, reads=("insight",),
                 description="Illustrative channel comparison and talking points")
