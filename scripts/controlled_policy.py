"""H12: change only the retention policy, keep retriever and reader fixed.

The deployed systems differ in extractor, retriever and reader as well as in
what they keep, so the consolidate/retain taxonomy has no controlled test of the
policy alone. Here the store is built from the grid's own rendered turns, for
every question from the turns recorded by its transaction time, under one of two
policies:

* ``retain`` keeps every rendered turn;
* ``consolidate`` keeps, per person, only the statement of the latest value that
  is neither superseded nor purged (an expired value is kept).

Both are searched with the same BM25 over the same text (top five), scored as
returned with the grid's exact scorer, and read by the common reader of H9
(``scripts/llm_rescore.py``: same prompt, ``gpt-4o-mini``, temperature 0).

    python scripts/controlled_policy.py experiments/runs/controlled-policy-v1
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402
from temvera.external_experiment import _events_for  # noqa: E402
from temvera.model import Operation  # noqa: E402
from temvera.nl_workload import build_nl_cases, render_turns  # noqa: E402
from temvera.reanalysis import load_run, matched_cells  # noqa: E402

RUNS = ROOT / "experiments" / "runs"
GRID = ("external-mem0-grid-v2", "external-langmem-v1", "external-graphiti-hybrid-v1",
        "external-cognee-chunks-grid-v3", "external-hindsight-recall-v1",
        "external-cognee-grid-v1", "external-hindsight-reflect-v1")
POLICIES = ("retain", "consolidate")
TOP_K = 5
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def bm25(records: list[str], query: str, k: int = TOP_K,
         k1: float = 1.5, b: float = 0.75) -> list[str]:
    """Top-k records by BM25; ties keep record order, so the result is deterministic."""
    docs = [_tokens(r) for r in records]
    if not docs:
        return []
    avg = sum(map(len, docs)) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    scores = []
    for index, doc in enumerate(docs):
        tf = Counter(doc)
        score = 0.0
        for term in set(_tokens(query)):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avg))
        scores.append((-score, index))
    return [records[i] for _, i in sorted(scores)[:k]]


def stores(events, turns, transaction_at) -> dict[str, list[str]]:
    known = [t for t in turns if t.recorded_at <= transaction_at]
    text = {t.event_id: t.text for t in known}
    retain = [t.text for t in known]
    seen = [e for e in events if e.recorded_at <= transaction_at]
    subject_of = {e.belief_id: (e.subject, e.attribute) for e in seen
                  if e.operation is Operation.INGEST}
    latest: dict[tuple, object] = {}
    for event in seen:  # events are in recorded order
        if event.operation is Operation.INGEST:
            latest[(event.subject, event.attribute)] = event
        elif event.operation is Operation.PURGE and event.belief_id in subject_of:
            key = subject_of[event.belief_id]
            if key in latest and latest[key].belief_id == event.belief_id:
                del latest[key]
    consolidate = [text[e.event_id] for e in latest.values() if e.event_id in text]
    return {"retain": retain, "consolidate": consolidate}


def exact(text: str, expected, stale) -> bool:
    return llm_rescore.exact(text, list(expected), list(stale))


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    keep = matched_cells(*(load_run(RUNS / r) for r in GRID))
    config = json.loads((RUNS / GRID[0] / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    work = []
    for profile, entities, revisions, seed in sorted(keep):
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        events = tuple(sorted(events, key=lambda e: e.recorded_at))
        turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
        for case in build_nl_cases(events):
            built = stores(events, turns, case.transaction_at)
            for policy in POLICIES:
                returned = " | ".join(bm25(built[policy], case.query_text))
                work.append({
                    "policy": policy, "profile": profile, "entities": entities,
                    "revisions": revisions, "seed": seed, "case_id": case.case_id,
                    "category": case.category, "query": case.query_text,
                    "expected_values": sorted(case.expected_values),
                    "stale_values": sorted(case.stale_values), "answer": returned,
                    "exact_returned": exact(returned, case.expected_values, case.stale_values),
                })
    client = llm_rescore._client("openai")

    def read(row: dict) -> dict:
        text = llm_rescore._complete(client, "gpt-4o-mini", "reader", row)
        value = llm_rescore._value("reader", text)
        return {**row, "reader_value": value,
                "exact_read": exact(value, row["expected_values"], row["stale_values"])}

    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(read, work))
    summary: dict[str, dict] = {}
    for row in rows:
        entry = summary.setdefault(f"{row['policy']}:{row['category']}",
                                   {"n": 0, "exact_returned": 0, "exact_read": 0})
        entry["n"] += 1
        entry["exact_returned"] += row["exact_returned"]
        entry["exact_read"] += row["exact_read"]
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary}, indent=2,
                                                 sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-controlled-policy-v1", "cells_from": list(GRID),
                          "policies": list(POLICIES), "retriever": "bm25 k1=1.5 b=0.75",
                          "top_k": TOP_K, "reader": "openai:gpt-4o-mini", "temperature": 0,
                          "reader_prompt_sha256": llm_rescore.prompt_hash("reader")},
             command=f"python scripts/controlled_policy.py {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for the common reader")
    raise SystemExit(main(*sys.argv[1:]))
