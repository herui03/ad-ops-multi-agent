from backend.agents.base_agent import AgentSpec
from backend.contracts import CreativeOutput
from backend.prompts.templates import CREATIVE_SYSTEM


def _unique_ids(out, _ctx) -> None:
    ids = [c.creative_id for c in out.creatives]
    if len(ids) != len(set(ids)):
        raise ValueError("creative_id values must be unique")


SPEC = AgentSpec(name="creative", system_prompt=CREATIVE_SYSTEM, contract=CreativeOutput, reads=("strategy", "insight"),
                 semantic_check=_unique_ids, description="Ad copy per placement")
