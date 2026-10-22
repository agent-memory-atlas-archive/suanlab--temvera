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
from temvera.reanalysis import Proportion, consolidation_answerable

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"

RETAINING = {
    "Graphiti": ["external-graphiti-hybrid-v1", "external-graphiti-hybrid-gpt4o-v1",
                 "scale-sweep-graphiti-e8-v2", "scale-sweep-graphiti-e32-v2",
                 "scale-sweep-graphiti-e128-v2"],
    "Cognee chunks": ["external-cognee-chunks-grid-v3"],
    "Hindsight recall": ["external-hindsight-recall-v1"],
}
# The 43 agreement pairs and the 19 adjudicated ones (D-017) ran separately;
# the real-data test pools them.
REAL = {
    "Graphiti": ["lme-bitemporal-graphiti-agreement-v1",
                 "lme-bitemporal-graphiti-adjudicated-v1"],
    "Cognee chunks": ["lme-bitemporal-cognee-chunks-agreement-v3",
                      "lme-bitemporal-cognee-chunks-adjudicated-v1"],
    "Hindsight recall": ["lme-bitemporal-hindsight-recall-agreement-v2",
                         "lme-bitemporal-hindsight-recall-adjudicated-v1"],
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


def split(run: str, category: str) -> tuple[int, int, int, int]:
    """(exact, n) with nothing to filter, then (exact, n) with something to filter."""
    rs = [r for r in rows(run) if r["category"] == category and r["expected_values"]]
    free = [r for r in rs if not r["stale_values"]]
    conflict = [r for r in rs if r["stale_values"]]
    return (sum(r["exact"] for r in free), len(free),
            sum(r["exact"] for r in conflict), len(conflict))


def split_real(runs: list[str] | str) -> tuple[int, int, int, int]:
    """Real data: the control (no incidental value) has nothing to filter; current
    and valid-time questions all have a superseded value."""
    rs = [r for run in ([runs] if isinstance(runs, str) else runs) for r in rows(run)]
    free = [r for r in rs if r["category"] == "transaction_as_of" and not r["incidental_value"]]
    conflict = [r for r in rs if r["category"] in ("current", "valid_time")]
    return (sum(r["exact"] for r in free), len(free),
            sum(r["exact"] for r in conflict), len(conflict))


def ceiling(run: str) -> tuple[int, int, int, int, int]:
    """Valid-time (answerable, questions, exact inside, exact beyond, mismatches)."""
    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    sealed = [r for r in rows(run) if r["category"] == "valid_time"]
    bound: dict[tuple, tuple[bool, frozenset]] = {}
    for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in sealed}):
        profile, entities, revisions, seed = cell
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        cases = build_nl_cases(events)
        answerable = consolidation_answerable(events, cases)
        for case in cases:
            bound[cell + (case.case_id,)] = (answerable[case.case_id], case.expected_values)
    inside = beyond = answerable_n = mismatches = 0
    for r in sealed:
        answerable, expected = bound[(r["profile"], r["entities"], r["revisions"], r["seed"],
                                      r["case_id"])]
        mismatches += set(expected) != set(r["expected_values"])
        answerable_n += answerable
        inside += r["exact"] and answerable
        beyond += r["exact"] and not answerable
    return answerable_n, len(sealed), inside, beyond, mismatches


def reader_ceiling(reader_run: str, source_run: str) -> tuple[int, int]:
    """(correct valid-time verdicts, those beyond the ceiling) for a sealed
    rescore of ``source_run`` (scripts/llm_rescore.py), whose rows keep the
    source's cell and case ids."""
    config = json.loads((RUNS / source_run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    lines = (RUNS / reader_run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    sealed = [r for r in map(json.loads, lines) if r["category"] == "valid_time" and r["exact"]]
    beyond = 0
    for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in sealed}):
        profile, entities, revisions, seed = cell
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        answerable = consolidation_answerable(events, build_nl_cases(events))
        beyond += sum(not answerable[r["case_id"]] for r in sealed
                      if (r["profile"], r["entities"], r["revisions"], r["seed"]) == cell)
    return len(sealed), beyond


def first_ceiling_beyond(run: str) -> int:
    """Correct valid-time answers outside the first, falsified bound, which kept
    only values still valid at the question's transaction time. Kept so the
    paper's account of that failure recomputes like any other number."""
    from temvera.oracle import LifecycleOracle

    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    sealed = [r for r in rows(run) if r["category"] == "valid_time" and r["exact"]]
    beyond = 0
    for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in sealed}):
        profile, entities, revisions, seed = cell
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        oracle = LifecycleOracle(events)
        values = {e.belief_id: e.value for e in events if e.value is not None}
        cases = {c.case_id: c for c in build_nl_cases(events)}
        for r in (r for r in sealed if (r["profile"], r["entities"], r["revisions"], r["seed"]) == cell):
            case = cases[r["case_id"]]
            current = {values[b.belief_id] for b in oracle.query(
                case.subject, case.attribute,
                valid_at=case.transaction_at, transaction_at=case.transaction_at)}
            beyond += not (set(case.expected_values) <= current)
    return beyond


def main() -> int:
    print("H1  exact rate with nothing to filter | with something to filter (phi)")
    for system, runs in RETAINING.items():
        for run in runs:
            for category in ("transaction_as_of", "valid_time"):
                kf, nf, kc, nc = split(run, category)
                print(f"  {system:16s} {run:36s} {category:17s} pi={nf / (nf + nc):.3f}  "
                      f"{show(kf, nf):28s} {show(kc, nc)}")
    print("  real data: the control is asked before the revision exists; current and"
          " valid-time questions all have a superseded value")
    for system, runs in REAL.items():
        kf, nf, kc, nc = split_real(runs)
        print(f"  {system:16s} {' + '.join(runs):90s} {show(kf, nf):28s} {show(kc, nc)}")
    print("\nH2  valid-time ceiling for a consolidating store | exact | exact beyond it")
    total_mismatches = 0
    for system, runs in CONSOLIDATING.items():
        for run in runs:
            answerable, n, inside, beyond, mismatches = ceiling(run)
            total_mismatches += mismatches
            print(f"  {system:8s} {run:30s} ceiling {show(answerable, n):30s} "
                  f"exact {show(inside + beyond, n):30s} beyond {beyond}")
    print(f"  rebuilt cases disagreeing with the sealed ones: {total_mismatches}")
    return 1 if total_mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
