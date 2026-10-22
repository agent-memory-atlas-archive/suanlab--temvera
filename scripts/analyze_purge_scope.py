"""The purge category under the request's own scope (evidence ledger E-096).

The generator's typed purge removes only the latest belief, while the request a
system receives asks it to delete everything recorded about the attribute. This
rescores the purge-category questions of a sealed run under that wider reading:
an answer is correct only if it states no value the subject's attribute ever
had. Deterministic and offline.

    python scripts/analyze_purge_scope.py
"""

from __future__ import annotations

import json
from pathlib import Path

from temvera.external_experiment import _events_for
from temvera.model import Operation
from temvera.nl_workload import build_nl_cases

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"
GRID = ("external-mem0-grid-v2", "external-langmem-v1", "external-graphiti-hybrid-v1",
        "external-cognee-chunks-grid-v3", "external-hindsight-recall-v1",
        "external-cognee-grid-v1", "external-hindsight-reflect-v1")


def _rows(run: str) -> list[dict]:
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if r.get("system") != "oracle"]


def request_scope(run: str) -> dict[str, int]:
    """Purge questions: as specified, under the request's scope, and how many
    of them expect a value the request asked to delete."""
    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    rows = [r for r in _rows(run) if r["category"] == "purge"]
    out = {"questions": 0, "as_specified": 0, "request_scope": 0, "expect_deleted": 0}
    for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in rows}):
        profile, entities, revisions, seed = cell
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        key = {e.belief_id: (e.subject, e.attribute) for e in events
               if e.operation is Operation.INGEST}
        values: dict[tuple, set[str]] = {}
        for e in events:
            if e.operation is Operation.INGEST:
                values.setdefault(key[e.belief_id], set()).add(e.value)
        cases = {c.case_id: c for c in build_nl_cases(events)}
        for r in rows:
            if (r["profile"], r["entities"], r["revisions"], r["seed"]) != cell:
                continue
            case = cases[r["case_id"]]
            answer = r["answer"].casefold()
            out["questions"] += 1
            out["as_specified"] += bool(r["exact"])
            out["expect_deleted"] += bool(r["expected_values"])
            out["request_scope"] += not any(
                v.casefold() in answer for v in values[(case.subject, case.attribute)])
    return out


def main() -> int:
    for run in GRID:
        r = request_scope(run)
        print(f"{run:34s} as specified {r['as_specified']}/{r['questions']}  "
              f"request scope {r['request_scope']}/{r['questions']}  "
              f"(expecting a value the request deleted: {r['expect_deleted']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
