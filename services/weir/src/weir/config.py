from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["small", "large"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagConfig(_Strict):
    base_url: str
    timeout_seconds: float = 30.0
    retrieve_k: int = 4
    info_refresh_seconds: float = 30.0


class RouterConfig(_Strict):
    small_model: str
    large_model: str
    enabled: bool = False
    default_tier: Tier = "large"            # the tier used when the router is disabled
    short_query_tokens: int = 20            # tuned offline (addendum §7.3)
    high_confidence: float = 0.75           # tuned offline
    low_confidence: float = 0.40            # tuned offline
    max_model_calls: int = Field(2, ge=1, le=2)
    reasoning_words: list[str] = []


class GroundingConfig(_Strict):
    min_overlap: float = 0.5                # share of answer content words found in the cited chunks


class CacheConfig(_Strict):
    enabled: bool = False
    threshold: float = 0.92
    candidates: int = 3
    ttl_hours: float = 24.0
    min_retrieval_score: float = 0.30
    cleanup_interval_minutes: float = 60.0
    embed_model: str = "BAAI/bge-small-en-v1.5"
    lookup_timeout_ms: int = 500  # give up on the cache (bypass) rather than stall the request


class BypassConfig(_Strict):
    time_sensitive: list[str] = []
    clinical: list[str] = []          # a trailing "*" means prefix match ("diagnos*")
    followup_prefixes: list[str] = []
    followup_pronouns: list[str] = []
    followup_max_words: int = 6


class KillSwitch(_Strict):
    force_large: bool = False
    disable_cache: bool = False


class NamespaceCacheConfig(_Strict):
    enabled: bool = True
    ttl_hours: float | None = None


class NamespaceConfig(_Strict):
    sensitive: bool = False
    cache: NamespaceCacheConfig = NamespaceCacheConfig()


class WeirConfig(_Strict):
    config_label: str
    rag: RagConfig
    router: RouterConfig
    grounding: GroundingConfig = GroundingConfig()
    cache: CacheConfig = CacheConfig()
    kill_switch: KillSwitch = KillSwitch()
    bypass: BypassConfig = BypassConfig()
    namespaces: dict[str, NamespaceConfig] = {}

    def is_sensitive(self, namespace: str) -> bool:
        ns = self.namespaces.get(namespace)
        return True if ns is None else ns.sensitive  # unknown namespace: be careful

    def cache_enabled_for(self, namespace: str) -> bool:
        ns = self.namespaces.get(namespace)
        return ns is not None and ns.cache.enabled  # unknown namespace: never cache

    def ttl_hours_for(self, namespace: str) -> float:
        ns = self.namespaces.get(namespace)
        return ns.cache.ttl_hours if ns is not None and ns.cache.ttl_hours is not None else self.cache.ttl_hours

    def model_for(self, tier: Tier) -> str:
        return self.router.small_model if tier == "small" else self.router.large_model


def deep_merge(base: dict, over: dict) -> dict:
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path, overlay: Path | None = None) -> WeirConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if overlay is not None:
        data = deep_merge(data, yaml.safe_load(overlay.read_text(encoding="utf-8")) or {})
    return WeirConfig.model_validate(data)
