"""H6: what a retroactive correction does to each design. Offline, sealed runs only.

The analysis was written and committed with its predictions
(docs/preregistration-h6.md) before the runs existed. It rebuilds each history
from its seed, finds the subjects that received a correction, and splits the
questions asked after the correction was recorded into:

* ``corrected``  -- valid time inside the corrected interval (answer: the
  corrected value; the replaced value is stale);
* ``present_corrected`` / ``present_uncorrected`` -- the current value of a
  subject with / without a correction, asked at the end of the history;
* ``past_uncorrected`` -- an ordinary superseded interval of a subject without a
  correction, asked at the end (the usual valid-time question, for contrast).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from temvera.external_experiment import _events_for
from temvera.model import Operation
from temvera.nl_workload import build_nl_cases
from temvera.reanalysis import Proportion

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"
SYSTEMS = {"Mem0": "external-corrections-mem0-v1", "Graphiti": "external-corrections-graphiti-v1"}
KINDS = ("corrected", "present_corrected", "present_uncorrected", "past_uncorrected",
         "pre_correction")


def classify(run: str) -> dict[str, list[bool]]:
    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [r for r in map(json.loads, lines) if r.get("system") != "oracle"]
    by_cell = defaultdict(dict)
    for r in rows:
        by_cell[(r["profile"], r["entities"], r["revisions"], r["seed"])][r["case_id"]] = r
    out: dict[str, list[bool]] = {kind: [] for kind in KINDS}
    for (profile, entities, revisions, seed), sealed in sorted(by_cell.items()):
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        end = max(e.recorded_at for e in events)
        fixes = {(e.subject, e.attribute): e for e in events
                 if e.operation is Operation.INGEST and e.valid_to is not None}
        latest = {}
        for e in events:
            if e.operation is Operation.INGEST and e.valid_to is None:
                key = (e.subject, e.attribute)
                if key not in latest or e.valid_from > latest[key].valid_from:
                    latest[key] = e
        for case in build_nl_cases(events):
            row = sealed[case.case_id]
            assert set(row["expected_values"]) == set(case.expected_values), case.case_id
            key = (case.subject, case.attribute)
            fix = fixes.get(key)
            if fix is not None and case.transaction_at >= fix.recorded_at \
                    and fix.valid_from <= case.valid_at < fix.valid_to:
                out["corrected"].append(row["exact"])
            elif fix is not None and case.transaction_at < fix.recorded_at \
                    and fix.valid_from <= case.valid_at < fix.valid_to:
                # What was believed about the interval before its correction
                # (H11a). Trivial under forward replay; a real transaction-time
                # question when the final store is asked.
                out["pre_correction"].append(row["exact"])
            elif case.transaction_at == end and key in latest \
                    and case.valid_at == latest[key].valid_from:
                kind = "present_corrected" if fix is not None else "present_uncorrected"
                out[kind].append(row["exact"])
            elif case.transaction_at == end and fix is None and case.stale_values \
                    and case.category == "valid_time":
                out["past_uncorrected"].append(row["exact"])
    return out


def pre_correction_rows(run: str) -> list[tuple[dict, str]]:
    """(sealed row, the later correction's value) for every H11a question."""
    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    by_cell: dict[tuple, dict] = defaultdict(dict)
    for r in map(json.loads, lines):
        if r.get("system") != "oracle":
            by_cell[(r["profile"], r["entities"], r["revisions"], r["seed"])][r["case_id"]] = r
    out = []
    for (profile, entities, revisions, seed), sealed in sorted(by_cell.items()):
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        fixes = {(e.subject, e.attribute): e for e in events
                 if e.operation is Operation.INGEST and e.valid_to is not None}
        for case in build_nl_cases(events):
            fix = fixes.get((case.subject, case.attribute))
            if fix is not None and case.transaction_at < fix.recorded_at \
                    and fix.valid_from <= case.valid_at < fix.valid_to:
                out.append((sealed[case.case_id], fix.value))
    return out


def pre_correction(run: str, judge: str | None = None) -> dict[str, int]:
    """H11a: what was believed about a corrected interval before the correction.

    ``exact`` is the grid's scorer as preregistered. It counts only values known
    at the question's transaction time as stale, so an answer that also states
    the later correction passes; ``strict`` (added after the runs) fails it too.
    With ``judge`` (a sealed llm_rescore run of ``run``), ``judged`` uses the
    value the answer asserts, and fails it if that is the correction.
    """
    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [r for r in map(json.loads, lines) if r.get("system") != "oracle"]
    verdicts = None
    if judge is not None:
        judged = (RUNS / judge / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
        verdicts = [json.loads(line) for line in judged]
        if [(r["case_id"], r["query"]) for r in verdicts] != [(r["case_id"], r["query"]) for r in rows]:
            raise ValueError(f"{judge} does not rescore {run}")
    by_cell: dict[tuple, dict] = defaultdict(dict)
    for index, r in enumerate(rows):
        by_cell[(r["profile"], r["entities"], r["revisions"], r["seed"])][r["case_id"]] = (
            r, verdicts[index] if verdicts else None)
    out = {"questions": 0, "exact": 0, "strict": 0, "judged": 0}
    for (profile, entities, revisions, seed), sealed in sorted(by_cell.items()):
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        fixes = {(e.subject, e.attribute): e for e in events
                 if e.operation is Operation.INGEST and e.valid_to is not None}
        for case in build_nl_cases(events):
            fix = fixes.get((case.subject, case.attribute))
            if fix is None or not (case.transaction_at < fix.recorded_at
                                   and fix.valid_from <= case.valid_at < fix.valid_to):
                continue
            row, verdict = sealed[case.case_id]
            states_fix = fix.value.casefold() in row["answer"].casefold()
            out["questions"] += 1
            out["exact"] += bool(row["exact"])
            out["strict"] += bool(row["exact"]) and not states_fix
            if verdict is not None:
                out["judged"] += bool(verdict["exact"]) and \
                    fix.value.casefold() not in verdict["value"].casefold()
    return out


def vanished(run: str) -> tuple[int, int]:
    """(subjects whose current value appears in no answer about them once the
    correction is recorded, corrected subjects asked about after it).

    Added after the preregistered results were read, to tell a value the store
    no longer returns from one it merely ranked low; it is not a preregistered
    test."""
    import re

    config = json.loads((RUNS / run / "config.json").read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in config["profiles"]}
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [r for r in map(json.loads, lines) if r.get("system") != "oracle"]
    gone = seen = 0
    for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in rows}):
        profile, entities, revisions, seed = cell
        events = _events_for(seed, entities, revisions, profiles[profile],
                             bool(config.get("naturalize", True)),
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        here = [r for r in rows if (r["profile"], r["entities"], r["revisions"], r["seed"]) == cell]
        latest = {}
        for e in events:
            if e.operation is Operation.INGEST and e.valid_to is None:
                key = (e.subject, e.attribute)
                if key not in latest or e.valid_from > latest[key].valid_from:
                    latest[key] = e
        for e in events:
            if e.operation is not Operation.INGEST or e.valid_to is None:
                continue
            after = [r for r in here if e.subject in r["query"]
                     and re.search(r"known by (\S+)\?", r["query"]).group(1)
                     >= e.recorded_at.date().isoformat()]
            if after:
                seen += 1
                gone += not any(latest[(e.subject, e.attribute)].value in r["answer"]
                                for r in after)
    return gone, seen


def show(hits: list[bool]) -> str:
    if not hits:
        return "-"
    p = Proportion(sum(hits), len(hits))
    low, high = p.wilson()
    return f"{sum(hits)}/{len(hits)} = {p.rate:.3f} [{low:.3f}, {high:.3f}]"


def main() -> int:
    for system, run in SYSTEMS.items():
        result = classify(run)
        print(system)
        for kind in KINDS:
            print(f"  {kind:20s} {show(result[kind])}")
        gone, seen = vanished(run)
        print(f"  current value absent from every later answer (post hoc): {gone}/{seen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
