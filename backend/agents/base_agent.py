from __future__ import annotations
import json
import time
from typing import Any

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import get_settings
from backend.memory.shared_memory import get_memory


class BaseAgent:
    agent_name: str = "base"
    system_prompt: str = ""
    use_fast_model: bool = False

    def __init__(self):
        settings = get_settings()
        model = settings.groq_model_fast if self.use_fast_model else settings.groq_model
        self.llm = ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=0.3,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.memory = get_memory()

    async def run(
        self, session_id: str, task: str, context: dict[str, Any] = None
    ) -> dict[str, Any]:
        start_time = time.time()
        context = context or {}

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self._build_prompt(task, context)),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            raw = response.content
            try:
                output = json.loads(raw)
            except json.JSONDecodeError:
                output = {"raw_response": raw, "_parse_error": True}
        except Exception as e:
            output = {"error": str(e), "_failed": True}

        duration_ms = int((time.time() - start_time) * 1000)
        self.memory.save_agent_output(session_id, self.agent_name, output)

        return {
            "agent": self.agent_name,
            "output": output,
            "duration_ms": duration_ms,
            "success": "_failed" not in output,
        }

    def _build_prompt(self, task: str, context: dict[str, Any]) -> str:
        parts = [f"## Task\n{task}"]

        if context:
            clean = {k: v for k, v in context.items() if k != "session_id"}
            if clean:
                parts.append(
                    f"\n## Context\n```json\n"
                    f"{json.dumps(clean, ensure_ascii=False, indent=2)}\n```"
                )

        client_name = context.get("client_name", "")
        if client_name:
            profile = self.memory.get_client_profile(client_name)
            if profile:
                parts.append(
                    f"\n## Client Historical Profile\n```json\n"
                    f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n```"
                )

        return "\n".join(parts)