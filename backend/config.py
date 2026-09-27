"""Runtime settings.

Defaults give a credential-free, network-free demo: the deterministic provider, local SQLite
files under ./data, and conservative limits. The live provider is opt-in (LLM_PROVIDER=groq
plus GROQ_API_KEY); the key is held as a SecretStr so it never appears in repr() or logs.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Provider: "demo" (deterministic, offline, default) or "groq" (live, opt-in)
    llm_provider: str = "demo"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Durable state (two SQLite files: the app store and the LangGraph checkpointer)
    data_dir: Path = ROOT / "data"

    # Reliability limits
    provider_timeout_s: float = 20.0
    provider_max_attempts: int = 2          # per agent step, per drive of the graph
    max_recoveries: int = 3                 # explicit Recover calls per run
    max_active_runs: int = 4                # queued + running jobs before 429
    worker_threads: int = 2

    # Input limits
    max_request_chars: int = 2000
    max_comment_chars: int = 500
    max_ws_message_bytes: int = 4096

    # Gate policy
    high_spend_threshold: float = 100_000
    hard_budget_cap: float = 500_000

    # Demo-only switches (ignored unless llm_provider == "demo")
    demo_crash_point: str = ""              # "before_commit" | "after_commit": os._exit once, for recovery drills

    frontend_url: str = "http://localhost:5173"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def store_path(self) -> Path:
        return self.data_dir / "adops.db"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.db"

    @property
    def is_demo(self) -> bool:
        return self.llm_provider.strip().lower() != "groq"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
