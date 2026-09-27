"""Live provider check. Skipped (reported as NOT RUN) unless GROQ_API_KEY is set.

Run: LLM_PROVIDER=groq GROQ_API_KEY=... pytest tests/live -m live -rs
It checks that live model output passes the same contracts and still stops at the gate. It does
NOT measure answer quality, and a pass here is one sample, not an accuracy figure.
"""
from __future__ import annotations

import os

import pytest

from backend.config import Settings
from tests.conftest import Harness

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.environ.get("GROQ_API_KEY"),
                                 reason="NOT RUN: GROQ_API_KEY not set; live LLM behaviour was not tested")]


def test_live_campaign_reaches_gate_or_fails_honestly(tmp_path):
    s = Settings(data_dir=tmp_path / "data", llm_provider="groq", provider_timeout_s=30)
    h = Harness(s)
    try:
        rid = h.create()
        d = h.detail(rid)
        assert d["provider_mode"] == "live"
        assert d["status"] in ("awaiting_approval", "failed", "completed")
        assert h.actions() == []            # never executes without an approval
        if d["status"] == "failed":
            assert d["error_code"] in ("timeout", "provider_error", "malformed_output", "schema_violation")
    finally:
        h.stop()
