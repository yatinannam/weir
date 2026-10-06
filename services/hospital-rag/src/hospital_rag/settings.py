from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql://weir:weir@127.0.0.1:5432/weir"
    groq_api_key: str = ""
    llm_mode: Literal["groq", "stub"] = "groq"
    stub_latency_ms: int = 800
    stub_timing: Literal["fixed", "realistic"] = "fixed"
    stub_seed: int = 7
    stub_small_model: str = "openai/gpt-oss-20b"
    stub_small_median_ms: float = 553     # fitted 2026-10-06 from 740 clean request-log rows (D49)
    stub_small_p95_ms: float = 830
    stub_large_model: str = "openai/gpt-oss-120b"
    stub_large_median_ms: float = 748
    stub_large_p95_ms: float = 1429
    groq_timeout_s: float = 20.0
    max_completion_tokens: int = 700
    reasoning_effort: str | None = "low"  # gpt-oss models: low | medium | high
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str | None = None
    retrieve_k: int = 4
    chunk_max_tokens: int = 250
