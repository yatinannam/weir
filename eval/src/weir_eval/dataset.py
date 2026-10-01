import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    namespace: str
    query: str
    group: Literal["distinct", "paraphrase", "trap"]
    cluster_id: str
    difficulty: Literal["easy", "medium", "hard"]
    required_facts: list[str] = Field(min_length=1)
    source_docs: list[str] = Field(min_length=1)
    split: Literal["tune", "holdout"] | None = None


def load_queries(path: Path) -> list[EvalQuery]:
    queries = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                queries.append(EvalQuery.model_validate_json(line))
            except ValueError as e:
                raise ValueError(f"{path}:{n}: {e}") from e
    return queries


def save_queries(path: Path, queries: list[EvalQuery]) -> None:
    lines = [json.dumps(q.model_dump(), ensure_ascii=False) for q in queries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


CLUSTER_SIZE = {"distinct": (1, 1), "paraphrase": (4, 6), "trap": (2, 2)}


def validate(queries: list[EvalQuery]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for q in queries:
        if q.id in seen:
            problems.append(f"duplicate id {q.id}")
        seen.add(q.id)
    clusters: dict[str, list[EvalQuery]] = defaultdict(list)
    for q in queries:
        clusters[q.cluster_id].append(q)
    for cid, members in clusters.items():
        groups = {m.group for m in members}
        if len(groups) != 1:
            problems.append(f"cluster {cid} mixes groups {sorted(groups)}")
            continue
        low, high = CLUSTER_SIZE[members[0].group]
        if not low <= len(members) <= high:
            problems.append(f"cluster {cid} ({members[0].group}) has {len(members)} members, needs {low}-{high}")
        if len({m.namespace for m in members}) != 1:
            problems.append(f"cluster {cid} spans namespaces")
        if len({m.split for m in members}) != 1:
            problems.append(f"cluster {cid} is split across tune/holdout")
        if members[0].group == "trap" and len({tuple(m.required_facts) for m in members}) != len(members):
            problems.append(f"trap cluster {cid} members must need different facts")
    return problems


def assign_splits(queries: list[EvalQuery], holdout_frac: float = 0.3, seed: int = 7) -> list[EvalQuery]:
    """Hold out ~holdout_frac of clusters per group; a cluster is never split (spec §11.1)."""
    rng = random.Random(seed)
    holdout: set[str] = set()
    for group in ("distinct", "paraphrase", "trap"):
        cluster_ids = sorted({q.cluster_id for q in queries if q.group == group})
        rng.shuffle(cluster_ids)
        holdout.update(cluster_ids[: round(len(cluster_ids) * holdout_frac)])
    return [q.model_copy(update={"split": "holdout" if q.cluster_id in holdout else "tune"}) for q in queries]
