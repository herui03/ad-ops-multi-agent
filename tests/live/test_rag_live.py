# test_rag_live.py — live tests for RAG retrieval and orchestrator routing.
# These call the Groq API and need GROQ_API_KEY; run with: pytest tests/live -q
import pytest
import json
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.agents.orchestrator import Orchestrator


@pytest.fixture(scope="module")
def orch():
    """One Orchestrator per module to avoid re-initialising models."""
    return Orchestrator()


# =============================================
# 1. General knowledge — direct answer, no agents
# =============================================

@pytest.mark.asyncio
async def test_general_what_is_cpm(orch):
    result = await orch.run(session_id="test-gen-001", user_input="What is CPM?")
    trace = result.get("agent_trace", [])

    has_direct = any(t.get("action") == "direct_answer" for t in trace)
    has_agent = any(t.get("action") == "execute" for t in trace)

    assert has_direct, "Should use direct_answer for general knowledge"
    assert not has_agent, "Should NOT call any agent for general knowledge"
    assert len(result["message"]) > 20, "Answer should not be empty"


@pytest.mark.asyncio
async def test_general_cpc_vs_cpm(orch):
    result = await orch.run(
        session_id="test-gen-002",
        user_input="What is the difference between CPC and CPM?",
    )
    trace = result.get("agent_trace", [])

    has_direct = any(t.get("action") == "direct_answer" for t in trace)
    has_agent = any(t.get("action") == "execute" for t in trace)

    assert has_direct
    assert not has_agent
    assert len(result["message"]) > 20


@pytest.mark.asyncio
async def test_general_feed_ads(orch):
    result = await orch.run(
        session_id="test-gen-003",
        user_input="How does feed advertising work?",
    )
    trace = result.get("agent_trace", [])

    has_direct = any(t.get("action") == "direct_answer" for t in trace)
    assert has_direct, "Platform knowledge question should be direct answer"


# =============================================
# 2. Agent tasks — should plan and invoke agents
# =============================================

@pytest.mark.asyncio
async def test_campaign_calls_agents(orch):
    result = await orch.run(
        session_id="test-agent-001",
        user_input="Create a feed-ad campaign for a Marina Bay hotel targeting Chinese tourists",
    )
    trace = result.get("agent_trace", [])

    has_agent = any(t.get("action") == "execute" for t in trace)
    has_direct = any(t.get("action") == "direct_answer" for t in trace)

    assert has_agent, "Campaign task should call agents"
    assert not has_direct, "Campaign task should NOT be direct answer"

    agents_called = [t["agent"] for t in trace if t.get("action") == "execute"]
    assert len(agents_called) >= 1, f"At least 1 agent should run, got: {agents_called}"


@pytest.mark.asyncio
async def test_analysis_calls_agents(orch):
    result = await orch.run(
        session_id="test-agent-002",
        user_input="Analyze the performance of our last campaign and find anomalies",
    )
    trace = result.get("agent_trace", [])

    has_agent = any(t.get("action") == "execute" for t in trace)
    assert has_agent, "Analysis task should call agents"


# =============================================
# 3. Edge cases
# =============================================

@pytest.mark.asyncio
async def test_empty_input(orch):
    """Empty input must not crash."""
    result = await orch.run(session_id="test-edge-001", user_input="")
    assert "message" in result


@pytest.mark.asyncio
async def test_chinese_input(orch):
    """Chinese-language input should work too."""
    result = await orch.run(
        session_id="test-edge-002",
        user_input="什么是朋友圈广告？",
    )
    assert "message" in result
    assert len(result["message"]) > 10


@pytest.mark.asyncio
async def test_result_structure(orch):
    """Response structure is complete."""
    result = await orch.run(session_id="test-struct-001", user_input="What is CPM?")

    assert "session_id" in result
    assert "message" in result
    assert "agent_trace" in result
    assert "pending_approvals" in result
    assert "intent" in result
    assert result["session_id"] == "test-struct-001"