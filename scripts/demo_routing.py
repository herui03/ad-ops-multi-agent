# demo_routing.py — manual check of orchestrator routing (direct answer vs. agent plan).
# Requires GROQ_API_KEY in .env. Run: python scripts/demo_routing.py
import asyncio
import json
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.orchestrator import Orchestrator


async def test():
    orch = Orchestrator()

    # =============================================
    # Test 1: general knowledge questions — should NOT invoke any agent
    # =============================================
    print("=" * 60)
    print("Test 1: General knowledge (expect a direct answer, no agents)")
    print("=" * 60)

    general_questions = [
        "What is CPM?",
        "What is the difference between CPC and CPM?",
        "How does feed advertising work?",
    ]

    for q in general_questions:
        print(f"\n🔍 Question: {q}")

        result = await orch.run(
            session_id="test-general-001",
            user_input=q,
        )

        trace = result.get("agent_trace", [])
        has_direct_answer = any(
            t.get("action") == "direct_answer" for t in trace
        )
        has_agent_execution = any(
            t.get("action") == "execute" for t in trace
        )

        if has_direct_answer and not has_agent_execution:
            print(f"✅ PASS — Direct answer, no agents called")
        elif has_agent_execution:
            print(f"❌ FAIL — Agents were called (should have been direct)")
            agents_called = [t["agent"] for t in trace if t.get("action") == "execute"]
            print(f"   Agents called: {agents_called}")
        else:
            print(f"⚠️  UNCLEAR — Check trace manually")

        # show the first 200 characters of the answer
        msg = result.get("message", "")
        preview = msg[:200] + "..." if len(msg) > 200 else msg
        print(f"📝 Answer: {preview}")

        print(f"🔗 Trace: {json.dumps(trace, indent=2, default=str)}")

    # =============================================
    # Test 2: tasks that need agents — should produce a plan
    # =============================================
    print("\n" + "=" * 60)
    print("Test 2: Agent tasks (expect a plan with agents)")
    print("=" * 60)

    agent_questions = [
        "Create a feed-ad campaign for a Marina Bay hotel targeting Chinese tourists",
        "Analyze the performance of our last campaign and find anomalies",
    ]

    for q in agent_questions:
        print(f"\n🔍 Question: {q}")

        result = await orch.run(
            session_id="test-agent-001",
            user_input=q,
        )

        trace = result.get("agent_trace", [])
        has_direct_answer = any(
            t.get("action") == "direct_answer" for t in trace
        )
        has_agent_execution = any(
            t.get("action") == "execute" for t in trace
        )

        if has_agent_execution and not has_direct_answer:
            agents_called = [t["agent"] for t in trace if t.get("action") == "execute"]
            print(f"✅ PASS — Agents called: {agents_called}")
        elif has_direct_answer:
            print(f"❌ FAIL — Was direct answer (should have called agents)")
        else:
            print(f"⚠️  UNCLEAR — Check trace")

        msg = result.get("message", "")
        preview = msg[:200] + "..." if len(msg) > 200 else msg
        print(f"📝 Answer: {preview}")

    # =============================================
    # Summary
    # =============================================
    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)
    print("""
Expected:
  Test 1: all 3 questions → PASS (direct answer)
  Test 2: both tasks → PASS (agents called)

If Test 1 FAILs:
  → check the General Knowledge section of ORCHESTRATOR_SYSTEM

If Test 2 FAILs:
  → check the _should_execute_or_direct_answer logic
""")


asyncio.run(test())