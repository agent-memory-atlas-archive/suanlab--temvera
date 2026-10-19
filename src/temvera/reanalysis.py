"""Corrected aggregation over sealed external-comparison runs.

Review of the first paper draft found several aggregation defects that changed
reported conclusions. This module recomputes the affected statistics directly
from sealed run artifacts so the paper can cite verified numbers:

* **Macro vs micro.** The draft reported unweighted means over cells whose case
  counts differ by 2.5x, without saying so. Both are computed here.
* **Vacuous abstention cells.** Cells with no abstention case recorded
  ``abstention_accuracy = 1.0`` and were averaged in, inflating the statistic.
  Only cells that actually contain abstention cases are counted here.
* **Unmatched grids.** Mem0 ran 48 cells and Graphiti 20; the draft compared the
  two aggregates as "identical histories". Matching restricts both to the shared
  (profile, entities, revisions, seed) cells.
* **Missing intervals and denominators.** Wilson score intervals are provided so
  proportions resting on few cases (e.g. expiry at 0/16) are not read as exact.
* **Budget sensitivity.** ``exact`` requires every expected value and no stale
  value across the *concatenation* of the retrieved items, so it depends on the
  retrieval budget. ``k_sweep`` re-scores sealed transcripts at truncated k.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_CELL_KEYS = ("profile", "entities", "revisions", "seed")


@dataclass(frozen=True, slots=True)
class Proportion:
    """A count-backed rate with an explicit denominator and interval."""

    successes: int
    total: int

    @property
    def rate(self) -> float:
        return self.successes / self.total if self.total else float("nan")

    def wilson(self, z: float = 1.96) -> tuple[float, float]:
        """Wilson score interval; correct at 0 and 1, unlike normal approx."""
        n = self.total
        if not n:
            return (float("nan"), float("nan"))
        p = self.successes / n
        d = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / d
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return (max(0.0, centre - half), min(1.0, centre + half))

    def as_dict(self) -> dict[str, Any]:
        low, high = self.wilson()
        return {
            "successes": self.successes,
            "total": self.total,
            "rate": self.rate,
            "wilson95_low": low,
            "wilson95_high": high,
        }


def load_run(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "results.json").read_text(encoding="utf-8"))


def load_transcript(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "transcript.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def cell_key(row: dict[str, Any]) -> tuple:
    return tuple(row[key] for key in _CELL_KEYS)


def matched_cells(*runs: dict[str, Any]) -> set[tuple]:
    """Cells present in every run, so aggregates describe the same histories."""
    sets = []
    for run in runs:
        sets.append({cell_key(row) for row in run["rows"]})
    if not sets:
        return set()
    common = sets[0]
    for other in sets[1:]:
        common &= other
    return common


def macro(rows: Iterable[dict[str, Any]], metric: str) -> float:
    values = [row[metric] for row in rows]
    return sum(values) / len(values) if values else float("nan")


def abstention(rows: Iterable[dict[str, Any]]) -> Proportion:
    """Abstention accuracy over cells that actually contain abstention cases.

    Cells without abstention cases report 1.0 by convention; averaging those in
    measures nothing and inflates the result.
    """
    successes = total = 0
    for row in rows:
        cases = int(row.get("abstention_cases", 0))
        if not cases:
            continue
        total += cases
        successes += round(row["abstention_accuracy"] * cases)
    return Proportion(successes, total)


def category_counts(
    transcript: Iterable[dict[str, Any]], *, cells: set[tuple] | None = None
) -> dict[str, Proportion]:
    """Case-level exact counts per category, optionally restricted to cells."""
    tally: dict[str, list[int]] = {}
    for row in transcript:
        if cells is not None and cell_key(row) not in cells:
            continue
        entry = tally.setdefault(row["category"], [0, 0])
        entry[0] += bool(row["exact"])
        entry[1] += 1
    return {
        category: Proportion(hits, total)
        for category, (hits, total) in sorted(tally.items())
    }


def overall_counts(
    transcript: Iterable[dict[str, Any]], *, cells: set[tuple] | None = None
) -> Proportion:
    rows = [
        row
        for row in transcript
        if cells is None or cell_key(row) in cells
    ]
    return Proportion(sum(bool(row["exact"]) for row in rows), len(rows))


def _score_truncated(row: dict[str, Any], k: int) -> bool:
    """Re-score one transcript row using only its top-k retrieved items.

    Items are joined with " | " by the adapters and rank order is preserved, so
    truncating the string is equivalent to having queried with a smaller budget.
    """
    answer = " | ".join(row["answer"].split(" | ")[:k]).casefold()
    expected = {value.casefold() for value in row["expected_values"]}
    stale = {value.casefold() for value in row["stale_values"]}
    present_expected = {value for value in expected if value in answer}
    present_stale = {value for value in stale if value in answer}
    if expected:
        return present_expected == expected and not present_stale
    return not present_stale


def k_sweep(
    transcript: Iterable[dict[str, Any]],
    budgets: tuple[int, ...] = (1, 2, 3, 5, 10),
    *,
    cells: set[tuple] | None = None,
) -> dict[int, dict[str, Any]]:
    """Exact accuracy overall and per category at each truncated budget."""
    rows = [
        row for row in transcript if cells is None or cell_key(row) in cells
    ]
    result: dict[int, dict[str, Any]] = {}
    for k in budgets:
        per_category: dict[str, list[int]] = {}
        hits = 0
        for row in rows:
            exact = _score_truncated(row, k)
            hits += exact
            entry = per_category.setdefault(row["category"], [0, 0])
            entry[0] += exact
            entry[1] += 1
        result[k] = {
            "overall": Proportion(hits, len(rows)).as_dict(),
            "by_category": {
                category: Proportion(h, t).as_dict()
                for category, (h, t) in sorted(per_category.items())
            },
        }
    return result


def compare_systems(
    run_dirs: dict[str, Path], *, match: bool = True
) -> dict[str, Any]:
    """Corrected side-by-side comparison of external runs.

    Returns macro and micro aggregates, per-category counts with Wilson
    intervals, and a corrected abstention rate, optionally restricted to the
    cells all runs share.
    """
    runs = {name: load_run(path) for name, path in run_dirs.items()}
    transcripts = {name: load_transcript(path) for name, path in run_dirs.items()}
    cells = matched_cells(*runs.values()) if match else None

    report: dict[str, Any] = {
        "matched": bool(match),
        "matched_cell_count": len(cells) if cells is not None else None,
        "systems": {},
    }
    for name, run in runs.items():
        system = next(
            row["system"] for row in run["rows"] if row["system"] != "oracle"
        )
        rows = [
            row
            for row in run["rows"]
            if row["system"] == system
            and (cells is None or cell_key(row) in cells)
        ]
        transcript = transcripts[name]
        report["systems"][name] = {
            "system": system,
            "cells": len(rows),
            "macro_exact": macro(rows, "exact_state_accuracy"),
            "macro_recall": macro(rows, "evidence_recall"),
            "macro_stale_use": macro(rows, "stale_use_rate"),
            "micro_exact": overall_counts(transcript, cells=cells).as_dict(),
            "by_category_micro": {
                category: proportion.as_dict()
                for category, proportion in category_counts(
                    transcript, cells=cells
                ).items()
            },
            "abstention_on_cells_with_cases": abstention(rows).as_dict(),
        }
    return report


def consolidated_values(oracle: Any, subject: str, attribute: str, at: Any) -> frozenset[str]:
    """What a consolidating store can still hold for one subject and attribute.

    Consolidation overwrites a value only when a newer one supersedes it. Expiry
    ends a value without replacing it, so the store keeps it (often with an end
    marker), and purge removes it. The result is the latest value, as known at
    ``at``, that was neither superseded nor purged -- an upper bound on what any
    reader of such a store can answer. A first version of this bound counted
    only values still valid at ``at`` and was contradicted by the runs: every
    answer beyond it concerned an expired value (evidence ledger E-085).
    """
    live = [
        belief
        for belief in oracle.state_as_of(at).values()
        if belief.subject == subject
        and belief.attribute == attribute
        and belief.superseded_by is None
    ]
    if not live:
        return frozenset()
    latest = max(live, key=lambda b: (b.valid_from, b.recorded_at, b.belief_id))
    return frozenset({latest.value})


def consolidation_answerable(events: Iterable[Any], cases: Iterable[Any]) -> dict[str, bool]:
    """``consolidated_values`` for many cases in one pass over the history.

    Equivalent to asking the oracle per case (tests check this), but sweeps the
    events once in transaction order instead of rebuilding state per question,
    which is what makes the bound cheap enough to verify on every test run.
    """
    from .model import Operation

    ordered = sorted(events, key=lambda e: (e.recorded_at, e.event_id))
    pending = sorted(cases, key=lambda c: c.transaction_at)
    live: dict[str, Any] = {}
    out: dict[str, bool] = {}
    index = 0
    for case in pending:
        while index < len(ordered) and ordered[index].recorded_at <= case.transaction_at:
            event = ordered[index]
            if event.operation is Operation.INGEST:
                live[event.belief_id] = event
            elif event.operation is Operation.SUPERSEDE:
                live.pop(event.target_id, None)
            elif event.operation is Operation.PURGE:
                live.pop(event.belief_id, None)
            index += 1
        candidates = [e for e in live.values()
                      if e.subject == case.subject and e.attribute == case.attribute]
        kept = (
            {max(candidates, key=lambda e: (e.valid_from, e.recorded_at, e.belief_id)).value}
            if candidates else set()
        )
        expected = set(case.expected_values)
        out[case.case_id] = bool(expected) and expected <= kept
    return out
