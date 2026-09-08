import pytest
from unittest.mock import patch


def test_insight_agent_config():
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        from backend.agents.insight_agent import InsightAgent
        agent = InsightAgent()
        assert agent.agent_name == "insight"
        assert "Insight" in agent.system_prompt


def test_compliance_uses_fast_model():
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        from backend.agents.compliance_agent import ComplianceAgent
        agent = ComplianceAgent()
        assert agent.use_fast_model is True


def test_anomaly_detection():
    from backend.tools.data_tools import detect_anomalies
    current = {"ctr": 0.005, "cpm": 80, "cvr": 0.01}
    benchmark = {"avg_ctr": 0.011, "avg_cpm": 42, "avg_cvr": 0.018}
    anomalies = detect_anomalies(current, benchmark)
    assert len(anomalies) > 0
    ctr_a = next((a for a in anomalies if a["metric"] == "CTR"), None)
    assert ctr_a is not None
    assert "below" in ctr_a["message"]
