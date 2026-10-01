import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Tenant:
    name: str
    namespaces: frozenset[str]
    admin: bool = False

    def allows(self, namespace: str) -> bool:
        return namespace in self.namespaces


class TenantRegistry:
    def __init__(self, keyed: list[tuple[str, Tenant]]):
        self._keyed = keyed

    @classmethod
    def from_yaml(cls, path: Path, env: Mapping[str, str]) -> "TenantRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        keyed: list[tuple[str, Tenant]] = []
        for t in data["tenants"]:
            key = env.get(t["key_env"], "")
            if not key:
                raise ValueError(f"tenant '{t['name']}': environment variable {t['key_env']} is empty")
            tenant = Tenant(t["name"], frozenset(t.get("namespaces", [])), bool(t.get("admin", False)))
            keyed.append((key, tenant))
        keys = [k for k, _ in keyed]
        if len(set(keys)) != len(keys):
            raise ValueError("two tenants share the same API key")
        return cls(keyed)

    def authenticate(self, key: str | None) -> Tenant | None:
        if not key:
            return None
        found = None
        for candidate, tenant in self._keyed:  # compare against all keys: constant-time per key
            if hmac.compare_digest(candidate.encode(), key.encode()):
                found = tenant
        return found
