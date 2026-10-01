from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagConfig(_Strict):
    base_url: str
    timeout_seconds: float = 30.0
    retrieve_k: int = 4


class RouterConfig(_Strict):
    small_model: str
    large_model: str


class CacheConfig(_Strict):
    enabled: bool = False


class KillSwitch(_Strict):
    force_large: bool = False
    disable_cache: bool = False


class NamespaceConfig(_Strict):
    sensitive: bool = False


class WeirConfig(_Strict):
    config_label: str
    rag: RagConfig
    router: RouterConfig
    cache: CacheConfig = CacheConfig()
    kill_switch: KillSwitch = KillSwitch()
    namespaces: dict[str, NamespaceConfig] = {}

    def is_sensitive(self, namespace: str) -> bool:
        ns = self.namespaces.get(namespace)
        return True if ns is None else ns.sensitive  # unknown namespace: be careful

    def model_for(self, tier: Literal["small", "large"]) -> str:
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
