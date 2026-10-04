"""Read Weir's grounding results for a report's requests from weir.request_log (Phase 3 addendum §7.2)."""
import psycopg

SQL = ("select request_id::text as request_id, model, route_reason, grounding_passed, grounding_reason, "
       "grounding_overlap from weir.request_log where request_id = any(%s::uuid[])")


def fetch_grounding(db_url: str, request_ids: list[str]) -> list[dict]:
    with psycopg.connect(db_url) as conn:
        cur = conn.execute(SQL, (request_ids,))
        names = [d.name for d in cur.description]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def attach(results: list[dict], log_rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Grounding rows keyed by question id, plus the ids whose request has no log row (yet)."""
    by_request = {r["request_id"]: r for r in log_rows}
    rows, missing = [], []
    for r in results:
        if r.get("status_code") != 200:
            continue
        found = by_request.get(r["meta"]["request_id"])
        if found is None:
            missing.append(r["id"])
        else:
            rows.append({"id": r["id"], **found})
    return rows, missing
