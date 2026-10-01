import pytest
from pydantic import ValidationError

from weir.config import deep_merge, load_config

from .conftest import CONFIGS


def test_repo_config_loads():
    cfg = load_config(CONFIGS / "weir.yaml")
    assert cfg.config_label == "dev"
    assert cfg.model_for("large") == "openai/gpt-oss-120b"
    assert cfg.model_for("small") == "openai/gpt-oss-20b"
    assert cfg.is_sensitive("weir-general/en/staff") is True
    assert cfg.is_sensitive("weir-general/en/public") is False
    assert cfg.is_sensitive("unknown/ns") is True  # unknown namespaces are treated as sensitive


def test_baseline_overlay_forces_large():
    cfg = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / "baseline.yaml")
    assert cfg.config_label == "baseline"
    assert cfg.kill_switch.force_large is True
    assert cfg.rag.retrieve_k == 4  # untouched keys survive the merge


def test_deep_merge_nested():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}}) == {"a": {"b": 1, "c": 3}}


def test_unknown_key_rejected(tmp_path):
    bad = tmp_path / "w.yaml"
    bad.write_text((CONFIGS / "weir.yaml").read_text(encoding="utf-8") + "\ntypo_key: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad)
