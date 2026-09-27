"""Agent specification and the single code path every specialist agent runs through."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentSpec:
    name: str
    system_prompt: str
    contract: type[BaseModel]
    # which upstream agents' outputs this agent may read (only those listed as plan dependencies are passed)
    reads: tuple[str, ...] = ()
    # extra context builder (e.g. retrieved sources for compliance); must be deterministic
    extra_context: Callable[[dict], dict] | None = None
    # semantic checks beyond the schema (e.g. citations must resolve); raise ValueError to reject
    semantic_check: Callable[[BaseModel, dict], None] | None = None
    description: str = field(default="")
