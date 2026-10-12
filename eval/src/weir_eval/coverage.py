"""Offline scoring of saved answers with Weir's coverage check (D79), plus synthetic omissions.

For each answered question, re-fetch its chunks from hospital-rag (retrieval only, no model), keep the ones from
the documents the answer cited, and run the check. Synthetic omissions: every good answer (judge 5, full facts)
that passes is copied once per required detail type it contains, with every detail of that type deleted; the
check should flag each copy.
"""
from weir.router.coverage import check, details, passage, required_types, strip_type


# hospital-rag's refusal (prompt.NOT_FOUND_MESSAGE). Saved answers don't carry its not_found flag; live, Weir
# never runs the check on a refusal (it cites nothing), and grounding escalates it.
NOT_FOUND = "couldn't find that in weir general hospital's information"


def _good(record: dict) -> bool:
    return record.get("judge_score") == 5 and record.get("fact_score") == 1.0


async def coverage_rows(records: list[dict], rag, k: int) -> tuple[list[dict], list[dict]]:
    rows, synthetic = [], []
    for r in records:
        if r.get("status_code") != 200:
            continue
        if NOT_FOUND in r["answer"].lower():
            rows.append({"id": r["id"], "passed": True, "reason": "skipped:not_found", "strict_passed": True,
                         "required": sorted(required_types(r["query"])), "passage": []})
            continue
        retrieved = await rag.retrieve(r["query"], r["namespace"], k)
        cited = {s["id"] for s in (r.get("sources") or [])}
        texts = [c.text for c in retrieved.chunks if c.doc_id in cited] or [c.text for c in retrieved.chunks]
        cov = check(r["query"], r["answer"], texts)
        lines = passage(r["query"], texts)
        rows.append({"id": r["id"], "passed": cov.passed, "reason": cov.reason, "strict_passed": cov.strict_passed,
                     "required": sorted(required_types(r["query"])), "passage": lines})
        if _good(r) and cov.passed:
            source, given = details(" ".join(lines)), details(r["answer"])
            for kind in sorted(required_types(r["query"])):
                if source.get(kind) and given.get(kind):
                    stripped = check(r["query"], strip_type(r["answer"], kind), texts)
                    synthetic.append({"id": r["id"], "type": kind, "flagged": not stripped.passed})
    return rows, synthetic


def summarize(rows: list[dict], synthetic: list[dict], records: list[dict]) -> dict:
    by_id = {r["id"]: r for r in records}
    good = [x for x in rows if _good(by_id[x["id"]])]
    return {
        "answers": len(rows),
        "flagged": [x["id"] for x in rows if not x["passed"]],
        "flagged_strict": [x["id"] for x in rows if not x["strict_passed"]],
        "good_answers": len(good),
        "false_flag_rate": sum(not x["passed"] for x in good) / len(good) if good else 0.0,
        "false_flag_rate_strict": sum(not x["strict_passed"] for x in good) / len(good) if good else 0.0,
        "synthetic": len(synthetic),
        "synthetic_recall": sum(s["flagged"] for s in synthetic) / len(synthetic) if synthetic else None,
        "synthetic_missed": [f'{s["id"]}:{s["type"]}' for s in synthetic if not s["flagged"]],
    }
