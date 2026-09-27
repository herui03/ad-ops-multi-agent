"""Offline tests of the live provider's wiring (fake HTTP; no network, no real key).

These prove request shape, secret handling and error mapping. They say nothing about live model
quality; that needs tests/live with a real key.
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.config import Settings
from backend.contracts import InsightOutput
from backend.providers import GroqProvider, ProviderError, ProviderTimeout, StepFailed, invoke_structured

KEY = "gsk_" + "k" * 24


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def provider(timeout=5.0):
    return GroqProvider(Settings(_env_file=None, llm_provider="groq", groq_api_key=KEY, provider_timeout_s=timeout))


def test_request_shape_and_envelope(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        seen.update(url=url, body=json, timeout=timeout, headers=headers)
        return FakeResp(200, {"choices": [{"message": {"content": '{"ok": 1}'}}]})
    monkeypatch.setattr(httpx, "post", fake_post)
    p = provider()
    assert p.complete("insight", "sys", {"request": "x"}) == '{"ok": 1}'
    assert seen["url"].endswith("/chat/completions") and seen["timeout"] == 5.0
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["headers"]["Authorization"] == f"Bearer {KEY}"
    assert KEY not in repr(p.__dict__.get("label"))


@pytest.mark.parametrize("resp,exc", [(FakeResp(401, {"error": KEY}), ProviderError),
                                      (FakeResp(200, {"unexpected": True}), ProviderError)])
def test_http_errors_map_to_provider_error_without_body(monkeypatch, resp, exc):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: resp)
    with pytest.raises(exc) as e:
        provider().complete("insight", "sys", {})
    assert KEY not in str(e.value)


def test_timeout_maps_and_step_fails_bounded(monkeypatch):
    def boom(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(ProviderTimeout):
        provider().complete("insight", "sys", {})
    with pytest.raises(StepFailed) as e:
        invoke_structured(provider(), "insight", "sys", {}, InsightOutput, timeout_s=1, max_attempts=2)
    assert e.value.code == "timeout" and e.value.attempts == 2


def test_error_messages_are_redacted(monkeypatch):
    def leak(*a, **k):
        raise ProviderError(f"upstream said Authorization: Bearer {KEY}")
    p = provider()
    monkeypatch.setattr(p, "complete", leak)
    with pytest.raises(StepFailed) as e:
        invoke_structured(p, "insight", "sys", {}, InsightOutput, timeout_s=1, max_attempts=1)
    assert KEY not in e.value.message and "[REDACTED]" in e.value.message
