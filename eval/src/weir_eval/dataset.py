import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    namespace: str
    query: str
    group: Literal["distinct", "paraphrase", "trap", "unanswerable"]
    cluster_id: str
    difficulty: Literal["easy", "medium", "hard"]
    required_facts: list[str] = Field(min_length=1)
    source_docs: list[str] = Field(default_factory=list)
    split: Literal["tune", "holdout"] | None = None

    @model_validator(mode="after")
    def sources_match_group(self) -> "EvalQuery":
        if self.group == "unanswerable" and self.source_docs:
            raise ValueError("unanswerable queries have no source_docs")
        if self.group != "unanswerable" and not self.source_docs:
            raise ValueError("answerable queries need at least one source_doc")
        return self


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


CLUSTER_SIZE = {"distinct": (1, 1), "paraphrase": (4, 6), "trap": (2, 2), "unanswerable": (1, 1)}


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
    """Hold out ~holdout_frac of the *unassigned* clusters per group (spec §11.1). Clusters that
    already have a split keep it, so adding questions never reshuffles the existing tune/holdout sets."""
    rng = random.Random(seed)
    assigned = {q.cluster_id: q.split for q in queries if q.split is not None}
    holdout: set[str] = set()
    for group in ("distinct", "paraphrase", "trap", "unanswerable"):
        new_ids = sorted({q.cluster_id for q in queries if q.group == group and q.cluster_id not in assigned})
        rng.shuffle(new_ids)
        holdout.update(new_ids[: round(len(new_ids) * holdout_frac)])
    return [q.model_copy(update={"split": assigned.get(q.cluster_id)
                                 or ("holdout" if q.cluster_id in holdout else "tune")}) for q in queries]
