"""k6 output parsing and per-run calculations (Phase 5 addendum §5). Pure functions only."""
import json
import math
import re
from collections.abc import Iterable
from datetime import datetime

PATHS = ("all", "hit", "small", "large")
FAILURE_LABELS = ["normal", "normal", "large_rate_limited", "normal_2", "small_timeout", "db_delay", "recovery"]
_FRACTION = re.compile(r"(\.\d{6})\d+")


def parse_summary(data: dict) -> dict:
    m = data["metrics"]

    def trend(name: str) -> dict | None:
        v = m.get(name, {}).get("values")
        if not v or not v.get("count"):
            return None
        return {"p50": v["med"], "p95": v["p(95)"], "p99": v["p(99)"], "count": int(v["count"])}

    return {
        "requests": int(m["iterations"]["values"]["count"]),
        "achieved_rate": m["iterations"]["values"]["rate"],
        "error_rate": m.get("errors", {}).get("values", {}).get("rate", 0.0),
        "dropped": int(m.get("dropped_iterations", {}).get("values", {}).get("count", 0)),
        "latency": {p: trend(f"latency_{p}") for p in PATHS},
    }


def _ts_ms(text: str) -> int:
    text = _FRACTION.sub(r"\1", text.replace("Z", "+00:00"))
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def compact_points(lines: Iterable[str]) -> list[tuple[int, str, float, int]]:
    out = []
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("type") != "Point":
            continue
        data, tags = rec["data"], rec["data"].get("tags", {})
        if tags.get("scenario") != "traffic":
            continue
        if rec["metric"] == "http_req_duration":
            out.append((_ts_ms(data["time"]), "req", float(data["value"]), int(tags.get("status") or 0)))
        elif rec["metric"] == "dropped_iterations":
            out.append((_ts_ms(data["time"]), "drop", float(data["value"]), 0))
    return sorted(out)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def window_stats(points, start_ms: int, end_ms: int) -> dict:
    reqs = [(v, st) for t, k, v, st in points if k == "req" and start_ms <= t < end_ms]
    dropped = sum(v for t, k, v, _ in points if k == "drop" and start_ms <= t < end_ms)
    errors = sum(1 for _, st in reqs if st != 200)
    seconds = max((end_ms - start_ms) / 1000, 1e-9)
    return {"n": len(reqs), "p95": percentile([v for v, _ in reqs], 95), "errors": errors,
            "error_rate": errors / len(reqs) if reqs else 0.0, "dropped": int(dropped),
            "achieved_rate": len(reqs) / seconds}


def ramp_steps(points, t0_ms: int, rates: list[int], step_s: int) -> list[dict]:
    return [{"rate": r, **window_stats(points, t0_ms + i * step_s * 1000, t0_ms + (i + 1) * step_s * 1000)}
            for i, r in enumerate(rates)]


def _step_ok(step: dict, budget_ms: float, max_error: float, min_achieved: float) -> bool:
    return (step["p95"] is not None and step["p95"] <= budget_ms and step["error_rate"] <= max_error
            and step["achieved_rate"] >= min_achieved * step["rate"])


def ramp_max_rate(steps: list[dict], budget_ms: float = 2000, max_error: float = 0.01,
                  min_achieved: float = 0.95) -> int | None:
    best = None
    for step in steps:  # stop at the first failing step: a lucky later step doesn't count
        if not _step_ok(step, budget_ms, max_error, min_achieved):
            break
        best = step["rate"]
    return best


def spike_recovery_s(points, burst_end_ms: int, budget_ms: float = 2000, window_s: int = 10) -> float | None:
    last = max((t for t, k, _, _ in points if k == "req"), default=burst_end_ms)
    start = burst_end_ms
    while start + window_s * 1000 <= last + 1:
        w = window_stats(points, start, start + window_s * 1000)
        if w["n"] and w["p95"] <= budget_ms:
            return (start + window_s * 1000 - burst_end_ms) / 1000
        start += 1000
    return None


def failure_phases(points, t0_ms: int, phase_s: int) -> list[dict]:
    return [{"label": label, **window_stats(points, t0_ms + i * phase_s * 1000, t0_ms + (i + 1) * phase_s * 1000)}
            for i, label in enumerate(FAILURE_LABELS)]
