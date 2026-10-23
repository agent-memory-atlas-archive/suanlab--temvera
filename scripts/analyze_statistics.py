"""Cluster-aware intervals and paired tests for the main-grid comparisons.

The paper's Wilson intervals treat the 484 cases as independent, but cases share
the 20 histories (cells) they were asked of. This script, deterministic and
offline, adds what an experimental reviewer asks for:

* a cluster bootstrap that resamples whole cells (seeded), for each rate;
* exact McNemar tests on the paired cases two configurations share, Holm-adjusted
  over a family of comparisons declared below, with a cluster-bootstrap interval
  for each paired difference;
* an equivalence test (TOST, margin 0.10, cluster-bootstrap 90% interval) for
  the one claim of *no* difference: Mem0 and Graphiti at k=1;
* Fisher's exact test for the correction result, whose groups are not paired.

    python scripts/analyze_statistics.py
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

from temvera.reanalysis import (
    _score_truncated,
    cell_key,
    load_run,
    load_transcript,
    matched_cells,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_corrections import classify  # noqa: E402

RUNS = ROOT / "experiments" / "runs"
GRID = (
    "external-mem0-grid-v2",
    "external-langmem-v1",
    "external-graphiti-hybrid-v1",
    "external-cognee-chunks-grid-v3",
    "external-hindsight-recall-v1",
    "external-cognee-grid-v1",
    "external-hindsight-reflect-v1",
)
NAMES = dict(zip(GRID, ("Mem0", "LangMem", "Graphiti", "Cognee chunks",
                        "Hindsight recall", "Cognee graph", "Hindsight reflect")))
RESAMPLES = 4000
SEED = 7
MARGIN = 0.10

# The comparisons the paper's conclusions rest on, declared here once; Holm's
# adjustment is over exactly this family.
FAMILY = (
    ("consolidating vs retaining, valid time", "external-mem0-grid-v2",
     "external-graphiti-hybrid-v1", "valid_time"),
    ("consolidating vs retaining, valid time", "external-langmem-v1",
     "external-cognee-chunks-grid-v3", "valid_time"),
    ("consolidating vs retaining, transaction-scoped", "external-mem0-grid-v2",
     "external-graphiti-hybrid-v1", "transaction_as_of"),
    ("reader vs reader, valid time", "external-cognee-grid-v1",
     "external-hindsight-reflect-v1", "valid_time"),
    ("reader vs its own retrieval layer, valid time", "external-cognee-grid-v1",
     "external-cognee-chunks-grid-v3", "valid_time"),
    ("current release vs measured, transaction-scoped", "external-mem0-grid-v2",
     "external-mem0-grid-latest-v1", "transaction_as_of"),
)

_cache: dict[str, list[dict]] = {}


def rows(run: str) -> list[dict]:
    if run not in _cache:
        _cache[run] = [r for r in load_transcript(RUNS / run) if r.get("system") != "oracle"]
    return _cache[run]


def cells() -> set[tuple]:
    return matched_cells(*(load_run(RUNS / r) for r in GRID))


def outcomes(run: str, category: str, k: int | None = None) -> dict[tuple, bool]:
    """(cell, case_id) -> exact, over the matched cells."""
    keep = cells()
    return {(cell_key(r), r["case_id"]): (bool(r["exact"]) if k is None
                                          else _score_truncated(r, k))
            for r in rows(run) if r["category"] == category and cell_key(r) in keep}


def _by_cell(values: dict[tuple, float]) -> dict[tuple, list[float]]:
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for (cell, _), value in sorted(values.items()):
        grouped[cell].append(value)
    return grouped


def cluster_interval(values: dict[tuple, float], level: float = 0.95) -> tuple[float, float]:
    """Percentile interval of the case-weighted mean, resampling whole cells."""
    grouped = _by_cell(values)
    keys = sorted(grouped)
    rng = random.Random(SEED)
    means = []
    for _ in range(RESAMPLES):
        picked = [grouped[keys[rng.randrange(len(keys))]] for _ in keys]
        total = sum(len(g) for g in picked)
        means.append(sum(sum(g) for g in picked) / total if total else 0.0)
    means.sort()
    tail = (1 - level) / 2
    return means[int(tail * RESAMPLES)], means[int((1 - tail) * RESAMPLES) - 1]


def cluster_effects(a: dict[tuple, bool], b: dict[tuple, bool], by: str = "cell") -> list[tuple[int, int]]:
    """Per cluster: (sum of paired differences, pairs). ``by`` is ``cell`` (the
    20 histories) or ``seed`` (the 5 seeds the histories were generated from)."""
    grouped: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for key in sorted(set(a) & set(b)):
        cell = key[0]
        cluster = cell if by == "cell" else (cell[3],)
        grouped[cluster][0] += int(a[key]) - int(b[key])
        grouped[cluster][1] += 1
    return [tuple(v) for _, v in sorted(grouped.items())]


def sign_flip_p(effects: list[tuple[int, int]]) -> float:
    """Exact two-sided sign-flip permutation p of the case-weighted mean paired
    difference, flipping whole clusters."""
    sums = [d for d, _ in effects]
    total = sum(n for _, n in effects)
    observed = abs(sum(sums)) / total
    extreme = 0
    count = 1 << len(sums)
    for mask in range(count):
        stat = sum(-d if mask >> i & 1 else d for i, d in enumerate(sums))
        extreme += abs(stat) / total >= observed - 1e-12
    return extreme / count


def mcnemar_exact(a: dict[tuple, bool], b: dict[tuple, bool]) -> tuple[int, int, float]:
    """Discordant counts (a only, b only) and the two-sided exact p-value."""
    shared = sorted(set(a) & set(b))
    only_a = sum(a[key] and not b[key] for key in shared)
    only_b = sum(b[key] and not a[key] for key in shared)
    n = only_a + only_b
    if n == 0:
        return only_a, only_b, 1.0
    tail = sum(comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2 ** n
    return only_a, only_b, min(1.0, 2 * tail)


def holm(pvalues: list[float]) -> list[float]:
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(pvalues) - rank) * pvalues[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def fisher_two_sided(a: int, n1: int, c: int, n2: int) -> float:
    """Fisher's exact test for successes a/n1 against c/n2."""
    total, hits = n1 + n2, a + c

    def prob(x: int) -> float:
        return comb(n1, x) * comb(n2, hits - x) / comb(total, hits)

    observed = prob(a)
    low, high = max(0, hits - n2), min(hits, n1)
    return min(1.0, sum(prob(x) for x in range(low, high + 1)
                        if prob(x) <= observed * (1 + 1e-9)))


def analyse() -> dict:
    report: dict = {"resamples": RESAMPLES, "seed": SEED, "cells": len(cells()),
                    "rates": {}, "family": [], "equivalence": {}, "corrections": {}}
    for run in GRID + ("external-mem0-grid-latest-v1",):
        for category in ("valid_time", "transaction_as_of"):
            values = outcomes(run, category)
            low, high = cluster_interval({k: float(v) for k, v in values.items()})
            report["rates"][f"{run}:{category}"] = {
                "exact": sum(values.values()), "n": len(values),
                "rate": sum(values.values()) / len(values),
                "cluster_low": low, "cluster_high": high,
            }
    raw = []
    for label, left, right, category in FAMILY:
        a, b = outcomes(left, category), outcomes(right, category)
        only_a, only_b, p = mcnemar_exact(a, b)
        shared = sorted(set(a) & set(b))
        diff = {key: float(a[key]) - float(b[key]) for key in shared}
        low, high = cluster_interval(diff)
        raw.append(p)
        cells_effect = cluster_effects(a, b, "cell")
        seeds_effect = cluster_effects(a, b, "seed")
        sign = 1 if sum(d for d, _ in cells_effect) > 0 else -1
        report["family"].append({
            "histories": len(cells_effect), "seeds": len(seeds_effect),
            "histories_same_sign": sum(d * sign > 0 for d, _ in cells_effect),
            "seeds_same_sign": sum(d * sign > 0 for d, _ in seeds_effect),
            "p_permutation_histories": sign_flip_p(cells_effect),
            "p_permutation_seeds": sign_flip_p(seeds_effect),
            "comparison": label, "left": left, "right": right, "category": category,
            "pairs": len(shared), "left_only": only_a, "right_only": only_b,
            "difference": sum(diff.values()) / len(diff), "cluster_low": low,
            "cluster_high": high, "p_mcnemar": p,
        })
    for entry, adjusted in zip(report["family"], holm(raw)):
        entry["p_holm"] = adjusted
    a = outcomes("external-mem0-grid-v2", "valid_time", k=1)
    b = outcomes("external-graphiti-hybrid-v1", "valid_time", k=1)
    shared = sorted(set(a) & set(b))
    diff = {key: float(a[key]) - float(b[key]) for key in shared}
    low, high = cluster_interval(diff, level=0.90)
    report["equivalence"] = {
        "comparison": "Mem0 vs Graphiti, valid time, k=1", "margin": MARGIN,
        "difference": sum(diff.values()) / len(diff), "low90": low, "high90": high,
        "equivalent": -MARGIN < low and high < MARGIN,
        "margins": {str(m): (-m < low and high < m) for m in (0.025, 0.05, 0.10)},
    }
    hits = classify("external-corrections-mem0-v1")
    corrected, uncorrected = hits["present_corrected"], hits["present_uncorrected"]
    report["corrections"] = {
        "comparison": "Mem0 0.1.118: present value answered, corrected vs uncorrected",
        "corrected": [sum(corrected), len(corrected)],
        "uncorrected": [sum(uncorrected), len(uncorrected)],
        "p_fisher": fisher_two_sided(sum(corrected), len(corrected),
                                     sum(uncorrected), len(uncorrected)),
    }
    return report


def main() -> int:
    report = analyse()
    for key, value in report["rates"].items():
        print(f"{key:58s} {value['exact']:4d}/{value['n']:<4d} {value['rate']:.3f} "
              f"cluster [{value['cluster_low']:.3f}, {value['cluster_high']:.3f}]")
    for entry in report["family"]:
        print(f"{entry['comparison']:48s} {NAMES.get(entry['left'], entry['left'])} vs "
              f"{NAMES.get(entry['right'], entry['right'])}: diff {entry['difference']:+.3f} "
              f"[{entry['cluster_low']:+.3f}, {entry['cluster_high']:+.3f}] "
              f"discordant {entry['left_only']}/{entry['right_only']} "
              f"p {entry['p_mcnemar']:.2g} holm {entry['p_holm']:.2g} | same sign in "
              f"{entry['histories_same_sign']}/{entry['histories']} histories, "
              f"{entry['seeds_same_sign']}/{entry['seeds']} seeds; permutation p "
              f"{entry['p_permutation_histories']:.2g} (histories), "
              f"{entry['p_permutation_seeds']:.3g} (seeds)")
    eq = report["equivalence"]
    print(f"{eq['comparison']}: diff {eq['difference']:+.3f} 90% "
          f"[{eq['low90']:+.3f}, {eq['high90']:+.3f}] margin {eq['margin']} "
          f"equivalent={eq['equivalent']} by margin {eq['margins']}")
    print(f"{report['corrections']['comparison']}: Fisher p "
          f"{report['corrections']['p_fisher']:.2g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
