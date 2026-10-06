"""Live check (Phase 4 addendum §7): run every dashboard panel through Grafana's query API and report empty ones.

Usage (stack up with --profile monitoring):
    GRAFANA_ADMIN_PASSWORD=... python monitoring/check_panels.py
Exit code 1 if any panel is empty for "All". Per-configuration results are printed: cache panels are legitimately
empty for configurations with the cache off (baseline, router_only).
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

GRAFANA = "http://127.0.0.1:3000"
DASHBOARD = json.loads((Path(__file__).resolve().parent / "grafana" / "dashboards" / "weir.json")
                       .read_text(encoding="utf-8"))
AUTH = "Basic " + base64.b64encode(f"admin:{os.environ.get('GRAFANA_ADMIN_PASSWORD') or 'admin'}".encode()).decode()


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(GRAFANA + path, json.dumps(body).encode(),
                                 {"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _quote(values: list[str]) -> str:
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


def rows_for(target: dict, configs: list[str], namespaces: list[str]) -> int:
    q = {"refId": "A", "datasource": target["datasource"]}
    if "rawSql" in target:
        q |= {"rawSql": target["rawSql"].replace("$config", _quote(configs)).replace("$namespace", _quote(namespaces)),
              "format": target["format"], "rawQuery": True}
        span = ("now-30d", "now")
    else:
        q |= {"expr": target["expr"], "instant": True}
        span = ("now-15m", "now")
    frames = _post("/api/ds/query", {"queries": [q], "from": span[0], "to": span[1]})["results"]["A"].get("frames", [])
    return sum(len(f["data"]["values"][0]) if f["data"]["values"] else 0 for f in frames)


def distinct(sql: str) -> list[str]:
    res = _post("/api/ds/query", {"queries": [{"refId": "A", "datasource": {"uid": "weir-pg"}, "rawSql": sql,
                                               "format": "table", "rawQuery": True}], "from": "now-30d", "to": "now"})
    return [v for f in res["results"]["A"]["frames"] for v in f["data"]["values"][0]]


def main() -> int:
    configs = distinct("select distinct config_label from weir.request_log where config_label is not null order by 1")
    namespaces = distinct("select distinct namespace from weir.request_log order by 1")
    views = {"All": configs, **{c: [c] for c in ("baseline", "cache_only", "router_only", "full") if c in configs}}
    panels = [p for p in DASHBOARD["panels"] if p.get("targets")]
    empty_all = []
    print(f"{'panel':48s} " + " ".join(f"{v:>11s}" for v in views))
    for p in panels:
        counts = [rows_for(p["targets"][0], cfgs, namespaces) for cfgs in views.values()]
        print(f"{p['title'][:48]:48s} " + " ".join(f"{c:>11d}" for c in counts))
        if counts[0] == 0:
            empty_all.append(p["title"])
    print("\nempty for All:", empty_all or "none")
    return 1 if empty_all else 0


if __name__ == "__main__":
    sys.exit(main())
