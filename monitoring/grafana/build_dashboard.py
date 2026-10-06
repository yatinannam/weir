"""Builds monitoring/grafana/dashboards/weir.json (Phase 4 addendum §4). Stdlib only.

This file is the source of truth for every panel: edit it, then run
    python monitoring/grafana/build_dashboard.py
The test suite checks the JSON is up to date and runs every Postgres query as the read-only user.
Only these Grafana macros are used: $__timeFilter(col), $__timeGroupAlias(col, '1h'); variables: $config, $namespace.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards" / "weir.json"
PG = {"type": "grafana-postgresql-datasource", "uid": "weir-pg"}
PROM = {"type": "prometheus", "uid": "weir-prom"}
F = "$__timeFilter(ts) and config_label in ($config) and namespace in ($namespace)"
LOG = "from weir.request_log where " + F

_id = 0


def _next_id() -> int:
    global _id
    _id += 1
    return _id


def _sql(sql: str, fmt: str = "table") -> dict:
    return {"refId": "A", "datasource": PG, "rawSql": " ".join(sql.split()), "format": fmt, "rawQuery": True,
            "editorMode": "code"}


def _prom(expr: str, legend: str = "", instant: bool = False) -> dict:
    return {"refId": "A", "datasource": PROM, "expr": expr, "legendFormat": legend, "range": not instant,
            "instant": instant}


def panel(kind: str, title: str, target: dict, x: int, y: int, w: int, h: int, unit: str = "short",
          decimals: int | None = None, options: dict | None = None, overrides: list | None = None,
          time_from: str | None = None, description: str = "") -> dict:
    defaults: dict = {"unit": unit}
    if decimals is not None:
        defaults["decimals"] = decimals
    p = {"id": _next_id(), "type": kind, "title": title, "description": description, "datasource": target["datasource"],
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": [target],
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options or {}}
    if time_from:
        p["timeFrom"] = time_from
    return p


def row(title: str, y: int) -> dict:
    return {"id": _next_id(), "type": "row", "title": title, "collapsed": False, "panels": [],
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}}


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none",
        "graphMode": "none", "textMode": "value", "justifyMode": "center"}


def stat(title: str, sql: str, x: int, y: int, unit: str = "short", decimals: int | None = None,
         description: str = "") -> dict:
    return panel("stat", title, _sql(sql), x, y, 3, 4, unit, decimals, STAT, description=description)


def percent_columns(*names: str) -> list:
    return [{"matcher": {"id": "byName", "options": n},
             "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}]} for n in names]


def build() -> dict:
    global _id
    _id = 0
    panels = [
        row("Headline", 0),
        stat("Requests", f"select count(*) as \"Requests\" {LOG}", 0, 1),
        stat("Cost per 1,000 requests",
             f"select coalesce(1000 * sum(cost_usd) / nullif(count(*), 0), 0) as \"Cost per 1,000\" {LOG}",
             3, 1, "currencyUSD", 4, "List prices; actual spend is $0 on free tiers"),
        stat("Estimated savings",
             f"select coalesce(sum(counterfactual_cost_usd - cost_usd), 0) as \"Saved\" {LOG}", 6, 1,
             "currencyUSD", 4, "Counterfactual (no cache, always the large model) minus actual cost"),
        stat("Savings %",
             f"select coalesce(1 - sum(cost_usd) / nullif(sum(counterfactual_cost_usd), 0), 0) as \"Saved\" {LOG}",
             9, 1, "percentunit", 1),
        stat("Cache hit rate", f"select coalesce(avg((cache_status = 'hit')::int), 0) as \"Hit rate\" {LOG}",
             12, 1, "percentunit", 1),
        stat("Routed small",
             f"select coalesce(sum((route = 'small')::int)::float / nullif(sum((cache_status <> 'hit')::int), 0), 0)"
             f" as \"Routed small\" {LOG}", 15, 1, "percentunit", 1, "Small-model requests / non-hit requests"),
        stat("Escalation rate",
             f"select coalesce(sum(escalated::int)::float / nullif(sum((route = 'small')::int), 0), 0)"
             f" as \"Escalated\" {LOG}", 18, 1, "percentunit", 1, "Escalated / small-routed requests"),
        stat("Error rate", f"select coalesce(avg((status <> 'ok')::int), 0) as \"Errors\" {LOG}",
             21, 1, "percentunit", 2),

        row("Comparison", 5),
        panel("table", "Configuration comparison", _sql(f"""
            select config_label as "Configuration", count(*) as "Requests",
                   avg((cache_status = 'hit')::int) as "Cache hit rate",
                   sum((route = 'small')::int)::float / nullif(sum((cache_status <> 'hit')::int), 0) as "Routed small",
                   1000 * sum(cost_usd) / count(*) as "Cost per 1,000",
                   percentile_cont(0.5) within group (order by latency_total_ms) as "p50 (ms)",
                   percentile_cont(0.95) within group (order by latency_total_ms) as "p95 (ms)",
                   1 - sum(cost_usd) / nullif(sum(counterfactual_cost_usd), 0) as "Saved",
                   avg((status <> 'ok')::int) as "Error rate"
            {LOG} group by config_label order by "Cost per 1,000" desc"""), 0, 6, 24, 9,
              overrides=percent_columns("Cache hit rate", "Routed small", "Saved", "Error rate")
              + [{"matcher": {"id": "byName", "options": "Cost per 1,000"},
                  "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 4}]}],
              description="The four-way ablation, live from the request log"),

        row("Where requests go", 15),
        panel("timeseries", "Route mix over time", _sql(f"""
            select $__timeGroupAlias(ts, '1h'), sum((cache_status = 'hit')::int) as "cache hit",
                   sum((cache_status <> 'hit' and route = 'small')::int) as "small model",
                   sum((cache_status <> 'hit' and route = 'large')::int) as "large model"
            {LOG} group by 1 order by 1""", "time_series"), 0, 16, 12, 8,
              options={"legend": {"displayMode": "list", "placement": "bottom"}}),
        panel("piechart", "Cache status",
              _sql(f"select cache_status as \"Status\", count(*) as \"Requests\" {LOG} group by 1 order by 1"),
              12, 16, 6, 8, options={"reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": ""},
                                     "legend": {"displayMode": "list", "placement": "right"}}),
        panel("table", "Top bypass reasons", _sql(f"""
            select coalesce(bypass_reason, '(none)') as "Bypass reason", count(*) as "Requests"
            {LOG} and cache_status = 'bypass' group by 1 order by 2 desc limit 10"""), 18, 16, 6, 8),

        row("Latency", 24),
        panel("table", "Latency by path", _sql(f"""
            select case when cache_status = 'hit' then 'cache hit' else route || ' model' end as "Path",
                   count(*) as "Requests",
                   percentile_cont(0.5) within group (order by latency_total_ms) as "p50 (ms)",
                   percentile_cont(0.95) within group (order by latency_total_ms) as "p95 (ms)",
                   percentile_cont(0.99) within group (order by latency_total_ms) as "p99 (ms)"
            {LOG} and status = 'ok' and (cache_status = 'hit' or route in ('small', 'large'))
            group by 1 order by 1"""), 0, 25, 12, 7),
        panel("bargauge", "Average time per stage (non-hit requests)", _sql(f"""
            select avg(latency_embed_ms) as "Embed", avg(latency_cache_ms) as "Cache lookup",
                   avg(latency_retrieval_ms) as "Retrieval", avg(latency_llm_ms) as "Model"
            {LOG} and cache_status <> 'hit'"""), 12, 25, 12, 7, "ms", 0,
              options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                       "orientation": "horizontal", "displayMode": "basic"}),

        row("Cache and router health", 32),
        panel("barchart", "Similarity: hits and near misses", _sql(f"""
            select to_char(floor(similarity * 100) / 100, 'FM0.00') as "Similarity",
                   sum((cache_status = 'hit')::int) as "hits", sum((cache_status <> 'hit')::int) as "near misses"
            {LOG} and similarity >= 0.80 group by 1 order by 1"""), 0, 33, 12, 8,
              options={"xField": "Similarity", "stacking": "normal",
                       "legend": {"displayMode": "list", "placement": "bottom"}},
              description="Is the 0.90 threshold sensible? Near misses are lookups that scored 0.80+ but didn't hit"),
        panel("table", "Route reasons", _sql(f"""
            select route_reason as "Route reason", count(*) as "Requests"
            {LOG} and route_reason is not null group by 1 order by 2 desc"""), 12, 33, 6, 8),
        panel("table", "Grounding results", _sql(f"""
            select case when grounding_passed then 'passed' else coalesce(grounding_reason, 'failed') end
                   as "Grounding", count(*) as "Requests"
            {LOG} and grounding_passed is not null group by 1 order by 2 desc"""), 18, 33, 6, 8),
        panel("timeseries", "Fallbacks and escalations over time", _sql(f"""
            select $__timeGroupAlias(ts, '1h'), sum((route_reason like '%+fallback')::int) as "fallbacks",
                   sum(escalated::int) as "escalations"
            {LOG} group by 1 order by 1""", "time_series"), 0, 41, 18, 7),
        panel("stat", "Thumbs down", _sql("""
            select count(*) as "Thumbs down" from weir.feedback f join weir.request_log r on r.request_id = f.request_id
            where f.rating = -1 and $__timeFilter(r.ts) and r.config_label in ($config)
              and r.namespace in ($namespace)"""), 18, 41, 6, 7, options=STAT),

        row("Live (Prometheus, last 15 minutes)", 48),
        panel("timeseries", "Requests per second", _prom("sum(rate(weir_requests_total[1m]))", "requests/s"),
              0, 49, 6, 7, "reqps", time_from="15m"),
        panel("timeseries", "Live p95 latency",
              _prom("histogram_quantile(0.95, sum by (le) (rate(weir_request_latency_seconds_bucket[5m])))", "p95"),
              6, 49, 6, 7, "s", time_from="15m"),
        panel("timeseries", "Errors per second",
              _prom('sum(rate(weir_requests_total{status!="ok"}[1m])) or vector(0)', "errors/s"),
              12, 49, 6, 7, "reqps", time_from="15m"),
        panel("stat", "Lost work",
              _prom('sum({__name__=~"weir_(log_rows|cache_jobs)_(dropped|failed)_total"}) or vector(0)', instant=True),
              18, 49, 3, 7, options=STAT,
              description="Dropped or failed log rows and cache jobs since Weir started"),
        panel("stat", "Firing alerts", _prom('sum(ALERTS{alertstate="firing"}) or vector(0)', instant=True),
              21, 49, 3, 7, options=STAT),
        panel("stat", "Running configuration", _prom("weir_info", "{{config_label}}", instant=True), 0, 56, 6, 4,
              options={**STAT, "textMode": "name"}),
        {"id": _next_id(), "type": "text", "title": "Answer quality", "gridPos": {"x": 6, "y": 56, "w": 18, "h": 4},
         "options": {"mode": "markdown", "content":
                     "Answer quality (judge score, key facts) is measured by the eval suite, not live traffic. "
                     "See [docs/results/summary.md](https://github.com/yatinannam/weir/blob/main/docs/results/"
                     "summary.md) for the four-way ablation with quality."}},
    ]
    variables = [
        {"name": "config", "label": "Configuration", "type": "query", "datasource": PG, "refresh": 2,
         "query": "select distinct config_label from weir.request_log where $__timeFilter(ts) "
                  "and config_label is not null order by 1",
         "definition": "config_label values", "multi": True, "includeAll": True,
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}},
        {"name": "namespace", "label": "Namespace", "type": "query", "datasource": PG, "refresh": 2,
         "query": "select distinct namespace from weir.request_log where $__timeFilter(ts) order by 1",
         "definition": "namespace values", "multi": True, "includeAll": True,
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}},
    ]
    return {"uid": "weir", "title": "Weir", "tags": ["weir"], "timezone": "browser", "editable": False,
            "schemaVersion": 39, "refresh": "5m", "time": {"from": "now-30d", "to": "now"},
            "templating": {"list": variables}, "panels": panels}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
