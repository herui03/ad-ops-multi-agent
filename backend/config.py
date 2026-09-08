from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Groq LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_model_fast: str = "llama-3.1-8b-instant"

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # Redis (optional)
    redis_url: str = ""

    # Ad platform API (leave blank to run in mock mode)
    ad_platform_app_id: str = ""
    ad_platform_app_secret: str = ""
    ad_platform_access_token: str = ""

    # LangSmith
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "ad-ops-agent"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"  # ignore unknown env vars
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
