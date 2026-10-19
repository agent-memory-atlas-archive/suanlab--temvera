"""Two offline tests of what the measurements imply, over sealed runs only.

H1 (decomposition): a retaining store read at the retrieval layer answers a
question exactly when it has nothing to filter. Accuracy then splits into
pi, the share of questions with no superseded value known, and phi, the exact
rate on the rest; for such a store phi should be near zero everywhere.

H2 (consolidation ceiling): a consolidating store holds at most the latest
value not superseded or purged (``reanalysis.consolidated_values``), so its
valid-time accuracy cannot exceed the share of questions whose answer is that
value. The histories are rebuilt from each run's seeds; a rebuilt case that
disagrees with the sealed one is reported, not skipped.

No API key, server or dataset is needed. Evidence ledger E-085, E-086.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from temvera.external_experiment import _events_for
from temvera.nl_workload import build_nl_cases
from temvera.oracle import LifecycleOracle
from temvera.reanalysis import Proportion, consolidated_values

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"

RETAINING = {
    "Graphiti": ["external-graphiti-hybrid-v1", "external-graphiti-hybrid-gpt4o-v1",
                 "scale-sweep-graphiti-e8-v2", "scale-sweep-graphiti-e32-v2",
                 "scale-sweep-graphiti-e128-v2"],
    "Cognee chunks": ["external-cognee-chunks-grid-v3"],
    "Hindsight recall": ["external-hindsight-recall-v1"],
}
REAL = {
    "Graphiti": "lme-bitemporal-graphiti-agreement-v1",
    "Cognee chunks": "lme-bitemporal-cognee-chunks-agreement-v3",
    "Hindsight recall": "lme-bitemporal-hindsight-recall-agreement-v2",
}
CONSOLIDATING = {
    "Mem0": ["external-mem0-grid-v2", "external-mem0-grid-gpt4o-v1",
             "scale-sweep-mem0-e8-v2", "scale-sweep-mem0-e32-v2",
             "scale-sweep-mem0-e128-s7-v3", "scale-sweep-mem0-e128-s17-v3",
             "scale-sweep-mem0-e128-s42-v3"],
    "LangMem": ["external-langmem-v1"],
}


def rows(run: str) -> list[dict]:
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if r.get("system") != "oracle"]


def show(k: int, n: int) -> str:
    if not n:
        return "-"
    low, high = Proportion(k, n).wilson()
    return f"{k}/{n} = {k / n:.3f} [{low:.3f}, {high:.3f}]"


def h1() -> None:
    print("H1  exact rate with nothing to filter | with something to filter (phi)")
    for system, runs in RETAINING.items():
        for run in runs:
            for category in ("transaction_as_of", "valid_time"):
                rs = [r for r in rows(run) if r["category"] == category and r["expected_values"]]
                free = [r for r in rs if not r["stale_values"]]
                conflict = [r for r in rs if r["stale_values"]]
                print(f"  {system:16s} {run:36s} {category:17s} pi={len(free) / len(rs):.3f}  "
                      f"{show(sum(r['exact'] for r in free), len(free)):28s} "
                      f"{show(sum(r['exact'] for r in conflict), len(conflict))}")
    print("  real data: the control is asked before the revision exists; current and"
          " valid-time questions all have a superseded value")
    for system, run in REAL.items():
        rs = rows(run)
        free = [r for r in rs if r["category"] == "transaction_as_of" and not r["incidental_value"]]
        conflict = [r for r in rs if r["category"] in ("current", "valid_time")]
        print(f"  {system:16s} {run:45s} {show(sum(r['exact'] for r in free), len(free)):28s} "
              f"{show(sum(r['exact'] for r in conflict), len(conflict))}")


def h2() -> int:
    print("\nH2  valid-time ceiling for a consolidating store | exact | exact beyond it")
    mismatches = 0
    for system, runs in CONSOLIDATING.items():
        for run in runs:
            config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
            profiles = {p["name"]: p for p in config["profiles"]}
            sealed = [r for r in rows(run) if r["category"] == "valid_time"]
            ceiling: dict[tuple, tuple[bool, frozenset]] = {}
            for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in sealed}):
                profile, entities, revisions, seed = cell
                events = _events_for(seed, entities, revisions, profiles[profile],
                                     bool(config.get("naturalize", True)),
                                     int(config.get("attributes", 1)),
                                     bool(config.get("distinct_values", False)),
                                     config.get("natural_pools", "standard"))
                oracle = LifecycleOracle(events)
                for case in build_nl_cases(events):
                    kept = consolidated_values(oracle, case.subject, case.attribute,
                                               case.transaction_at)
                    answerable = bool(case.expected_values) and case.expected_values <= kept
                    ceiling[cell + (case.case_id,)] = (answerable, case.expected_values)
            inside = beyond = answerable_n = 0
            for r in sealed:
                answerable, expected = ceiling[(r["profile"], r["entities"], r["revisions"],
                                                r["seed"], r["case_id"])]
                mismatches += set(expected) != set(r["expected_values"])
                answerable_n += answerable
                inside += r["exact"] and answerable
                beyond += r["exact"] and not answerable
            print(f"  {system:8s} {run:30s} ceiling {show(answerable_n, len(sealed)):30s} "
                  f"exact {show(inside + beyond, len(sealed)):30s} beyond {beyond}")
    print(f"  rebuilt cases disagreeing with the sealed ones: {mismatches}")
    return mismatches


if __name__ == "__main__":
    h1()
    sys.exit(1 if h2() else 0)
