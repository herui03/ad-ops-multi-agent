"""Model providers and the bounded call policy.

* DemoProvider (default): deterministic, rule-based generators. No language model, no network,
  no credentials. Every run it serves is labelled "demo" in the API and the UI.
* GroqProvider (opt-in, LLM_PROVIDER=groq + GROQ_API_KEY): calls Groq's OpenAI-compatible chat
  endpoint with JSON mode. The key is read from a SecretStr and never logged; provider errors are
  redacted before they are stored or returned.
* FaultInjectingProvider: demo/test wrapper that makes a chosen role time out, fail, or return
  malformed / wrong-schema output for the first N attempts. The counter is durable (SQLite), so
  the behaviour survives a restart and Recover can be demonstrated.

`invoke_structured` is the only way agents call a provider: per-attempt timeout, bounded
attempts, JSON parsing, and schema validation. Failures raise StepFailed with a stable code.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable

import httpx
from pydantic import BaseModel, ValidationError

from backend.config import Settings
from backend.contracts import validation_summary


class ProviderError(Exception):
    """Transport or upstream failure."""


class ProviderTimeout(ProviderError):
    pass


class StepFailed(Exception):
    def __init__(self, code: str, message: str, *, attempts: int = 0, retryable: bool = True,
                 step_id: str | None = None, agent: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.attempts = code, message, attempts
        self.retryable, self.step_id, self.agent = retryable, step_id, agent


_SECRET_PATTERNS = [re.compile(p) for p in (r"gsk_[A-Za-z0-9]{8,}", r"sk-[A-Za-z0-9_\-]{8,}",
                                             r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}")]


def redact(text: str, secrets: list[str] | None = None, limit: int = 300) -> str:
    out = str(text)
    for s in secrets or []:
        if s:
            out = out.replace(s, "[REDACTED]")
    for p in _SECRET_PATTERNS:
        out = p.sub("[REDACTED]", out)
    return out[:limit]


class Provider:
    name = "base"
    mode = "demo"
    label = ""

    def complete(self, role: str, system: str, payload: dict) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def secrets(self) -> list[str]:
        return []


class DemoProvider(Provider):
    name = "deterministic-demo"
    mode = "demo"
    label = "DEMO — deterministic rule-based provider (no language model, no network, no credentials)"

    def complete(self, role: str, system: str, payload: dict) -> str:
        from backend.demo_generators import generate
        return json.dumps(generate(role, payload))


class GroqProvider(Provider):
    name = "groq"
    mode = "live"

    def __init__(self, settings: Settings):
        self._key = settings.groq_api_key.get_secret_value()
        if not self._key:
            raise RuntimeError("LLM_PROVIDER=groq requires GROQ_API_KEY")
        self._model = settings.groq_model
        self._url = settings.groq_base_url.rstrip("/") + "/chat/completions"
        self._timeout = settings.provider_timeout_s
        self.label = f"LIVE — Groq {self._model} (network call per agent step)"

    def secrets(self) -> list[str]:
        return [self._key]

    def complete(self, role: str, system: str, payload: dict) -> str:
        body = {"model": self._model, "temperature": 0.2, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
        try:
            r = httpx.post(self._url, json=body, timeout=self._timeout,
                           headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as e:
            raise ProviderTimeout("provider request timed out") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"transport error: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"provider returned HTTP {r.status_code}")
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderError("unexpected provider response envelope") from e


class FaultInjectingProvider(Provider):
    def __init__(self, inner: Provider, fault: dict, counter: Callable[[str], int], timeout_s: float):
        self.inner, self.fault, self.counter, self.timeout_s = inner, fault, counter, timeout_s
        self.name, self.mode, self.label = inner.name, inner.mode, inner.label

    def secrets(self) -> list[str]:
        return self.inner.secrets()

    def complete(self, role: str, system: str, payload: dict) -> str:
        if role == self.fault.get("agent") and self.counter(role) <= int(self.fault.get("fail_attempts", 1)):
            kind = self.fault["kind"]
            if kind == "provider_error":
                raise ProviderError("simulated provider outage (injected fault)")
            if kind == "timeout":
                time.sleep(self.timeout_s + 0.3)
                return "{}"
            if kind == "malformed_json":
                return '{"campaign_name": "unterminated'
            if kind == "wrong_schema":
                return json.dumps(["valid", "json", "but", "not", "an", "object"])
        return self.inner.complete(role, system, payload)


def build_provider(settings: Settings) -> Provider:
    return DemoProvider() if settings.is_demo else GroqProvider(settings)


_call_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="provider-call")


def invoke_structured(provider: Provider, role: str, system: str, payload: dict, contract: type[BaseModel], *,
                      timeout_s: float, max_attempts: int,
                      on_attempt: Callable[[int, str, str], None] | None = None,
                      semantic_check: Callable[[BaseModel], None] | None = None) -> tuple[BaseModel, int]:
    """Call the provider with a per-attempt timeout and at most `max_attempts` attempts.

    Returns (validated_output, attempts_used) or raises StepFailed. A timed-out call cannot be
    killed in Python; it is abandoned (the live provider's own HTTP timeout ends it).
    """
    code, message = "provider_error", "no attempt made"
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_pool.submit(provider.complete, role, system, payload).result(timeout=timeout_s)
        except (FutureTimeout, ProviderTimeout):
            code, message = "timeout", f"no response within {timeout_s:g}s"
        except ProviderError as e:
            code, message = "provider_error", redact(str(e), provider.secrets())
        except Exception as e:  # noqa: BLE001 - never leak arbitrary exception text
            code, message = "provider_error", f"unexpected {type(e).__name__}"
        else:
            try:
                data: Any = json.loads(raw)
            except (TypeError, ValueError):
                code, message = "malformed_output", "response is not valid JSON"
            else:
                if not isinstance(data, dict):
                    code, message = "schema_violation", f"top-level JSON must be an object, got {type(data).__name__}"
                else:
                    try:
                        obj = contract.model_validate(data)
                        if semantic_check:
                            semantic_check(obj)
                        if on_attempt:
                            on_attempt(attempt, "ok", "")
                        return obj, attempt
                    except ValidationError as e:
                        code, message = "schema_violation", validation_summary(e)
                    except ValueError as e:
                        code, message = "schema_violation", redact(str(e), provider.secrets())
        if on_attempt:
            on_attempt(attempt, code, message)
        if attempt < max_attempts:
            time.sleep(0.05 * attempt)
    raise StepFailed(code, message, attempts=max_attempts, retryable=True)
