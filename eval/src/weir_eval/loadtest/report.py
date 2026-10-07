"""Load-test report (Phase 5 addendum §6): aggregate repeats, evaluate the checks honestly, render markdown."""
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import median

from .k6 import ramp_max_rate

CONFIGS = ("baseline", "cache_only", "router_only", "full")
CONTAINERS = ("weir-weir-1", "weir-hospital-rag-1", "weir-postgres-1")
MODEL_FAULTS = ("large_rate_limited", "small_timeout")
BUDGET_MS = 2000
_MEM = re.compile(r"([\d.]+)\s*([KMG]i?B)")
_UNITS = {"KiB": 1 / 1024, "KB": 1 / 1000, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1000}


def load_runs(root: Path) -> list[dict]:
    """Every run under a results folder, except the copies set aside as <name>.stalled (not results)."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*/summary.json"))
            if not p.parent.name.endswith(".stalled")]


def _name(r: dict) -> str:
    s = r["spec"]
    return f"{s['scenario']}-{s['config']}-r{s['repeat']}"


def power_by_run(runs: list[dict], log_text: str) -> dict[str, str | None]:
    """'battery' or 'AC' for each run: the last power change (UTC) logged before the run started."""
    changes = []
    for line in log_text.splitlines():
        if line.strip() and not line.startswith("#"):
            ts, state = line.split()[:2]
            changes.append((datetime.fromisoformat(ts.replace("Z", "+00:00")), "AC" if state == "Online" else "battery"))
    out = {}
    for r in runs:
        started = datetime.fromisoformat(r["started"])
        before = [state for t, state in changes if t <= started]
        out[_name(r)] = before[-1] if before else None
    return out


def power_line(by_run: dict[str, str | None]) -> str:
    battery = sum(1 for v in by_run.values() if v == "battery")
    ac = sum(1 for v in by_run.values() if v == "AC")
    if not battery and not ac:
        return ""
    return (f"- Power: {battery} run{'' if battery == 1 else 's'} on battery, {ac} on AC power "
            "(power log in the results folder).")


def median_range(values) -> tuple | None:
    vals = [v for v in values if v is not None]
    return (median(vals), min(vals), max(vals)) if vals else None


def _broken_switch(r: dict) -> bool:
    return r["spec"]["scenario"] == "failure" and bool((r.get("k6") or {}).get("chaos_failed"))


def _valid(r: dict) -> bool:
    """A run counts unless it stalled (the machine slept, so its timings are not real) or a fault switch failed
    (a phase measured the wrong fault)."""
    return bool(r.get("k6")) and not r.get("stalled") and not _broken_switch(r)


def _sel(runs, scenario, config=None):
    return [r for r in runs if r["spec"]["scenario"] == scenario and (config is None or r["spec"]["config"] == config)
            and _valid(r)]


def _p95(r):
    return r["k6"]["latency"]["all"]["p95"] if r["k6"]["latency"]["all"] else None


def _mem_mib(text: str) -> float:
    m = _MEM.match(text)
    return float(m.group(1)) * _UNITS[m.group(2)] if m else 0.0


SOAK_WINDOW_S = 300                                     # first and last 5 minutes, by sample time


def _median_or_none(values):
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None


def soak_stats(run: dict) -> dict:
    """Memory and connections in the first vs the last 5 minutes, chosen by time so a gap in the samples
    (docker stats failing) leaves a window empty instead of silently shifting it."""
    res = run.get("resources", [])
    if len(res) < 2:
        return {}
    t0, t1 = res[0]["t"], res[-1]["t"]
    head = [s for s in res if s["t"] < t0 + SOAK_WINDOW_S]
    tail = [s for s in res if s["t"] > t1 - SOAK_WINDOW_S]

    def mem(samples):
        values = [_mem_mib(s["weir-weir-1"]["mem"]) or None for s in samples if "weir-weir-1" in s]
        if 2 * len([v for v in values if v]) < len(samples):   # samples must cover the window, not touch its edge
            return None
        return _median_or_none(values)

    first, last = mem(head), mem(tail)
    return {"mem_first_mib": first, "mem_last_mib": last,
            "mem_growth": (last - first) / first if first and last is not None else None,
            "conn_first": _median_or_none(s.get("db_connections") for s in head),
            "conn_last": _median_or_none(s.get("db_connections") for s in tail)}


def _met_fault(ph: dict) -> int:
    """Requests that reached the faulted model: Weir falls back from it, or (if the fallback fails) errors."""
    log = ph.get("log", {})
    return log.get("fallbacks", 0) + log.get("errors", 0)


def _model_fault_check(fails: list[dict]) -> dict:
    name = "0 errors during model faults"
    phs = [ph for r in fails for ph in r["phases"] if ph["label"] in MODEL_FAULTS]
    # D54: a fault no request met proves nothing, so every fault phase of every run must show requests meeting it
    untested = [f"{_name(r)} {ph['label']}" for r in fails for ph in r["phases"]
                if ph["label"] in MODEL_FAULTS and not _met_fault(ph)]
    if untested:
        return {"name": name, "passed": None,
                "detail": f"not tested: no request reached the faulted model in {', '.join(untested)}"}
    errors = sum(ph["errors"] for ph in phs)
    met = sum(_met_fault(ph) for ph in phs)
    fallbacks = sum(ph.get("log", {}).get("fallbacks", 0) for ph in phs)
    return {"name": name, "passed": errors == 0,
            "detail": f"{errors} errors across {len(fails)} runs; {met} requests met a faulted model and "
                      f"{fallbacks} of them fell back"}


def _cache_outage_check(fails: list[dict]) -> dict:
    name = "cache outage invisible"
    db = [ph for r in fails for ph in r["phases"] if ph["label"] == "db_delay"]
    if not all(ph.get("log", {}).get("cache_errors", 0) for ph in db):   # the outage must be shown to have happened
        return {"name": name, "passed": None, "detail": "not tested: a run's database-delay phase had no cache bypasses"}
    errors = sum(ph["errors"] for ph in db)
    p95 = median_range(ph["p95"] for ph in db)
    over = sum(1 for ph in db if ph["p95"] is not None and ph["p95"] > BUDGET_MS)
    bypasses = sum(ph["log"]["cache_errors"] for ph in db)
    return {"name": name, "passed": errors == 0 and p95 is not None and p95[0] <= BUDGET_MS,
            "detail": f"{errors} errors; median p95 {p95[0]:.0f} ms ({p95[1]:.0f}–{p95[2]:.0f}), "
                      f"{over} of {len(db)} runs over 2 s; {bypasses} cache bypasses" if p95 else f"{errors} errors"}


def evaluate_checks(runs: list[dict]) -> list[dict]:
    checks = []
    base = median_range(_p95(r) for r in _sel(runs, "cold", "baseline"))
    warm = median_range(_p95(r) for r in _sel(runs, "warm", "full"))
    if base and warm:
        cut = 1 - warm[0] / base[0]
        checks.append({"name": "warm p95 at least 30% below baseline", "passed": cut >= 0.30,
                       "detail": f"full warm p95 {warm[0]:.0f} ms vs baseline {base[0]:.0f} ms ({cut:.0%} lower)"})
    else:
        checks.append({"name": "warm p95 at least 30% below baseline", "passed": None, "detail": "no runs yet"})
    fails = _sel(runs, "failure", "full")
    if fails:
        checks += [_model_fault_check(fails), _cache_outage_check(fails)]
    else:
        checks += [{"name": "0 errors during model faults", "passed": None, "detail": "no runs yet"},
                   {"name": "cache outage invisible", "passed": None, "detail": "no runs yet"}]
    soaks = _sel(runs, "soak", "full")
    if soaks:
        s, st = soaks[0], soak_stats(soaks[0])
        soak = s.get("soak") or {}
        drift = soak["last_p95"] / soak["first_p95"] - 1 if soak.get("first_p95") and soak.get("last_p95") else None
        growth = st.get("mem_growth")
        if growth is None or drift is None:      # half the evidence missing is not a pass
            parts = [f"p95 drift {drift:+.0%}" if drift is not None else "no p95 drift",
                     "memory missing in the first or last 5 min" if growth is None else f"memory {growth:+.0%}"]
            checks.append({"name": "no leaks over the soak", "passed": None,
                           "detail": "incomplete: " + "; ".join(parts)})
        else:
            checks.append({"name": "no leaks over the soak", "passed": growth < 0.10 and drift < 0.20,
                           "detail": f"memory {growth:+.0%}, p95 drift {drift:+.0%}"})
    else:
        checks.append({"name": "no leaks over the soak", "passed": None, "detail": "no runs yet"})
    lost = sum(r.get("lost_work", 0) for r in runs)
    checks.append({"name": "no lost background work", "passed": lost == 0 if runs else None,
                   "detail": f"{lost} across {len(runs)} runs" if runs else "no runs yet"})
    return checks


def _fmt(mr, unit=" ms"):
    return "–" if mr is None else (f"{mr[0]:.0f}{unit}" if mr[1] == mr[2] else f"{mr[0]:.0f}{unit} ({mr[1]:.0f}–{mr[2]:.0f})")


def _pct(mr, digits=1):
    return "–" if mr is None else f"{mr[0]:.{digits}%}"


def _table(runs, scenario):
    rows = []
    for c in CONFIGS:
        sel = _sel(runs, scenario, c)
        if not sel:
            continue
        lat = lambda key, sel=sel: median_range(r["k6"]["latency"]["all"][key] for r in sel)  # noqa: E731
        cost = median_range(1000 * r["request_log"]["cost"] / max(r["request_log"]["n"], 1) for r in sel)
        hit = median_range(r["request_log"]["hit_rate"] for r in sel)
        err = median_range(r["k6"]["error_rate"] for r in sel)
        rows.append(f"| {c} | {len(sel)} | {_fmt(lat('p50'))} | {_fmt(lat('p95'))} | {_fmt(lat('p99'))} | "
                    f"{_pct(hit)} | ${cost[0]:.4f} | {_pct(err, 2)} |")
    if not rows:
        return ["no runs yet"]
    return ["| Configuration | Runs | p50 | p95 | p99 | Hit rate | Cost / 1k | Errors |",
            "| :-- | --: | --: | --: | --: | --: | --: | --: |", *rows]


def _cpu_table(runs):
    rows = []
    for c in CONFIGS:
        sel = _sel(runs, "cold", c)
        cells = []
        for name in CONTAINERS:
            per_run = [median(s[name]["cpu"] for s in r.get("resources", []) if name in s)
                       for r in sel if any(name in s for s in r.get("resources", []))]
            cells.append(_fmt(median_range(per_run), "%"))
        if sel:
            rows.append(f"| {c} | " + " | ".join(cells) + " |")
    if not rows:
        return []
    return ["", "Container CPU during the cold runs (median of the 5 s samples; 100% = one core):", "",
            "| Configuration | weir | hospital-rag | postgres |", "| :-- | --: | --: | --: |", *rows]


def _runs(n: int, kind: str) -> str:
    return f"{n} {kind} run" if n == 1 else f"{n} {kind} runs"


def _excluded(runs) -> list[str]:
    slept = sum(1 for r in runs if r.get("stalled"))
    broken = sum(1 for r in runs if _broken_switch(r))
    parts = []
    if slept:
        parts.append(f"{_runs(slept, 'stalled')} (the machine slept mid-run, so the timings are not real)")
    if broken:
        parts.append(f"{_runs(broken, 'failure')} whose fault switch failed (a phase measured the wrong fault)")
    return ["- Excluded: " + "; ".join(parts) + "."] if parts else []


def render(runs: list[dict], meta: dict) -> str:
    out = [f"# Load test results ({meta['date']})", "", "## Setup", "",
           f"- Machine: {meta['machine']}. k6 runs on the same laptop (a recorded limitation).",
           "- Versions: k6 0.54.0, Toxiproxy 2.9.0, Postgres 16 with pgvector 0.8, Python 3.12; "
           "embeddings fastembed bge-small.",
           f"- Workload: 3,000 requests, Zipf (seed 11), repeat rate {meta['repeat_rate']:.1%}, constant arrival rate.",
           "- Stub model: lognormal per model (small 553 / 830 ms, large 748 / 1,429 ms median / p95), seeded (D49).",
           "- Failure runs: 1 in 3 requests skip the cache, so the model faults always meet real traffic (D54).",
           "- Latency budget: p95 2 s (D50). Medians of repeats, with the range in brackets.",
           *([meta["power"]] if meta.get("power") else []), *_excluded(runs), "",
           "## Cold cache: four-way (10 req/s, 5 min)", "", *_table(runs, "cold"), "",
           "## Warm cache (10 req/s, 5 min)", "", *_table(runs, "warm"), "", "## Latency per path", ""]
    rows = []
    for scenario in ("cold", "warm"):
        for c in CONFIGS:
            sel = _sel(runs, scenario, c)
            if sel:
                cells = [_fmt(median_range((r["k6"]["latency"][p] or {}).get("p95") for r in sel))
                         for p in ("hit", "small", "large")]
                rows.append(f"| {scenario} | {c} | " + " | ".join(cells) + " |")
    out += (["| Scenario | Configuration | Hit p95 | Small p95 | Large p95 |", "| :-- | :-- | --: | --: | --: |", *rows]
            if rows else ["no runs yet"])
    out += ["", "## Gateway overhead", ""]
    ov = [r for r in runs if _valid(r) and r.get("request_log", {}).get("overhead_mean") is not None
          and r["spec"]["config"] in ("cache_only", "full")]
    out += ([f"Embed + cache lookup inside Weir: mean {_fmt(median_range(r['request_log']['overhead_mean'] for r in ov))}, "
             f"p95 {_fmt(median_range(r['request_log']['overhead_p95'] for r in ov))} (cache configurations, all runs)."]
            if ov else ["no runs yet"])
    out += _cpu_table(runs)
    out += ["", "## Ramp", ""]
    ramp_rows = []
    for c in ("full", "baseline"):
        sel = [r for r in _sel(runs, "ramp", c) if r.get("steps")]
        if sel:
            best = median_range(ramp_max_rate(r["steps"]) for r in sel)
            ramp_rows.append(f"| {c} | {len(sel)} | {_fmt(best, ' req/s')} |")
    out += (["![p95 vs request rate](loadtest-ramp.png)", "",
             "| Configuration | Runs | Highest rate within budget |", "| :-- | --: | --: |", *ramp_rows]
            if ramp_rows else ["no runs yet"])
    out += ["", "## Spike", ""]
    sp = _sel(runs, "spike", "full")
    if sp:
        recovery = median_range(r.get("recovery_s") for r in sp)
        recovered = ("the 10-second p95 never left the 2 s budget, so there was nothing to recover from"
                     if recovery and recovery[2] == 0 else
                     f"recovery {_fmt(recovery, ' s')} from the end of the burst until the 10-second p95 is back "
                     "under 2 s (0 = it never left)")
        out.append(f"A 60 req/s burst for 30 s on a 5 req/s base: peak 10-second p95 "
                   f"{_fmt(median_range(r.get('peak_p95') for r in sp))}; {recovered}; overall p95 "
                   f"{_fmt(median_range(_p95(r) for r in sp))}.")
    else:
        out.append("no runs yet")
    out += ["", "## Soak", ""]
    so = _sel(runs, "soak", "full")
    if so:
        st, soak = soak_stats(so[0]), so[0].get("soak") or {}
        p95 = lambda v: "–" if v is None else f"{v:.1f}"  # noqa: E731
        first_mem, last_mem = st.get("mem_first_mib"), st.get("mem_last_mib")
        memory = (f"weir memory {first_mem:.0f} -> {last_mem:.0f} MiB" if first_mem and last_mem is not None else
                  f"weir memory {first_mem:.0f} MiB at the start, but no memory samples in the last 5 min "
                  "(docker stats returned nothing)" if first_mem else "no weir memory samples")
        out.append(f"30 min at 10 req/s, first vs last 5 min: p95 {p95(soak.get('first_p95'))} -> "
                   f"{p95(soak.get('last_p95'))} ms; {memory}; "
                   f"open database connections {st.get('conn_first')} -> {st.get('conn_last')}; "
                   f"errors {so[0]['k6']['error_rate']:.2%}.")
    else:
        out.append("no runs yet")
    out += ["", "## Failure injection", ""]
    fl = _sel(runs, "failure", "full")
    if fl:
        out += ["| Phase | Requests | Model path | Errors | p95 | Fallbacks | Cache bypasses |",
                "| :-- | --: | --: | --: | --: | --: | --: |"]
        for i, label in enumerate(fl[0]["phases"]):
            phs = [r["phases"][i] for r in fl]
            log = lambda key, phs=phs: sum(p.get("log", {}).get(key, 0) for p in phs)  # noqa: E731
            out.append(f"| {label['label']} | {sum(p['n'] for p in phs)} | {log('model_path')} | "
                       f"{sum(p['errors'] for p in phs)} | {_fmt(median_range(p['p95'] for p in phs))} | "
                       f"{log('fallbacks')} | {log('cache_errors')} |")
        out += ["", f"Totals across {len(fl)} runs; p95 is the median of the runs. Requests and errors are counted "
                    "by k6 when each request finishes; model path, fallbacks and cache bypasses come from Weir's "
                    "request log by when each request started."]
    else:
        out.append("no runs yet")
    out += ["", "## Checks", "", "| Check | Result | Detail |", "| :-- | :-: | :-- |"]
    for c in evaluate_checks(runs):
        result = {True: "pass", False: "FAIL", None: "not run"}[c["passed"]]
        out.append(f"| {c['name']} | {result} | {c['detail']} |")
    out += ["", "## Limitations", "",
            "- The model is a stub with realistic timing, not Groq: answers are real retrieval, generation is simulated.",
            "- k6, Weir, hospital-rag and Postgres share one laptop; one Weir process (no horizontal scaling).",
            "- Rates are modest by design (a free-tier, single-machine project); the ramp finds this machine's limit.",
            "- CPU readings include ONNX Runtime's embedding threads spin-waiting between requests, so a container "
            "that embeds (weir with a cache, hospital-rag) reads far above the work it does."]
    return "\n".join(out) + "\n"


def ramp_chart(runs: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    for c, color in (("full", "#2b6cb0"), ("baseline", "#c05621")):
        sel = [r for r in _sel(runs, "ramp", c) if r.get("steps")]
        if not sel:
            continue
        rates = [s["rate"] for s in sel[0]["steps"]]
        for r in sel:   # every repeat, faintly, so a collapse the median hides stays visible
            pts = [(s["rate"], s["p95"]) for s in r["steps"] if s["p95"]]
            ax.plot([x for x, _ in pts], [y for _, y in pts], color=color, alpha=0.3, linewidth=1)
        p95 = [median([r["steps"][i]["p95"] for r in sel if i < len(r["steps"]) and r["steps"][i]["p95"]] or [0])
               for i in range(len(rates))]
        ax.plot(rates, p95, marker="o", color=color, label=f"{c} (median of {len(sel)}; faint: each run)")
    ax.axhline(BUDGET_MS, color="grey", linestyle=":", label="2 s budget")
    ax.set_yscale("log")   # hits (~15 ms) and collapses (~60 s) on one chart
    ax.set_xlabel("request rate (req/s)")
    ax.set_ylabel("p95 latency (ms, log scale)")
    ax.set_title("p95 vs request rate")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
