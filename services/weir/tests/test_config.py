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


def test_phase2_config_fields():
    cfg = load_config(CONFIGS / "weir.yaml")
    assert cfg.cache.threshold == 0.90 and cfg.cache.candidates == 3  # D30: from the threshold sweep
    assert cfg.cache.embed_model == "BAAI/bge-small-en-v1.5" and cfg.cache.ttl_hours == 24
    assert cfg.rag.info_refresh_seconds == 30
    assert cfg.cache_enabled_for("weir-general/en/public") is True
    assert cfg.cache_enabled_for("unknown/ns") is False
    assert cfg.ttl_hours_for("weir-general/en/staff") == 24
    assert "now" in cfg.bypass.time_sensitive and "diagnos*" in cfg.bypass.clinical
    assert cfg.bypass.followup_max_words == 6


def test_cache_only_overlay():
    cfg = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / "cache_only.yaml")
    assert cfg.config_label == "cache_only"
    assert cfg.cache.enabled is True and cfg.kill_switch.force_large is True


def test_namespace_ttl_override(tmp_path):
    import yaml

    data = yaml.safe_load((CONFIGS / "weir.yaml").read_text(encoding="utf-8"))
    data["namespaces"]["weir-general/en/staff"]["cache"]["ttl_hours"] = 2
    path = tmp_path / "w.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert load_config(path).ttl_hours_for("weir-general/en/staff") == 2


def test_phase3_router_and_grounding_config():
    cfg = load_config(CONFIGS / "weir.yaml")
    r = cfg.router
    assert r.enabled is True and r.default_tier == "large" and r.max_model_calls == 2
    assert 0 < r.low_confidence < r.high_confidence <= 1 and r.short_query_tokens > 0
    assert {"why", "compare", "pros and cons"} <= set(r.reasoning_words)
    assert 0 < cfg.grounding.min_overlap <= 1


def test_max_model_calls_is_capped_at_two(tmp_path):
    bad = tmp_path / "w.yaml"
    text = (CONFIGS / "weir.yaml").read_text(encoding="utf-8").replace("max_model_calls: 2", "max_model_calls: 3")
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad)


@pytest.mark.parametrize(("overlay", "cache_on", "router_on", "tier", "force_large"), [
    ("baseline", False, True, "large", True),
    ("cache_only", True, True, "large", True),
    ("small_only", False, False, "small", False),
    ("router_only", False, True, "large", False),
    ("full", True, True, "large", False),
])
def test_ablation_overlays(overlay, cache_on, router_on, tier, force_large):
    cfg = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / f"{overlay}.yaml")
    assert cfg.config_label == overlay
    assert cfg.cache.enabled is cache_on and cfg.router.enabled is router_on
    assert cfg.router.default_tier == tier and cfg.kill_switch.force_large is force_large


def test_phase3_tuned_values():  # D37: from the offline router simulation (docs/results/router-tuning.md)
    cfg = load_config(CONFIGS / "weir.yaml")
    assert (cfg.router.short_query_tokens, cfg.router.high_confidence, cfg.router.low_confidence) == (16, 0.86, 0.50)
    assert cfg.grounding.min_overlap == 0.3  # D39: 0.6 kept good large answers out of the cache
