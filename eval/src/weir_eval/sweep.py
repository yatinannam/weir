"""Threshold sweep (Phase 2 addendum §7.2): how often does the cache accept a pair it should,
and how often one it shouldn't, at each similarity threshold, with and without the entity guard."""
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .dataset import EvalQuery

THRESHOLDS = [round(0.80 + 0.01 * i, 2) for i in range(19)]


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    kind: str          # positive | trap | hard_negative
    split: str         # tune | holdout | cross
    similarity: float
    guard_conflict: bool


def build_pairs(queries: list[EvalQuery], vectors: dict[str, np.ndarray],
                conflicts: Callable[[str, str], bool]) -> list[Pair]:
    by_id = {q.id: q for q in queries}
    pairs: dict[tuple[str, str], Pair] = {}

    def add(a: str, b: str, kind: str) -> None:
        key = tuple(sorted((a, b)))
        if key in pairs:
            return
        qa, qb = by_id[key[0]], by_id[key[1]]
        split = qa.split if qa.split == qb.split else "cross"
        pairs[key] = Pair(key[0], key[1], kind, split, float(vectors[key[0]] @ vectors[key[1]]),
                          conflicts(qa.query, qb.query))

    clusters: dict[str, list[EvalQuery]] = defaultdict(list)
    for q in queries:
        clusters[q.cluster_id].append(q)
    for members in clusters.values():
        kind = {"paraphrase": "positive", "trap": "trap"}.get(members[0].group)
        if kind:
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    add(a.id, b.id, kind)
    for q in queries:  # hard negatives: the nearest question from another cluster with a different answer
        others = [o for o in queries if o.cluster_id != q.cluster_id
                  and not set(o.required_facts) & set(q.required_facts)]
        if others:
            nearest = max(others, key=lambda o: float(vectors[q.id] @ vectors[o.id]))
            add(q.id, nearest.id, "hard_negative")
    return list(pairs.values())


def sweep(pairs: list[Pair], thresholds: list[float], use_guard: bool) -> list[dict]:
    positives = sum(p.kind == "positive" for p in pairs)
    rows = []
    for t in thresholds:
        accepted = [p for p in pairs if p.similarity >= t and not (use_guard and p.guard_conflict)]
        pos = sum(p.kind == "positive" for p in accepted)
        rows.append({
            "threshold": round(t, 2), "use_guard": use_guard, "accepted": len(accepted),
            "hit_rate": pos / positives if positives else 0.0,
            "false_hit_rate": (len(accepted) - pos) / len(accepted) if accepted else 0.0,
            "trap_false_hits": sum(p.kind == "trap" for p in accepted),
            "hard_negative_false_hits": sum(p.kind == "hard_negative" for p in accepted),
        })
    return rows


def choose_threshold(rows: list[dict], max_false_hit: float = 0.01) -> float | None:
    passing = [r["threshold"] for r in rows
               if r["accepted"] > 0 and r["false_hit_rate"] < max_false_hit and r["trap_false_hits"] == 0]
    return min(passing) if passing else None


def write_sweep_report(out_dir: Path, results: dict[tuple[str, bool], list[dict]], chosen: float | None,
                       pairs: list[Pair]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "sweep.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["split", *results[("tune", True)][0].keys()])
        writer.writeheader()
        for (split, _), rows in results.items():
            for r in rows:
                writer.writerow({"split": split, **r})

    fig, ax = plt.subplots(figsize=(7, 4))
    for guard, style in ((True, "-"), (False, "--")):
        rows = results[("tune", guard)]
        xs = [r["threshold"] for r in rows]
        label = "guard on" if guard else "guard off"
        ax.plot(xs, [r["hit_rate"] for r in rows], style, color="tab:blue", label=f"hit rate ({label})")
        ax.plot(xs, [r["false_hit_rate"] for r in rows], style, color="tab:red", label=f"false-hit rate ({label})")
    if chosen is not None:
        ax.axvline(chosen, color="gray", linestyle=":", label=f"chosen {chosen:.2f}")
    ax.set_xlabel("cosine similarity threshold")
    ax.set_ylabel("rate")
    ax.set_title("Cache threshold sweep (tune split)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "threshold.png", dpi=120)
    plt.close(fig)

    counts = Counter((p.kind, p.split) for p in pairs)
    lines = ["# Threshold sweep", "", f"Chosen threshold: **{chosen if chosen is not None else 'none passes'}**", "",
             "Pairs: " + ", ".join(f"{k}/{s}: {n}" for (k, s), n in sorted(counts.items())), ""]
    for split in ("tune", "holdout", "all"):
        for guard in (True, False):
            lines += [f"## {split}, guard {'on' if guard else 'off'}", "",
                      "| threshold | accepted | hit rate | false-hit rate | trap false hits | hard-neg false hits |",
                      "| --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {r['threshold']:.2f} | {r['accepted']} | {r['hit_rate']:.3f} | {r['false_hit_rate']:.3f} | "
                      f"{r['trap_false_hits']} | {r['hard_negative_false_hits']} |" for r in results[(split, guard)]]
            lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "pairs.jsonl").write_text("".join(json.dumps(asdict(p)) + "\n" for p in pairs), encoding="utf-8")
