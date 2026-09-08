import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_orchestrator_initialization():
    from backend.agents.orchestrator import Orchestrator
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        orch = Orchestrator()
        assert set(orch.agents.keys()) == {"insight", "strategy", "creative", "analytics", "compliance", "ci"}


@pytest.mark.asyncio
async def test_phase_grouping():
    from backend.agents.orchestrator import Orchestrator
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        orch = Orchestrator()
    plan = [
        {"step": 1, "agent": "insight", "task": "Analyze client", "depends_on": []},
        {"step": 2, "agent": "ci", "task": "Competitive analysis", "depends_on": []},
        {"step": 3, "agent": "strategy", "task": "Create plan", "depends_on": ["insight"]},
        {"step": 4, "agent": "creative", "task": "Generate creatives", "depends_on": ["strategy"]},
        {"step": 5, "agent": "compliance", "task": "Review", "depends_on": ["creative"]},
    ]
    phases = orch._group_by_phase(plan)
    assert len(phases) == 4
    assert {s["agent"] for s in phases[0]} == {"insight", "ci"}
    assert phases[1][0]["agent"] == "strategy"
    assert phases[2][0]["agent"] == "creative"
    assert phases[3][0]["agent"] == "compliance"


def test_memory_session():
    from backend.memory.shared_memory import SharedMemory
    mem = SharedMemory()
    mem.append_message("test1", {"role": "user", "content": "hello"})
    mem.append_message("test1", {"role": "assistant", "content": "hi"})
    msgs = mem.get_session("test1")
    assert len(msgs) == 2
    assert msgs[0]["content"] == "hello"


def test_memory_agent_output():
    from backend.memory.shared_memory import SharedMemory
    mem = SharedMemory()
    mem.save_agent_output("test2", "insight", {"client": "MBS"})
    result = mem.get_agent_output("test2", "insight")
    assert result["client"] == "MBS"
    all_out = mem.get_all_agent_outputs("test2")
    assert "insight" in all_out
