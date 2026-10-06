"""The Grafana dashboard's queries (Phase 4 addendum §6). Every Postgres panel query runs as weir_reader against a
seeded database and must return rows; Prometheus expressions may only use metrics Weir really exposes."""
import json
import re
import runpy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from prometheus_client import CollectorRegistry, generate_latest

from weir.metrics.prometheus import LossCollector, WeirMetrics

from .conftest import REPO

DASHBOARD = REPO / "monitoring" / "grafana" / "dashboards" / "weir.json"
BUILDER = REPO / "monitoring" / "grafana" / "build_dashboard.py"
ALERTS = REPO / "monitoring" / "prometheus" / "alerts.yml"


def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _postgres_queries() -> list[tuple[str, str]]:
    d = _dashboard()
    out = [(f"variable {v['name']}", v["query"]) for v in d["templating"]["list"]
           if v.get("datasource", {}).get("uid") == "weir-pg"]
    for panel in d["panels"]:
        for t in panel.get("targets", []):
            if t.get("datasource", {}).get("uid") == "weir-pg":
                out.append((panel["title"], t["rawSql"]))
    return out


def _prometheus_exprs() -> list[str]:
    return [t["expr"] for p in _dashboard()["panels"] for t in p.get("targets", [])
            if t.get("datasource", {}).get("uid") == "weir-prom"]


def expand(sql: str) -> str:
    sql = re.sub(r"\$__timeFilter\(([\w.]+)\)", r"\1 between '2000-01-01' and '2100-01-01'", sql)
    sql = re.sub(r"\$__timeGroupAlias\(([\w.]+),\s*'[^']*'\)", r"date_trunc('hour', \1) as time", sql)
    sql = sql.replace("$config", "'full','baseline','dev'").replace("$namespace", "'weir-general/en/public'")
    assert "$" not in sql, f"unexpanded macro or variable in: {sql}"
    return sql


PUB = "weir-general/en/public"


@pytest.fixture
def seeded_reader(migrated_db_url):
    """Rows covering every panel: hit, small, large, bypass, escalation, fallback, error, a near miss, a Phase-1
    style row with NULL router columns (Review Focus 3), and a thumbs-down."""
    now = datetime.now(UTC)
    rows = [
        # (config, cache_status, route, status, similarity, route_reason, grounding_passed, grounding_reason,
        #  escalated, bypass_reason, cost, counterfactual, latency)
        ("full", "hit", "none", "ok", 0.97, None, None, None, False, None, "0", "0.0004", 20),
        ("full", "miss", "small", "ok", 0.85, "simple", True, None, False, None, "0.0002", "0.0004", 700),
        ("full", "miss", "small", "ok", 0.60, "simple", True, None, True, None, "0.0006", "0.0004", 1500),
        ("full", "miss", "large", "ok", None, "default_large+fallback", True, None, False, None, "0.0004", "0.0004",
         900),
        ("full", "bypass", "large", "ok", None, "clinical", False, "low_overlap", False, "clinical", "0.0004",
         "0.0004", 800),
        ("full", "miss", "large", "error", None, "default_large", None, None, False, None, "0", "0", 3000),
        ("baseline", "bypass", "large", "ok", None, "kill_switch", True, None, False, "cache_disabled", "0.0004",
         "0.0004", 750),
        ("dev", "miss", "large", "ok", 0.40, None, None, None, False, None, "0.0004", "0.0004", 650),
    ]
    ids = []
    with psycopg.connect(migrated_db_url) as conn:
        for i, (cfg, cs, route, status, sim, rr, gp, gr, esc, br, cost, cf, lat) in enumerate(rows):
            rid = uuid4()
            ids.append(rid)
            conn.execute(
                "insert into weir.request_log (request_id, ts, namespace, cache_status, bypass_reason, similarity, "
                "route, route_reason, escalated, model_calls, grounding_passed, grounding_reason, latency_total_ms, "
                "latency_embed_ms, latency_cache_ms, latency_retrieval_ms, latency_llm_ms, cost_usd, "
                "counterfactual_cost_usd, status, query_hash, config_label) values "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (rid, now - timedelta(hours=i), PUB, cs, br, sim, route, rr, esc, 0 if cs == "hit" else 1, gp, gr,
                 lat, 10, 2, 30, None if cs == "hit" else lat - 50, Decimal(cost), Decimal(cf), status, "h" * 64, cfg))
        conn.execute("insert into weir.feedback (request_id, rating) values (%s, -1)", (ids[1],))
    with psycopg.connect(migrated_db_url.replace("weir:weir@", "weir_reader:weir_reader@", 1)) as reader:
        yield reader


@pytest.mark.db
@pytest.mark.parametrize(("title", "sql"), _postgres_queries())
def test_every_postgres_query_runs_as_weir_reader_and_returns_rows(seeded_reader, title, sql):
    rows = seeded_reader.execute(expand(sql)).fetchall()
    assert rows, f"panel '{title}' returned no rows on the seeded data"


def test_dashboard_json_matches_the_builder():
    built = runpy.run_path(str(BUILDER))["build"]()
    assert built == _dashboard(), "weir.json is stale: run `python monitoring/grafana/build_dashboard.py`"


def test_dashboard_basics():
    d = _dashboard()
    assert d["uid"] == "weir" and d["time"] == {"from": "now-30d", "to": "now"}
    assert [v["name"] for v in d["templating"]["list"]] == ["config", "namespace"]
    assert all(v["multi"] and v["includeAll"] for v in d["templating"]["list"])
    titles = [p["title"] for p in d["panels"]]
    for required in ("Estimated savings", "Configuration comparison", "Similarity: hits and near misses",
                     "Latency by path", "Route mix over time", "Firing alerts", "Answer quality"):
        assert required in titles, required
    assert len(titles) == len(set(titles))


def test_prometheus_queries_only_use_metrics_weir_exposes():
    class Q:
        dropped = failed = 0

    registry = CollectorRegistry()
    WeirMetrics(registry, "dev")
    registry.register(LossCollector({"log_rows": Q(), "cache_jobs": Q()}))
    exposed = set(re.findall(r"^# TYPE (\w+)", generate_latest(registry).decode(), re.M))
    exposed |= {f"{n}_total" for n in exposed} | {f"{n}_bucket" for n in exposed} | {"up", "ALERTS"}
    used = set()
    for text in [*_prometheus_exprs(), ALERTS.read_text(encoding="utf-8")]:
        used |= set(re.findall(r"\b(weir_\w+|up|ALERTS)\b", text))
    regex_names = {"weir_log_rows_dropped_total", "weir_log_rows_failed_total",
                   "weir_cache_jobs_dropped_total", "weir_cache_jobs_failed_total"}
    assert regex_names <= exposed
    unknown = {n for n in used if n not in exposed}
    assert not unknown, f"queries reference metrics Weir doesn't expose: {sorted(unknown)}"
