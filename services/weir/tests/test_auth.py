import pytest

from weir.auth import TenantRegistry

from .conftest import CONFIGS

ENV = {"WEIR_KEY_PUBLIC": "pub-key", "WEIR_KEY_STAFF": "staff-key", "WEIR_KEY_ADMIN": "admin-key"}


def registry():
    return TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV)


def test_authenticate_maps_key_to_tenant():
    t = registry().authenticate("pub-key")
    assert t.name == "public-app"
    assert t.allows("weir-general/en/public") and not t.allows("weir-general/en/staff")
    assert registry().authenticate("admin-key").admin is True


def test_unknown_or_missing_key_is_none():
    assert registry().authenticate("nope") is None
    assert registry().authenticate(None) is None
    assert registry().authenticate("") is None


def test_missing_env_var_fails_fast():
    with pytest.raises(ValueError, match="WEIR_KEY_STAFF"):
        TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", {**ENV, "WEIR_KEY_STAFF": ""})


def test_duplicate_keys_rejected():
    with pytest.raises(ValueError, match="same API key"):
        TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", {**ENV, "WEIR_KEY_STAFF": "pub-key"})
