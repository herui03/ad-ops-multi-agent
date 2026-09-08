from __future__ import annotations
import json
import time
from typing import Any, Optional
from datetime import datetime

from backend.config import get_settings


class SharedMemory:

    def __init__(self):
        self._store: dict[str, Any] = {}
        self._ttl: dict[str, float] = {}
        self._redis = None
        self._init_redis()

    def _init_redis(self):
        settings = get_settings()
        if settings.redis_url:
            try:
                import redis as redis_lib
                self._redis = redis_lib.from_url(
                    settings.redis_url, decode_responses=True
                )
                self._redis.ping()
                print("Connected to Redis")
            except Exception as e:
                print(f"Redis unavailable ({e}), using in-memory store")
                self._redis = None

    def set(self, key: str, value: Any, ttl_seconds: int = 0) -> None:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if self._redis:
            if ttl_seconds > 0:
                self._redis.setex(key, ttl_seconds, serialized)
            else:
                self._redis.set(key, serialized)
        else:
            self._store[key] = serialized
            if ttl_seconds > 0:
                self._ttl[key] = time.time() + ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if self._redis:
            raw = self._redis.get(key)
        else:
            if key in self._ttl and time.time() > self._ttl[key]:
                del self._store[key]
                del self._ttl[key]
                return None
            raw = self._store.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def delete(self, key: str) -> None:
        if self._redis:
            self._redis.delete(key)
        else:
            self._store.pop(key, None)
            self._ttl.pop(key, None)

    def save_session(self, session_id: str, messages: list[dict]) -> None:
        self.set(f"session:{session_id}:messages", messages, ttl_seconds=7200)

    def get_session(self, session_id: str) -> list[dict]:
        return self.get(f"session:{session_id}:messages") or []

    def append_message(self, session_id: str, message: dict) -> None:
        messages = self.get_session(session_id)
        messages.append(message)
        self.save_session(session_id, messages)

    def save_agent_output(
        self, session_id: str, agent_name: str, output: dict
    ) -> None:
        self.set(
            f"working:{session_id}:{agent_name}",
            {"output": output, "timestamp": datetime.utcnow().isoformat()},
            ttl_seconds=3600,
        )

    def get_agent_output(self, session_id: str, agent_name: str) -> Optional[dict]:
        data = self.get(f"working:{session_id}:{agent_name}")
        return data["output"] if data else None

    def get_all_agent_outputs(self, session_id: str) -> dict[str, Any]:
        agents = ["insight", "strategy", "creative", "analytics", "compliance", "ci"]
        outputs = {}
        for agent in agents:
            result = self.get_agent_output(session_id, agent)
            if result is not None:
                outputs[agent] = result
        return outputs

    def save_client_profile(self, client_name: str, profile: dict) -> None:
        self.set(f"client:{client_name}", profile)

    def get_client_profile(self, client_name: str) -> Optional[dict]:
        return self.get(f"client:{client_name}")

    def save_case(self, case_id: str, case_data: dict) -> None:
        self.set(f"case:{case_id}", case_data)
        index = self.get("case:index") or []
        if case_id not in index:
            index.append(case_id)
            self.set("case:index", index)

    def search_cases(self, industry: str = "", keyword: str = "") -> list[dict]:
        index = self.get("case:index") or []
        results = []
        for case_id in index:
            case = self.get(f"case:{case_id}")
            if case is None:
                continue
            case_str = json.dumps(case, ensure_ascii=False).lower()
            if industry.lower() in case_str or keyword.lower() in case_str:
                results.append(case)
        return results

    def save_approval(self, approval: dict) -> None:
        approval_id = approval["approval_id"]
        self.set(f"approval:{approval_id}", approval, ttl_seconds=86400)
        session_id = approval.get("session_id", "")
        pending = self.get(f"approvals:{session_id}") or []
        pending.append(approval_id)
        self.set(f"approvals:{session_id}", pending, ttl_seconds=86400)

    def get_approval(self, approval_id: str) -> Optional[dict]:
        return self.get(f"approval:{approval_id}")

    def get_pending_approvals(self, session_id: str) -> list[dict]:
        pending_ids = self.get(f"approvals:{session_id}") or []
        approvals = []
        for aid in pending_ids:
            a = self.get(f"approval:{aid}")
            if a and a.get("status") == "pending":
                approvals.append(a)
        return approvals

    def resolve_approval(
        self, approval_id: str, decision: str, feedback: str = ""
    ) -> None:
        approval = self.get_approval(approval_id)
        if approval:
            approval["status"] = decision
            approval["human_feedback"] = feedback
            approval["resolved_at"] = datetime.utcnow().isoformat()
            self.set(f"approval:{approval_id}", approval, ttl_seconds=86400)


_memory_instance: Optional[SharedMemory] = None


def get_memory() -> SharedMemory:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = SharedMemory()
    return _memory_instance
