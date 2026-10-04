"""Router features for every eval question (Phase 3 addendum §7.2).

Uses Weir's own FeatureExtractor on hospital-rag's real /retrieve result, so the offline simulation sees exactly
what the live router sees. No LLM calls.
"""
from dataclasses import asdict, fields

from weir.rag.adapter import RetrieveResult
from weir.router.features import FeatureExtractor, Features

from .dataset import EvalQuery

FEATURE_KEYS = tuple(f.name for f in fields(Features) if f.name != "forced_tier")


def features_row(q: EvalQuery, retrieved: RetrieveResult, extractor: FeatureExtractor) -> dict:
    f = asdict(extractor.extract(q.query, retrieved))
    return {"id": q.id, "split": q.split, "group": q.group, **{k: f[k] for k in FEATURE_KEYS}}


async def collect_features(queries: list[EvalQuery], rag, extractor: FeatureExtractor, k: int) -> list[dict]:
    rows = []
    for q in queries:
        rows.append(features_row(q, await rag.retrieve(q.query, q.namespace, k), extractor))
    return rows
