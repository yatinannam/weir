"""Offline router simulation and tuning (Phase 3 addendum §7.3). No model calls.

Every question has two measured answers: baseline v3 (large) and the small-model trial. For each rule setting,
Weir's own route() picks a tier per question:
- large -> the baseline answer
- small and the small answer's grounding passes -> the small answer
- small and it fails -> escalated: the baseline answer, paying for both calls
"""
import itertools
from dataclasses import asdict, dataclass
from statistics import mean

from weir.config import WeirConfig
from weir.router.features import Features
from weir.router.rules import route

from .dataset import EvalQuery
from .features import FEATURE_KEYS

GRID = {
    "short_query_tokens": [12, 16, 20, 25, 30, 40],
    # 0.60–0.95 in 0.01 steps (D37): the addendum's 0.60–0.85 left no passing setting, because an easy-looking
    # question the small model answers incompletely (q-036, top score 0.855) was routed small at every setting.
    "high_confidence": [round(0.60 + 0.01 * i, 2) for i in range(36)],
    "low_confidence": [0.30, 0.35, 0.40, 0.45, 0.50],
    "min_overlap": [0.3, 0.4, 0.5, 0.6, 0.7],
}
EPS = 1e-9
SPLITS = ("tune", "holdout", "all")


@dataclass(frozen=True)
class Row:
    id: str
    split: str
    features: Features
    base_judge: float
    base_facts: float
    base_cost: float
    small_judge: float | None     # None: no usable small answer (error or another model) -> always escalates
    small_facts: float | None
    small_cost: float
    small_reason: str | None      # grounding reason Weir logged for the small answer
    small_overlap: float | None


@dataclass(frozen=True)
class Setting:
    short_query_tokens: int
    high_confidence: float
    low_confidence: float
    min_overlap: float


def settings() -> list[Setting]:
    return [Setting(*values) for values in itertools.product(*GRID.values())]


def small_passes(row: Row, min_overlap: float) -> bool:
    return (row.small_judge is not None and row.small_reason in (None, "low_overlap")
            and row.small_overlap is not None and row.small_overlap >= min_overlap)


def _config_for(setting: Setting, cfg: WeirConfig) -> WeirConfig:
    router = cfg.router.model_copy(update={
        "enabled": True, "short_query_tokens": setting.short_query_tokens,
        "high_confidence": setting.high_confidence, "low_confidence": setting.low_confidence})
    kill = cfg.kill_switch.model_copy(update={"force_large": False})
    return cfg.model_copy(update={"router": router, "kill_switch": kill})


def simulate(rows: list[Row], setting: Setting, cfg: WeirConfig) -> list[dict]:
    rcfg = _config_for(setting, cfg)
    out = []
    for r in rows:
        tier, reason = route(r.features, rcfg)
        base = {"id": r.id, "split": r.split, "tier": tier, "reason": reason, "base_judge": r.base_judge,
                "base_facts": r.base_facts, "base_cost": r.base_cost}
        if tier == "large":
            out.append({**base, "escalated": False, "judge": r.base_judge, "facts": r.base_facts,
                        "cost": r.base_cost})
        elif small_passes(r, setting.min_overlap):
            out.append({**base, "escalated": False, "judge": r.small_judge, "facts": r.small_facts,
                        "cost": r.small_cost})
        else:
            out.append({**base, "escalated": True, "judge": r.base_judge, "facts": r.base_facts,
                        "cost": r.small_cost + r.base_cost})
    return out


def metrics(sim: list[dict]) -> dict:
    small = [s for s in sim if s["tier"] == "small"]
    return {
        "n": len(sim),
        "cost_per_1k": sum(s["cost"] for s in sim) / len(sim) * 1000,
        "base_cost_per_1k": sum(s["base_cost"] for s in sim) / len(sim) * 1000,
        "judge": mean(s["judge"] for s in sim),
        "base_judge": mean(s["base_judge"] for s in sim),
        "facts": mean(s["facts"] for s in sim),
        "base_facts": mean(s["base_facts"] for s in sim),
        "share_small": len(small) / len(sim),
        "escalation_rate": sum(s["escalated"] for s in small) / len(small) if small else 0.0,
        "small_route_judge": mean(s["judge"] for s in small) if small else None,
        "small_route_base_judge": mean(s["base_judge"] for s in small) if small else None,
    }


def meets_bar(m: dict) -> bool:
    """D33, no visible loss. A setting that routes nothing small is not a router (Review Focus 5)."""
    return (m["share_small"] > 0
            and m["cost_per_1k"] < m["base_cost_per_1k"] - EPS
            and m["judge"] >= m["base_judge"] - 0.1 - EPS
            and m["facts"] >= m["base_facts"] - EPS
            and m["small_route_judge"] >= m["small_route_base_judge"] - EPS)


def run_grid(rows: list[Row], cfg: WeirConfig) -> list[tuple[Setting, dict[str, dict]]]:
    results = []
    for setting in settings():
        sim = simulate(rows, setting, cfg)
        by_split: dict = {}
        for split in SPLITS:
            part = [s for s in sim if split == "all" or s["split"] == split]
            if part:
                by_split[split] = metrics(part)
        by_split["_sim"] = sim
        results.append((setting, by_split))
    return results


def choose(results: list[tuple[Setting, dict[str, dict]]]) -> tuple[Setting, dict] | None:
    """Lowest simulated cost on the tune split among settings meeting the bar there.
    Ties go to the more conservative setting."""
    passing = [(s, m) for s, m in results if "tune" in m and meets_bar(m["tune"])]
    if not passing:
        return None
    return min(passing, key=lambda sm: (round(sm[1]["tune"]["cost_per_1k"], 9), -sm[1]["tune"]["judge"],
                                        -sm[0].min_overlap, -sm[0].high_confidence, sm[0].short_query_tokens,
                                        -sm[0].low_confidence))


def build_rows(queries: list[EvalQuery], features: dict[str, dict], baseline: dict[str, dict],
               small: dict[str, dict], grounding: dict[str, dict], small_model: str) -> list[Row]:
    rows = []
    for q in queries:
        b = baseline[q.id]
        if b.get("status_code") != 200 or b.get("judge_score") is None:
            raise ValueError(f"baseline row {q.id} is not judged; run rejudge first")
        s = small.get(q.id)
        g = grounding.get(q.id)
        usable = (s is not None and s.get("status_code") == 200 and s["meta"].get("model") == small_model
                  and g is not None)
        if usable and s.get("judge_score") is None:
            raise ValueError(f"small-trial row {q.id} is not judged; run rejudge first")
        rows.append(Row(
            id=q.id, split=q.split or "tune", features=Features(**{k: features[q.id][k] for k in FEATURE_KEYS}),
            base_judge=b["judge_score"], base_facts=b["fact_score"], base_cost=b["meta"]["cost_usd"],
            small_judge=s["judge_score"] if usable else None, small_facts=s["fact_score"] if usable else None,
            small_cost=s["meta"]["cost_usd"] if usable else 0.0,
            small_reason=g["grounding_reason"] if usable else "unavailable",
            small_overlap=g["grounding_overlap"] if usable else None,
        ))
    return rows


def _round(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    return x


def dump(results: list[tuple[Setting, dict[str, dict]]], chosen: tuple[Setting, dict] | None, header: dict) -> dict:
    """What simulate.json keeps: the chosen setting and every setting passing on tune. The full grid is not
    saved (it regenerates in under a second from the committed inputs)."""
    def entry(s: Setting, m: dict) -> dict:
        return {"setting": asdict(s), **{k: _round(v) for k, v in m.items() if k != "_sim"}}

    passing = [entry(s, m) for s, m in results if "tune" in m and meets_bar(m["tune"])]
    return {"header": header, "settings_total": len(results), "settings_passing": len(passing),
            "chosen": entry(*chosen) if chosen else None, "passing": passing}


HEAD = ["n","cost / 1k (baseline)", "judge (baseline)", "facts (baseline)", "routed small", "escalated",
        "small-route judge vs large", "bar"]


def _cells(m: dict) -> list[str]:
    srj = "–" if m["small_route_judge"] is None else \
        f"{m['small_route_judge']:.2f} vs {m['small_route_base_judge']:.2f}"
    return [str(m["n"]), f"${m['cost_per_1k']:.4f} (${m['base_cost_per_1k']:.4f})",
            f"{m['judge']:.2f} ({m['base_judge']:.2f})", f"{m['facts']:.3f} ({m['base_facts']:.3f})",
            f"{m['share_small']:.0%}", f"{m['escalation_rate']:.0%}", srj, "yes" if meets_bar(m) else "no"]


def _table(first: str, rows: list[tuple[str, dict]]) -> list[str]:
    cols = [first, *HEAD]
    lines = ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
    return lines + ["| " + " | ".join([label, *_cells(m)]) + " |" for label, m in rows]


def render(chosen: tuple[Setting, dict] | None, results: list[tuple[Setting, dict[str, dict]]], header: dict) -> str:
    lines = ["# Router simulation", "",
             f"Inputs: baseline `{header['baseline']}`, small trial `{header['small']}`. {len(results)} settings.", ""]
    if chosen is None:
        lines += ["**No setting meets the bar on the tune split. The router ships disabled (addendum §7.3).**", ""]
    else:
        setting, m = chosen
        lines += ["## Chosen setting", "", f"`{asdict(setting)}`", ""]
        lines += _table("split", [(split, m[split]) for split in SPLITS if split in m])
        small = [s for s in m["_sim"] if s["tier"] == "small"]
        lines += ["", f"## Questions routed small at the chosen setting ({len(small)})", "",
                  "| id | split | escalated | judge (final) | baseline judge |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {s['id']} | {s['split']} | {s['escalated']} | {s['judge']} | {s['base_judge']} |" for s in small]
    passing = sorted(((s, m) for s, m in results if "tune" in m and meets_bar(m["tune"])),
                     key=lambda sm: sm[1]["tune"]["cost_per_1k"])[:10]
    lines += ["", f"## Cheapest passing settings on tune (top {len(passing)})", ""]
    lines += _table("setting", [(f"`{asdict(s)}`", m["tune"]) for s, m in passing])
    return "\n".join(lines) + "\n"
