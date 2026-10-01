from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql://weir:weir@localhost:5432/weir"
    groq_api_key: str = ""
    llm_mode: Literal["groq", "stub"] = "groq"
    stub_latency_ms: int = 800
    groq_timeout_s: float = 20.0
    max_completion_tokens: int = 700
    reasoning_effort: str | None = "low"  # gpt-oss models: low | medium | high
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str | None = None
    retrieve_k: int = 4
    chunk_max_tokens: int = 250
