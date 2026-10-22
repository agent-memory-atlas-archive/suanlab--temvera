"""Tie every number printed in the paper to a computation over the sealed runs.

`recompute_paper_numbers.py` prints the tables for a human to compare by eye.
That is not a check: a 2026-08 audit found seven figures in one subsection had
drifted onto runs the paper does not use -- including a Mem0 run the same
subsection describes as corrupted and re-run -- because nothing tied the prose
back to an artifact.

Each claim below carries the value **as printed in `paper/main.tex`** and a
function that recomputes it from a sealed run. A claim fails if either half
moves: if the computation stops matching, or if the number no longer appears in
the paper. The second half is what catches a figure being edited by hand.

Aggregation is declared per claim, never inferred. The same audit briefly
"corrected" five correct numbers because it checked them against case-weighted
rates when the paragraph reported cell-averaged ones, so `micro` and `macro`
are separate functions here and every claim names which it means.

    python scripts/verify_paper_claims.py           # verify
    python scripts/verify_paper_claims.py --list    # show every claim
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from temvera.reanalysis import (
    category_counts,
    cell_key,
    k_sweep,
    load_run,
    load_transcript,
    macro,
    matched_cells,
    overall_counts,
)

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
PAPER = ROOT / "paper" / "main.tex"

_transcripts: dict[str, list] = {}
_results: dict[str, dict] = {}


def tr(run: str) -> list:
    if run not in _transcripts:
        _transcripts[run] = load_transcript(RUNS / run)
    return _transcripts[run]


def res(run: str) -> dict:
    if run not in _results:
        _results[run] = json.loads((RUNS / run / "results.json").read_text(encoding="utf-8"))
    return _results[run]


def rows_of(run: str) -> list:
    data = res(run)
    rows = data["rows"] if isinstance(data, dict) else data
    return [r for r in rows if r.get("system") != "oracle"]


def micro(run: str, category: str | None = None, cells=None) -> float:
    """Case-weighted rate: every question counts once."""
    if category is None:
        return overall_counts(tr(run), cells=cells).rate
    return category_counts(tr(run), cells=cells)[category].rate


def micro_counts(run: str, category: str | None = None, cells=None):
    if category is None:
        p = overall_counts(tr(run), cells=cells)
    else:
        p = category_counts(tr(run), cells=cells)[category]
    return p.successes, p.total


def macro_cat(run: str, category: str, cells=None) -> float:
    """Cell-averaged rate: every grid cell counts once, whatever its size."""
    per: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for row in tr(run):
        if row["category"] != category or (cells and cell_key(row) not in cells):
            continue
        entry = per[cell_key(row)]
        entry[0] += row["exact"]
        entry[1] += 1
    return sum(h / n for h, n in per.values()) / len(per)


def macro_metric(run: str, metric: str) -> float:
    return macro(rows_of(run), metric)


def internal(system: str, metric: str, profile: str | None = None) -> float:
    rows = [
        r for r in res("lifecycle-grid-robust-v1")
        if r["system"] == system and (profile is None or r["profile"] == profile)
    ]
    return macro(rows, metric)


def telemetry(run: str, *path: str) -> float:
    node = res(run)["telemetry"]
    for key in path:
        node = node[key]
    return node


def longmem(run: str, qtype: str, *, drop_abstention: bool = False) -> float:
    rows = [r for r in res(run)["per_instance"] if r["question_type"] == qtype]
    if drop_abstention:
        rows = [r for r in rows if not str(r["question_id"]).endswith("_abs")]
    return sum(r["token_recall"] for r in rows) / len(rows)


def residual(run: str, system: str) -> int:
    for report in res(run)["reports"]:
        if report["system"] == system:
            return report["total_residual"]
    raise KeyError(system)


def rank1_names_subject(run: str) -> float:
    """Share of cases whose top-ranked returned item names the queried subject.

    `answer` joins the returned items with ' | ' in rank order, so rank 1 is the
    first segment. The queried subject is the possessive in the question stem.
    """
    pattern = re.compile(r"^What (?:is|was) ([A-Z][\w'-]*)'s ")
    hits = total = 0
    for row in tr(run):
        match = pattern.match(row["query"])
        segments = [s.strip() for s in row["answer"].split("|") if s.strip()]
        if not match or not segments:
            continue
        total += 1
        hits += match.group(1) in segments[0]
    return 100 * hits / total


def lost_history_share(run: str) -> float:
    """Non-exact cases that returned a stale value with the expected one absent."""
    wrong = [r for r in tr(run) if not r["exact"]]
    lost = [r for r in wrong if r["present_stale"] and not r["present_expected"]]
    return 100 * len(lost) / len(wrong)


_REPLICATES = {
    "mem0": ("external-mem0-grid-v2", "variance-mem0-r1-v1", "variance-mem0-r2-v1",
             "variance-mem0-r3-v1"),
    "graphiti": ("external-graphiti-hybrid-v1", "variance-graphiti-r1-v1",
                 "variance-graphiti-r2-v1", "variance-graphiti-r3-v1"),
}


def replicate(system: str, what: str) -> float:
    """Over the replicate runs' cells: the overall hits (identical across all
    four runs, else -1), the case count, or the largest per-category shift."""
    runs = _REPLICATES[system]
    keep = {(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in tr(runs[1])}

    def counts(run, category):
        rows = [r for r in tr(run) if (r["profile"], r["entities"], r["revisions"],
                                       r["seed"]) in keep
                and (category is None or r["category"] == category)]
        return sum(bool(r["exact"]) for r in rows), len(rows)

    if what == "hits":
        hits = {counts(run, None)[0] for run in runs}
        return float(hits.pop()) if len(hits) == 1 else -1.0
    if what == "cases":
        return float(counts(runs[0], None)[1])
    shifts = []
    for category in ("transaction_as_of", "valid_time", "expiry_boundary", "purge"):
        hits = [counts(run, category)[0] for run in runs]
        shifts.append(max(hits) - min(hits))
    return float(max(shifts))


def _backbone_max_shift() -> float:
    """Largest change in correct answers, over categories and both systems."""
    pairs = (("external-mem0-grid-v2", "external-mem0-grid-gpt4o-v1"),
             ("external-graphiti-hybrid-v1", "external-graphiti-hybrid-gpt4o-v1"))
    shifts = []
    for mini, big in pairs:
        for category in (None, "transaction_as_of", "valid_time", "expiry_boundary", "purge"):
            (a, n), (b, m) = micro_counts(mini, category, cells()), micro_counts(big, category, cells())
            assert n == m, "the two backbones were scored on different cases"
            shifts.append(abs(a - b))
    return float(max(shifts))


def _expiry_cases() -> float:
    """Expiry cases on the matched cells, identical for every configuration."""
    counts = {micro_counts(r, "expiry_boundary", cells())[1] for r in GRID}
    assert len(counts) == 1, f"expiry denominators differ: {counts}"
    return float(counts.pop())


def _wilson_zero_of(n: float) -> float:
    from temvera.reanalysis import Proportion

    return Proportion(0, int(n)).wilson()[1]


GRID = (
    "external-mem0-grid-v2",
    "external-langmem-v1",
    "external-graphiti-hybrid-v1",
    "external-cognee-chunks-grid-v3",
    "external-hindsight-recall-v1",
    "external-cognee-grid-v1",
    "external-hindsight-reflect-v1",
)
_cells = None


def cells():
    global _cells
    if _cells is None:
        _cells = matched_cells(*(load_run(RUNS / r) for r in GRID))
    return _cells


@dataclass(frozen=True)
class Claim:
    where: str
    label: str
    printed: str
    compute: Callable[[], float]
    tol: float = 0.0006
    near: str | None = None
    window: int = 200
    after: str | None = None
    """Distinctive phrase the number must appear within 200 characters of.

    Document-wide presence is not enough. The drift this script exists to catch
    left every number still present somewhere -- the tables were right and the
    prose beside them was wrong -- so a prose claim anchors to its own sentence
    and a table claim to its own row label.
    """


def _grid_claims() -> list[Claim]:
    spec = {
        "Mem0": ("external-mem0-grid-v2", "0.603", "0.364", "0.044"),
        "LangMem": ("external-langmem-v1", "0.576", "0.323", "0.133"),
        "Graphiti": ("external-graphiti-hybrid-v1", "0.196", "0.000", "0.022"),
        "Cognee chunks": ("external-cognee-chunks-grid-v3", "0.194", "0.000", "0.022"),
        "Hindsight recall": ("external-hindsight-recall-v1", "0.194", "0.000", "0.022"),
        "Cognee graph-compl.": ("external-cognee-grid-v1", "0.930", "0.985", "0.622"),
        "Hindsight reflect": ("external-hindsight-reflect-v1", "0.407", "0.344", "0.311"),
    }
    out = []
    for name, (run, overall, valid, purge) in spec.items():
        out += [
            Claim("Tab.2/3", f"{name} overall (micro)", overall, lambda r=run: micro(r, cells=cells())),
            Claim("Tab.2/3", f"{name} valid_time (micro)", valid,
                  lambda r=run: micro(r, "valid_time", cells())),
            Claim("Tab.2/3", f"{name} purge (micro)", purge, lambda r=run: micro(r, "purge", cells())),
        ]
    return out


CLAIMS: list[Claim] = [
    # -- Table 1, internal baselines: cell-averaged over 270 cells --------------
    Claim("Tab.1", "oracle exact (macro)", "1.000", lambda: internal("oracle", "exact_state_accuracy")),
    Claim("Tab.1", "last-write-wins exact", "0.603", lambda: internal("last_write_wins", "exact_state_accuracy")),
    Claim("Tab.1", "last-write-wins recall", "0.603", lambda: internal("last_write_wins", "evidence_recall")),
    Claim("Tab.1", "last-write-wins stale", "0.397", lambda: internal("last_write_wins", "stale_use_rate")),
    Claim("Tab.1", "BM25@1 exact", "0.576", lambda: internal("bm25_at_1", "exact_state_accuracy")),
    Claim("Tab.1", "BM25@1 stale", "0.424", lambda: internal("bm25_at_1", "stale_use_rate")),
    Claim("Tab.1", "append-only exact", "0.272", lambda: internal("append_only", "exact_state_accuracy")),
    Claim("Tab.1", "append-only recall", "0.915", lambda: internal("append_only", "evidence_recall")),
    Claim("Tab.1", "append-only stale", "0.624", lambda: internal("append_only", "stale_use_rate")),
    Claim("5.1", "append-only exact, high churn", "0.255",
          lambda: internal("append_only", "exact_state_accuracy", "high_churn"),
          near="Under the high-churn profile"),
    Claim("5.1", "append-only stale, high churn", "0.662",
          lambda: internal("append_only", "stale_use_rate", "high_churn"),
          near="Under the high-churn profile"),
    # -- 5.2 prose: the subsection the audit found had drifted ------------------
    Claim("5.2", "Mem0 transaction_as_of (micro)", "0.952",
          lambda: micro("external-mem0-grid-v2", "transaction_as_of", cells()),
          near="transaction-scoped current queries"),
    Claim("5.2", "Mem0 valid_time (micro)", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="much weaker on historical valid time"),
    Claim("5.2", "Mem0 lost-history share of non-exact", "88.5",
          lambda: lost_history_share("external-mem0-grid-v2"), 0.06,
          near="Of its non-exact"),
    Claim("5.2", "Graphiti evidence recall (macro)", "0.937",
          lambda: macro_metric("external-graphiti-hybrid-v1", "evidence_recall"),
          near="It reaches"),
    Claim("5.2", "Graphiti rank-1 names subject, %", "91.3",
          lambda: rank1_names_subject("external-graphiti-hybrid-v1"), 0.06,
          near="naming the queried subject at rank"),
    Claim("5.2", "Mem0 valid_time at k=1 (micro)", "0.379",
          lambda: k_sweep(tr("external-mem0-grid-v2"), budgets=(1,), cells=cells())[1]
          ["by_category"]["valid_time"]["rate"],
          near="statistically indistinguishable"),
    Claim("5.2", "Graphiti valid_time at k=1 (micro)", "0.354",
          lambda: k_sweep(tr("external-graphiti-hybrid-v1"), budgets=(1,), cells=cells())[1]
          ["by_category"]["valid_time"]["rate"],
          near="statistically indistinguishable"),
    Claim("Tab.2", "Mem0 exact at k=1 (micro)", "0.630",
          lambda: k_sweep(tr("external-mem0-grid-v2"), budgets=(1,), cells=cells())[1]["overall"]["rate"]),
    Claim("Tab.2", "Mem0 evidence recall (macro)", "0.666",
          lambda: macro_metric("external-mem0-grid-v2", "evidence_recall")),
    Claim("Tab.2", "Mem0 stale-use (macro)", "0.356",
          lambda: macro_metric("external-mem0-grid-v2", "stale_use_rate")),
    # -- 5.2 filter paragraph: cell-averaged throughout -------------------------
    Claim("5.2f", "Graphiti cosine exact (macro)", "0.224",
          lambda: macro_metric("external-graphiti-grid-v1", "exact_state_accuracy"),
          near="raises exact from"),
    Claim("5.2f", "Graphiti filtered exact (macro)", "0.318",
          lambda: macro_metric("external-graphiti-filtered-v2", "exact_state_accuracy"),
          near="raises exact from"),
    Claim("5.2f", "Graphiti cosine stale-use (macro)", "0.561",
          lambda: macro_metric("external-graphiti-grid-v1", "stale_use_rate"),
          near="cuts stale-use"),
    Claim("5.2f", "Graphiti filtered stale-use (macro)", "0.360",
          lambda: macro_metric("external-graphiti-filtered-v2", "stale_use_rate"),
          near="cuts stale-use"),
    Claim("5.2f", "Graphiti cosine recall (macro)", "0.873",
          lambda: macro_metric("external-graphiti-grid-v1", "evidence_recall"),
          near="collapses evidence recall from"),
    Claim("5.2f", "Graphiti filtered valid_time (macro)", "0.093",
          lambda: macro_cat("external-graphiti-filtered-v2", "valid_time"),
          near="valid-time remains"),
    Claim("5.2f", "Graphiti filtered valid_time (micro)", "0.114",
          lambda: micro("external-graphiti-filtered-v2", "valid_time"),
          near="the case-weighted valid-time is"),
    # -- 5.2 extractor comparison: 4 matched cells, cell-averaged ---------------
    Claim("5.2x", "gpt-4o-mini valid_time (macro)", "0.111",
          lambda: macro_cat("external-graphiti-filtered-v2", "valid_time", _x_cells()),
          near="valid-time is unchanged"),
    Claim("5.2x", "gpt-4o valid_time (macro)", "0.111",
          lambda: macro_cat("external-graphiti-filtered-gpt4o-v2", "valid_time", _x_cells()),
          near="valid-time is unchanged"),
    Claim("5.2x", "gpt-4o-mini transaction_as_of (macro)", "0.514",
          lambda: macro_cat("external-graphiti-filtered-v2", "transaction_as_of", _x_cells()),
          near="improves ("),
    Claim("5.2x", "gpt-4o transaction_as_of (macro)", "0.625",
          lambda: macro_cat("external-graphiti-filtered-gpt4o-v2", "transaction_as_of", _x_cells()),
          near="improves ("),
    Claim("5.2x", "gpt-4o-mini purge (macro)", "0.296",
          lambda: macro_cat("external-graphiti-filtered-v2", "purge", _x_cells()),
          near="purge degrades"),
    Claim("5.2x", "gpt-4o purge (macro)", "0.176",
          lambda: macro_cat("external-graphiti-filtered-gpt4o-v2", "purge", _x_cells()),
          near="purge degrades"),
    # -- 5.3 deletion ----------------------------------------------------------
    Claim("5.3", "NL instruction, reference impl.", "3", lambda: residual("purge-residual-v3-nl", "temvera"), 0.5,
          near="the reference implementation"),
    Claim("5.3", "NL instruction, Mem0", "15", lambda: residual("purge-residual-v3-nl", "mem0"), 0.5,
          near="the reference implementation"),
    Claim("5.3", "NL instruction, Graphiti", "18", lambda: residual("purge-residual-v3-nl", "graphiti"), 0.5,
          near="the reference implementation"),
    Claim("5.3", "native API, Mem0", "12", lambda: residual("purge-residual-v3-api", "mem0"), 0.5,
          near="Mem0 falls to"),
    Claim("5.3", "native API, Graphiti", "3", lambda: residual("purge-residual-v3-api", "graphiti"), 0.5,
          near="Graphiti falls to"),
    # -- 5.5 cost and latency --------------------------------------------------
    Claim("Tab.4", "Mem0 ingest samples", "1035", lambda: telemetry("scale-cost-mem0-v1", "ingest_latency", "n"), 0.5),
    Claim("Tab.4", "Mem0 query samples", "949", lambda: telemetry("scale-cost-mem0-v1", "query_latency", "n"), 0.5),
    Claim("Tab.4", "Mem0 ingest mean", "4.733",
          lambda: telemetry("scale-cost-mem0-v1", "ingest_latency", "mean_s")),
    Claim("Tab.4", "Mem0 query mean", "0.300",
          lambda: telemetry("scale-cost-mem0-v1", "query_latency", "mean_s")),
    Claim("Tab.4", "Mem0 ingest p50", "4.41",
          lambda: telemetry("scale-cost-mem0-v1", "ingest_latency", "p50_s"), 0.006),
    Claim("Tab.4", "Mem0 ingest p95", "7.04",
          lambda: telemetry("scale-cost-mem0-v1", "ingest_latency", "p95_s"), 0.006),
    Claim("Tab.4", "chat calls", "2036",
          lambda: telemetry("scale-cost-mem0-v1", "usage", "gpt-4o-mini", "calls"), 0.5),
    Claim("Tab.4", "chat cost USD", "0.5310",
          lambda: telemetry("scale-cost-mem0-v1", "usage", "gpt-4o-mini", "cost_usd"), 0.00006),
    Claim("Tab.4", "embedding cost USD", "0.0009",
          lambda: telemetry("scale-cost-mem0-v1", "usage", "text-embedding-3-small", "cost_usd"),
          0.00006),
    Claim("5.5", "Cognee ingest mean", "0.65",
          lambda: telemetry("external-cognee-grid-v1", "ingest_latency", "mean_s"), 0.006,
          near="text and averages"),
    Claim("5.5", "Cognee query mean", "6.91",
          lambda: telemetry("external-cognee-grid-v1", "query_latency", "mean_s"), 0.006,
          near="while its query path averages"),
    Claim("5.5", "Cognee chunks query mean", "4.56",
          lambda: telemetry("external-cognee-chunks-grid-v3", "query_latency", "mean_s"), 0.006,
          near="graph build runs at the first query of each checkpoint"),
    Claim("5.5", "Cognee reader share of query time, s", "2.4",
          lambda: telemetry("external-cognee-grid-v1", "query_latency", "mean_s")
          - telemetry("external-cognee-chunks-grid-v3", "query_latency", "mean_s"), 0.06,
          near="textsc{chunks}, so roughly"),
    Claim("5.5", "scale-cost e8 synthetic value tokens, %", "19",
          lambda: _scale_cost_fallback_pct(8), 0.5,
          near="than the natural-name relabelling holds"),
    Claim("5.4", "reader expiry, best of the two (micro)", "0.125",
          lambda: max(micro(r, "expiry_boundary", cells())
                      for r in ("external-cognee-grid-v1", "external-hindsight-reflect-v1")),
          near="Expiry stays low for both readers"),
    Claim("5.4", "expiry cases per configuration", "16",
          lambda: _expiry_cases(), 0.5, near="Expiry stays low for both readers"),
    Claim("Fig.1", "expiry cases per configuration", "16",
          lambda: _expiry_cases(), 0.5, near="Expiry rests on"),
    Claim("Fig.1", "Wilson upper bound of 0 of 16", "0.19",
          lambda: _wilson_zero_of(_expiry_cases()), 0.006, near="Expiry rests on"),
    # -- second backbone: Mem0 and Graphiti grid on gpt-4o (case-weighted) -----
    Claim("5.2", "largest per-category change, gpt-4o vs mini (cases)", "2",
          lambda: _backbone_max_shift(), 0.5, near="otherwise unchanged, moves no category"),
    Claim("5.2", "Mem0 overall, mini (micro)", "0.603",
          lambda: micro("external-mem0-grid-v2", cells=cells()), near="Mem0 goes\nfrom"),
    Claim("5.2", "Mem0 overall, gpt-4o (micro)", "0.607",
          lambda: micro("external-mem0-grid-gpt4o-v1", cells=cells()), near="Mem0 goes\nfrom"),
    Claim("5.2", "Mem0 valid_time, mini (micro)", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="overall and from"),
    Claim("5.2", "Mem0 valid_time, gpt-4o (micro)", "0.374",
          lambda: micro("external-mem0-grid-gpt4o-v1", "valid_time", cells()),
          near="overall and from"),
    Claim("5.2", "Graphiti overall, mini (micro)", "0.196",
          lambda: micro("external-graphiti-hybrid-v1", cells=cells()), near="Graphiti from"),
    Claim("5.2", "Graphiti overall, gpt-4o (micro)", "0.194",
          lambda: micro("external-graphiti-hybrid-gpt4o-v1", cells=cells()), near="Graphiti from"),
    Claim("5.2", "Graphiti valid_time hits, gpt-4o", "0",
          lambda: micro_counts("external-graphiti-hybrid-gpt4o-v1", "valid_time", cells())[0],
          0.5, near="on valid time it answers"),
    Claim("5.2", "Graphiti valid_time hits, mini", "0",
          lambda: micro_counts("external-graphiti-hybrid-v1", "valid_time", cells())[0],
          0.5, near="on valid time it answers"),
    Claim("5.2", "Graphiti valid_time cases", "195",
          lambda: micro_counts("external-graphiti-hybrid-gpt4o-v1", "valid_time", cells())[1],
          0.5, near="on valid time it answers"),
    # -- replicates: four cells, cited run + three repeats (case counts) -------
    Claim("5.2", "Mem0 overall hits, identical in all four runs", "60",
          lambda: replicate("mem0", "hits"), 0.5, near="reproduce the cited runs' overall"),
    Claim("5.2", "Graphiti overall hits, identical in all four runs", "20",
          lambda: replicate("graphiti", "hits"), 0.5, near="reproduce the cited runs' overall"),
    Claim("5.2", "cases in the four replicate cells", "97",
          lambda: replicate("mem0", "cases") if replicate("mem0", "cases")
          == replicate("graphiti", "cases") else -1.0, 0.5,
          near="reproduce the cited runs' overall"),
    Claim("5.2", "largest per-category shift across replicates (cases)", "1",
          lambda: max(replicate("mem0", "shift"), replicate("graphiti", "shift")), 0.5,
          near="no category by more than", after="Repeated runs agree"),
    # -- abstract: figures printed only in the abstract and tables -------------
    Claim("abs", "LangMem transaction_as_of (micro)", "0.890",
          lambda: micro("external-langmem-v1", "transaction_as_of", cells()),
          near="queries well (0.952 and"),
    Claim("abs", "Cognee reader valid_time hits", "192",
          lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[0], 0.5,
          near="An LLM reader recovers it for Cognee"),
    Claim("abs", "Cognee reader valid_time cases", "195",
          lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[1], 0.5,
          near="An LLM reader recovers it for Cognee"),
    Claim("abs", "Hindsight reader valid_time hits", "67",
          lambda: micro_counts("external-hindsight-reflect-v1", "valid_time", cells())[0], 0.5,
          near="but\nnot for Hindsight"),
    Claim("abs", "Mem0 valid_time (micro)", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="historical ones poorly"),
    Claim("abs", "LangMem valid_time (micro)", "0.323",
          lambda: micro("external-langmem-v1", "valid_time", cells()),
          near="historical ones poorly"),
    Claim("abs", "Cognee chunks valid_time, as the other two retaining stores", "0.000",
          lambda: micro("external-cognee-chunks-grid-v3", "valid_time", cells()),
          near="three independent implementations score"),
    # -- 5.x scale, prose and the withdrawn first sweep ------------------------
    Claim("5.scale", "questions per system at 8 entities", "623",
          lambda: scale_rate("mem0", 8, "questions"), 0.5, near="three seeds per scale:"),
    Claim("5.scale", "questions per system at 32 entities", "2{,}507",
          lambda: scale_rate("mem0", 32, "questions"), 0.5, near="three seeds per scale:"),
    Claim("5.scale", "questions per system at 128 entities", "10{,}037",
          lambda: scale_rate("mem0", 128, "questions"), 0.5, near="three seeds per scale:"),
    Claim("5.scale", "Graphiti tx hits, nothing to filter, 128", "1{,}129",
          lambda: graphiti_tx_split(128, False, 0), 0.5, near="On those it answers"),
    Claim("5.scale", "Graphiti tx cases, nothing to filter, 128", "1{,}152",
          lambda: graphiti_tx_split(128, False, 1), 0.5, near="On those it answers"),
    Claim("5.scale", "Graphiti tx hits, superseded value present, 128", "22",
          lambda: graphiti_tx_split(128, True, 0), 0.5, near="on the rest,"),
    Claim("5.scale", "Graphiti tx cases, superseded value present, 128", "3{,}456",
          lambda: graphiti_tx_split(128, True, 1), 0.5, near="on the rest,"),
    Claim("5.scale", "Graphiti recall 32, Wilson low", "0.970",
          lambda: scale_rate("graphiti", 32, "recall", 0), near="recall falls at 128 entities"),
    Claim("5.scale", "Graphiti recall 32, Wilson high", "0.983",
          lambda: scale_rate("graphiti", 32, "recall", 1), near="recall falls at 128 entities"),
    Claim("5.scale", "Graphiti recall 128, Wilson low", "0.774",
          lambda: scale_rate("graphiti", 128, "recall", 0), near="recall falls at 128 entities"),
    Claim("5.scale", "Graphiti recall 128, Wilson high", "0.791",
          lambda: scale_rate("graphiti", 128, "recall", 1), near="recall falls at 128 entities"),
    Claim("5.scale", "Mem0 tx 32, Wilson low", "0.942",
          lambda: scale_rate("mem0", 32, "transaction_as_of", 0), near="transaction-scoped accuracy falls from"),
    Claim("5.scale", "Mem0 tx 32, Wilson high", "0.966",
          lambda: scale_rate("mem0", 32, "transaction_as_of", 1), near="transaction-scoped accuracy falls from"),
    Claim("5.scale", "Mem0 tx 128, Wilson low", "0.894",
          lambda: scale_rate("mem0", 128, "transaction_as_of", 0), near="transaction-scoped accuracy falls from"),
    Claim("5.scale", "Mem0 tx 128, Wilson high", "0.911",
          lambda: scale_rate("mem0", 128, "transaction_as_of", 1), near="transaction-scoped accuracy falls from"),
    Claim("6", "first sweep: synthetic values at 8 entities, %", "19",
          lambda: v1_fallback_pct(8), 0.5, near="silently fell back to synthetic tokens"),
    Claim("6", "first sweep: synthetic values at 32 entities, %", "55",
          lambda: v1_fallback_pct(32), 0.5, near="silently fell back to synthetic tokens"),
    Claim("6", "first sweep: synthetic values at 128 entities, %", "66",
          lambda: v1_fallback_pct(128), 0.5, near="silently fell back to synthetic tokens"),
    Claim("6", "first sweep: Graphiti exact at 8 entities", "0.117",
          lambda: v1_graphiti(8, "exact"), near="exact accuracy rising from"),
    Claim("6", "first sweep: Graphiti exact at 128 entities", "0.216",
          lambda: v1_graphiti(128, "exact"), near="exact accuracy rising from"),
    Claim("6", "first sweep: Graphiti recall at 32 entities", "0.705",
          lambda: v1_graphiti(32, "recall"), near="Graphiti's recall moves from"),
    Claim("5.5", "re-measured Mem0 ingest mean", "6.825",
          lambda: telemetry("scale-cost-mem0-v2", "ingest_latency", "mean_s"),
          near="mean ingest latency was"),
    Claim("5.5", "re-measured chat calls", "2036",
          lambda: telemetry("scale-cost-mem0-v2", "usage", "gpt-4o-mini", "calls"), 0.5,
          near="later made the same"),
    Claim("5.5", "re-measured chat cost USD", "0.528",
          lambda: telemetry("scale-cost-mem0-v2", "usage", "gpt-4o-mini", "cost_usd"), 0.0006,
          near="over essentially the same tokens"),
    Claim("5.5", "re-measured ingest/query ratio", "25",
          lambda: telemetry("scale-cost-mem0-v2", "ingest_latency", "mean_s")
          / telemetry("scale-cost-mem0-v2", "query_latency", "mean_s"), 0.5,
          near="the ingest-to-query ratio"),
    # -- 5.6 external validity -------------------------------------------------
    Claim("5.6", "knowledge-update recall", "0.724", lambda: longmem("longmemeval-e7-v2", "knowledge-update"),
          near="mean gold-token recall was knowledge-update"),
    Claim("5.6", "single-session-user recall", "0.622",
          lambda: longmem("longmemeval-e7-v2", "single-session-user"),
          near="mean gold-token recall was knowledge-update"),
    Claim("5.6", "preference recall", "0.314",
          lambda: longmem("longmemeval-e7-v2", "single-session-preference"),
          near="mean gold-token recall was knowledge-update"),
    Claim("5.6", "multi-session recall", "0.287", lambda: longmem("longmemeval-e7-v2", "multi-session"),
          near="mean gold-token recall was knowledge-update"),
    Claim("5.6", "temporal-reasoning recall", "0.221",
          lambda: longmem("longmemeval-e7-v2", "temporal-reasoning"),
          near="mean gold-token recall was knowledge-update"),
    Claim("5.6", "single-session-assistant recall", "0.151",
          lambda: longmem("longmemeval-e7-v2", "single-session-assistant"),
          near="mean gold-token recall was knowledge-update"),
    Claim("5.6", "single-session-user, abstention excluded", "0.810",
          lambda: longmem("longmemeval-e7-v2", "single-session-user", drop_abstention=True),
          near="excluding them here reorders"),
    Claim("5.6", "knowledge-update, abstention excluded", "0.794",
          lambda: longmem("longmemeval-e7-v2", "knowledge-update", drop_abstention=True),
          near="excluding them here reorders"),
    Claim("5.6", "temporal-reasoning, oracle split", "0.125",
          lambda: _matched_temporal("longmemeval-e7-v1"),
          near="temporal-reasoning in fact rises"),
    Claim("5.6", "temporal-reasoning, distractor split", "0.167",
          lambda: _matched_temporal("longmemeval-s-v1"),
          near="temporal-reasoning in fact rises"),
    # -- 4.1 claims-vs-documentation table -------------------------------------
    Claim("Tab.claims", "Graphiti valid_time beside its claim", "0.000",
          lambda: micro("external-graphiti-hybrid-v1", "valid_time", cells()),
          near="what was true at any point in time"),
    Claim("Tab.claims", "Hindsight valid_time beside its claim", "0.000",
          lambda: micro("external-hindsight-recall-v1", "valid_time", cells()),
          near="Temporal + Semantic + Entity Memory Architecture"),
    Claim("Tab.claims", "Cognee valid_time beside its claim", "0.000",
          lambda: micro("external-cognee-chunks-grid-v3", "valid_time", cells()),
          near="documents a \\texttt{forget} operation"),
    Claim("Tab.claims", "Mem0 valid_time beside its claim", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="none; ``long-term memory''"),
    Claim("Tab.claims", "LangMem valid_time beside its claim", "0.323",
          lambda: micro("external-langmem-v1", "valid_time", cells()),
          near="none; ``extracts, consolidates''"),
]

def _scale_cost_fallback_pct(entities: int) -> float:
    """Share of distinct values in scale-cost-mem0-v1 left as synthetic tokens."""
    from temvera.external_experiment import _events_for
    from temvera.nl_workload import fallback_tokens

    config = json.loads((RUNS / "scale-cost-mem0-v1" / "config.json").read_text())
    scale = next(s for s in config["scales"] if s["entities"] == entities)
    fell = total = 0
    for seed in config["seeds"]:
        counts = fallback_tokens(_events_for(seed, entities, scale["revisions"],
                                             config["profiles"][0], True,
                                             config.get("attributes", 1)))
        fell += counts["values"]
        total += counts["values_total"]
    return 100 * fell / total


# --- scale sweep (Section 5.x) -------------------------------------------------

_SCALE = {
    ("mem0", 8): ["scale-sweep-mem0-e8-v2"],
    ("mem0", 32): ["scale-sweep-mem0-e32-v2"],
    ("mem0", 128): [f"scale-sweep-mem0-e128-s{s}-v3" for s in (7, 17, 42)],
    ("graphiti", 8): ["scale-sweep-graphiti-e8-v2"],
    ("graphiti", 32): ["scale-sweep-graphiti-e32-v2"],
    ("graphiti", 128): ["scale-sweep-graphiti-e128-v2"],
}


def _pooled(names: list[str]) -> list:
    return [row for name in names for row in tr(name) if row.get("system") != "oracle"]


def _share(rows: list, test):
    from temvera.reanalysis import Proportion

    return Proportion(sum(bool(test(row)) for row in rows), len(rows))


def scale_rate(system: str, entities: int, what: str, bound: int | None = None) -> float:
    """A cell of the scale table, or one end of its Wilson interval."""
    rows = _pooled(_SCALE[(system, entities)])
    if what in ("transaction_as_of", "valid_time"):
        p = _share([r for r in rows if r["category"] == what], lambda r: r["exact"])
    elif what == "recall":
        p = _share([r for r in rows if r["expected_values"]], lambda r: r["present_expected"])
    elif what == "stale":
        p = _share([r for r in rows if r["stale_values"]], lambda r: r["present_stale"])
    elif what == "questions":
        return float(len(rows))
    else:
        raise KeyError(what)
    return p.rate if bound is None else p.wilson()[bound]


def graphiti_tx_split(entities: int, superseded: bool, part: int) -> float:
    """Hits (part 0) or total (part 1) of Graphiti's transaction questions,
    split by whether a superseded value exists to filter."""
    rows = [r for r in _pooled(_SCALE[("graphiti", entities)])
            if r["category"] == "transaction_as_of" and bool(r["stale_values"]) == superseded]
    return float(sum(r["exact"] for r in rows) if part == 0 else len(rows))


def v1_graphiti(entities: int, what: str) -> float:
    rows = _pooled([f"scale-sweep-graphiti-e{entities}-v1"])
    if what == "exact":
        return overall_counts(rows).rate
    return _share([r for r in rows if r["expected_values"]], lambda r: r["present_expected"]).rate


def v1_fallback_pct(entities: int) -> float:
    """Share of distinct values the first sweep left as synthetic tokens."""
    from temvera.external_experiment import _events_for
    from temvera.nl_workload import fallback_tokens

    config = json.loads((RUNS / f"scale-sweep-graphiti-e{entities}-v1" / "config.json").read_text())
    fell = total = 0
    for seed in (7, 17, 42):
        counts = fallback_tokens(_events_for(seed, entities, 4, config["profiles"][0], True, 3))
        fell += counts["values"]
        total += counts["values_total"]
    return 100 * fell / total


def _scale_claims() -> list:
    out = []
    table = {
        "mem0": [("transaction_as_of", ("0.944", "0.956", "0.903")),
                 ("valid_time", ("0.206", "0.211", "0.195")),
                 ("recall", ("0.578", "0.592", "0.603")),
                 ("stale", ("0.432", "0.463", "0.498"))],
        "graphiti": [("transaction_as_of", ("0.250", "0.250", "0.250")),
                     ("valid_time", ("0.004", "0.000", "0.005")),
                     ("recall", ("0.913", "0.977", "0.783")),
                     ("stale", ("0.991", "0.998", "0.995"))],
    }
    anchors = {"mem0": "Mem0     & \\texttt{transaction\\_as\\_of}",
               "graphiti": "Graphiti & \\texttt{transaction\\_as\\_of}"}
    for system, rows in table.items():
        for what, printed in rows:
            for entities, value in zip((8, 32, 128), printed):
                out.append(Claim(
                    "Tab.scale", f"{system} {what} at {entities} entities", value,
                    lambda s=system, e=entities, w=what: scale_rate(s, e, w),
                    near=anchors[system], window=280))
    return out


def _x_cells():
    return matched_cells(
        load_run(RUNS / "external-graphiti-filtered-v2"),
        load_run(RUNS / "external-graphiti-filtered-gpt4o-v2"),
    )


def _matched_temporal(run: str) -> float:
    ids = {
        r["question_id"] for r in res("longmemeval-s-v1")["per_instance"]
        if r["question_type"] == "temporal-reasoning"
    }
    rows = [
        r for r in res(run)["per_instance"]
        if r["question_type"] == "temporal-reasoning" and r["question_id"] in ids
    ]
    return sum(r["token_recall"] for r in rows) / len(rows)


# -- Real conversations: LongMemEval knowledge-update supersessions ----------
# Every figure here is a count of cases (one row per question), so there is no
# micro/macro choice to declare; rates are the counts over their stated cases.
_LME = {
    "Mem0": "lme-bitemporal-mem0-agreement-v1",
    "LangMem": "lme-bitemporal-langmem-agreement-v1",
    "Graphiti": "lme-bitemporal-graphiti-agreement-v1",
    "Cognee chunks": "lme-bitemporal-cognee-chunks-agreement-v3",
    "Hindsight recall": "lme-bitemporal-hindsight-recall-agreement-v2",
    "Cognee graph": "lme-bitemporal-cognee-graph-agreement-v3",
    "Hindsight reflect": "lme-bitemporal-hindsight-reflect-agreement-v2",
}
_LME_RETAINING = ("Graphiti", "Cognee chunks", "Hindsight recall")
_EXCLUSIONS = ROOT / "data" / "lme-bitemporal-exclusions.json"


def _lme_runs(system: str) -> tuple[str, str]:
    """The agreement run and the adjudicated run (D-017) for one configuration."""
    agreement = _LME[system]
    return agreement, agreement.split("-agreement")[0] + "-adjudicated-v1"


def lme(system: str, category: str, field: str = "exact") -> float:
    """One count over all 62 pairs: the two runs' summaries, summed."""
    return float(sum(res(run)["summary"][category][field] for run in _lme_runs(system)))


def lme_both(system: str, category: str) -> float:
    """Answers stating both the expected and the superseded value."""
    total = 0
    for run in _lme_runs(system):
        path = RUNS / run / "transcript.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        total += sum(r["present_expected"] and r["present_stale"]
                     for r in rows if r["category"] == category)
    return float(total)


def lme_wilson(system: str, category: str, bound: int) -> float:
    from temvera.reanalysis import Proportion

    return Proportion(int(lme(system, category)), int(lme(system, category, "cases"))).wilson()[bound]


def lme_pairs(what: str) -> float:
    """Pair counts for the real-data workload. Candidates are every labelled or
    excluded pair; 'used' is what the agreement runs replayed; 'excluded' is the
    candidates those runs did not use (adjudicated later, or excluded)."""
    data = json.loads(_EXCLUSIONS.read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "data" / "lme-bitemporal-labels.json").read_text())["labels"]
    candidates = len(labels) + len(data["excluded"])
    assert candidates == data["candidate_pairs"], "labels and exclusions no longer partition the pairs"
    agreement = {int(res(run)["instances"]) for run in _LME.values()}
    adjudicated = {int(res(_lme_runs(s)[1])["instances"]) for s in _LME}
    assert len(agreement) == 1 and len(adjudicated) == 1, "real-data runs disagree on pair counts"
    n_agree, n_adj = agreement.pop(), adjudicated.pop()
    return float({"candidates": candidates, "used": n_agree + n_adj, "agreement": n_agree,
                  "adjudicated": n_adj, "excluded": candidates - n_agree - n_adj}[what])


def _real_claims() -> list:
    out = [
        Claim("5.real", "candidate pairs", "69", lambda: lme_pairs("candidates"),
              near="value for all"),
        Claim("5.real", "pairs the extractors agreed on", "43", lambda: lme_pairs("agreement"),
              near="They\nagreed on"),
        Claim("5.real", "pairs adjudicated", "26",
              lambda: lme_pairs("candidates") - lme_pairs("agreement"), 0.5, near="The other"),
        Claim("5.real", "adjudicated pairs labelled", "19", lambda: lme_pairs("adjudicated"),
              near="author decided,\nlabelling"),
        Claim("5.real", "adjudicated pairs excluded", "7", lambda: lme_pairs("excluded"),
              near="labelling 19 and excluding"),
        Claim("5.real", "pairs used in all", "62", lambda: lme_pairs("used"),
              near="That leaves"),
        Claim("5.real", "full conversation control (count)", "46",
              lambda: lme("Mem0", "transaction_as_of", "full_context_exact"),
              near="the full conversation itself"),
        Claim("5.real", "pairs with incidental later value", "16",
              lambda: lme("Mem0", "transaction_as_of", "cases")
              - lme("Mem0", "transaction_as_of", "cases_without_incidental_values"),
              near="cases. The"),
        Claim("Tab.real", "caption pairs", "62", lambda: lme_pairs("used"),
              near="Benchmark conversations:"),
        Claim("Tab.real", "caption agreement pairs", "43", lambda: lme_pairs("agreement"),
              near="supersessions\n("),
        Claim("Tab.real", "caption adjudicated pairs", "19", lambda: lme_pairs("adjudicated"),
              near="two extractors agreed,"),
        Claim("Tab.real", "caption valid-time cases", "60",
              lambda: lme("Mem0", "valid_time", "cases"), near="Exact answers out of 62 ("),
        Claim("5.real", "retaining old kept, fewest", "41",
              lambda: min(lme(s, "valid_time", "present_expected") for s in _LME_RETAINING),
              near="return the superseded value in"),
        Claim("5.real", "retaining old kept, most", "60",
              lambda: max(lme(s, "valid_time", "present_expected") for s in _LME_RETAINING),
              near="return the superseded value in 41 to"),
        Claim("5.real", "retaining valid_time exact, fewest", "0",
              lambda: min(lme(s, "valid_time") for s in _LME_RETAINING),
              near="but answer only"),
        Claim("5.real", "retaining valid_time exact, most", "7",
              lambda: max(lme(s, "valid_time") for s in _LME_RETAINING),
              near="but answer only 0 to"),
        Claim("5.real", "Mem0 valid_time exact (count)", "3",
              lambda: lme("Mem0", "valid_time"), near="The consolidating stores answer"),
        Claim("5.real", "LangMem valid_time exact (count)", "8",
              lambda: lme("LangMem", "valid_time"), near="The consolidating stores answer 3 and"),
        Claim("5.real", "Mem0 old kept (count)", "21",
              lambda: lme("Mem0", "valid_time", "present_expected"),
              near="fewer than half of their answers"),
        Claim("5.real", "LangMem old kept (count)", "23",
              lambda: lme("LangMem", "valid_time", "present_expected"),
              near="fewer than half of their answers (21 and"),
        Claim("5.real", "Cognee graph valid_time exact (count)", "40",
              lambda: lme("Cognee graph", "valid_time"), near="LLM, Cognee's graph answers"),
        Claim("5.real", "Cognee graph valid_time Wilson low", "0.54",
              lambda: lme_wilson("Cognee graph", "valid_time", 0), 0.006,
              near="LLM, Cognee's graph answers"),
        Claim("5.real", "Cognee graph valid_time Wilson high", "0.77",
              lambda: lme_wilson("Cognee graph", "valid_time", 1), 0.006,
              near="LLM, Cognee's graph answers"),
        Claim("5.real", "Hindsight reflect valid_time exact (count)", "17",
              lambda: lme("Hindsight reflect", "valid_time"),
              near="0.77]) and Hindsight's answers"),
        Claim("5.real", "Hindsight reflect valid_time Wilson low", "0.19",
              lambda: lme_wilson("Hindsight reflect", "valid_time", 0), 0.006,
              near="0.77]) and Hindsight's answers"),
        Claim("5.real", "Hindsight reflect valid_time Wilson high", "0.41",
              lambda: lme_wilson("Hindsight reflect", "valid_time", 1), 0.006,
              near="0.77]) and Hindsight's answers"),
        Claim("5.real", "grid Cognee reader valid_time hits", "192",
              lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[0], 0.5,
              near="the reader ordering"),
        Claim("5.real", "grid Hindsight reader valid_time hits", "67",
              lambda: micro_counts("external-hindsight-reflect-v1", "valid_time", cells())[0],
              0.5, near="the reader ordering"),
        Claim("5.real", "grid reader valid_time cases", "195",
              lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[1], 0.5,
              near="the reader ordering"),
        Claim("5.real", "grid Mem0 transaction_as_of (micro)", "0.952",
              lambda: micro("external-mem0-grid-v2", "transaction_as_of", cells()),
              near="On the grid, Mem0 and LangMem"),
        Claim("5.real", "grid LangMem transaction_as_of (micro)", "0.890",
              lambda: micro("external-langmem-v1", "transaction_as_of", cells()),
              near="On the grid, Mem0 and LangMem"),
        Claim("5.real", "Mem0 current exact (count)", "35",
              lambda: lme("Mem0", "current"), near="here they\nanswer"),
        Claim("5.real", "LangMem current exact (count)", "26",
              lambda: lme("LangMem", "current"), near="here they\nanswer 35 and"),
        Claim("5.real", "Mem0 current, both values stated (count)", "18",
              lambda: lme_both("Mem0", "current"), near="Mem0 states both values in"),
        Claim("5.real", "best current exact over configurations (count)", "35",
              lambda: max(lme(s, "current") for s in _LME),
              near="No configuration answers more than"),
        Claim("abs", "main-grid valid-time ceiling for consolidating stores", "0.385",
              lambda: ceiling_rate(["external-mem0-grid-v2"], "ceiling"),
              near="just under a ceiling"),
        Claim("abs", "Mem0 current values answered after a correction", "1",
              lambda: corr("mem0", "present_corrected", "hits"), 0.5,
              near="correction about the past to the present ("),
        Claim("abs", "corrected subjects asked for their current value", "45",
              lambda: corr("mem0", "present_corrected", "n"), 0.5,
              near="correction about the past to the present ("),
        Claim("abs", "smallest scale, entities", "8", lambda: float(min(e for _, e in _SCALE)),
              near="Both failure modes hold"),
        Claim("abs", "largest scale, entities", "128", lambda: float(max(e for _, e in _SCALE)),
              near="Both failure modes hold\nfrom 8 to"),
        Claim("abs", "read-path rule, best retaining store (valid-time hits)", "190",
              lambda: max(read_path("Cognee chunks", "exact"), read_path("Hindsight recall", "exact")),
              0.5, near="read-path rule recovers up to"),
        Claim("abs", "read-path rule, valid-time questions", "195",
              lambda: read_path("Hindsight recall", "questions"), 0.5, near="read-path rule recovers up to"),
        Claim("abs", "real-data supersessions", "62", lambda: lme_pairs("used"),
              near="people per history and on"),
        Claim("intro", "real-data supersessions", "62", lambda: lme_pairs("used"),
              near="both failure modes reappear"),
        Claim("5.real", "pairs, closing caveat", "62", lambda: lme_pairs("used"),
              near="These are", after="No configuration answers more than"),
        Claim("Lim", "pairs in the real-data check", "62", lambda: lme_pairs("used"),
              near="the benchmark check covers"),
        Claim("Repro", "excluded pairs listed by ID", "7", lambda: lme_pairs("excluded"),
              near="derived are released; the"),
    ]
    table = [
        ("Mem0 (consolidates)                 &", "Mem0", ("47", "35", "3", "21")),
        ("LangMem (consolidates)              &", "LangMem", ("33", "26", "8", "23")),
        ("Graphiti (retains)                  &", "Graphiti", ("43", "11", "7", "41")),
        ("Cognee \\textsc{chunks} (retains)    &", "Cognee chunks", ("46", "0", "0", "60")),
        ("Hindsight \\textsc{recall} (retains) &", "Hindsight recall", ("56", "6", "3", "50")),
        ("Cognee \\textsc{graph-completion}    &", "Cognee graph", ("56", "35", "40", "44")),
        ("Hindsight \\textsc{reflect}          &", "Hindsight reflect", ("55", "32", "17", "31")),
    ]
    columns = (("transaction_as_of", "exact"), ("current", "exact"),
               ("valid_time", "exact"), ("valid_time", "present_expected"))
    for anchor, system, printed in table:
        for (category, field), value in zip(columns, printed):
            out.append(Claim(
                "Tab.real", f"{system} {category} {field} (count)", value,
                lambda s=system, c=category, f=field: lme(s, c, f),
                near=anchor, window=40, after="\\label{tab:realdata}"))
    full = (("transaction_as_of", "full_context_exact"), ("current", "full_context_exact"),
            ("valid_time", "full_context_exact"), ("valid_time", "full_context_expected"))
    for (category, field), value in zip(full, ("46", "0", "0", "60")):
        out.append(Claim(
            "Tab.real", f"full conversation {category} {field} (count)", value,
            lambda c=category, f=field: lme("Mem0", c, f),
            near="Full conversation                   &", window=40,
            after="\\label{tab:realdata}"))
    return out


# -- Two bounds (sec:bounds): recomputed by scripts/analyze_filtering_laws.py --
_laws = None


def laws():
    """The analysis script, loaded once; it rebuilds histories from run seeds."""
    global _laws
    if _laws is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "analyze_filtering_laws", ROOT / "scripts" / "analyze_filtering_laws.py")
        _laws = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_laws)
    return _laws


_MEM0_SCALE = {8: ["scale-sweep-mem0-e8-v2"], 32: ["scale-sweep-mem0-e32-v2"],
               128: ["scale-sweep-mem0-e128-s7-v3", "scale-sweep-mem0-e128-s17-v3",
                     "scale-sweep-mem0-e128-s42-v3"]}
_GRAPHITI_RUNS = ("external-graphiti-hybrid-v1", "external-graphiti-hybrid-gpt4o-v1",
                  "scale-sweep-graphiti-e8-v2", "scale-sweep-graphiti-e32-v2",
                  "scale-sweep-graphiti-e128-v2")
_RETAINING_RUNS = _GRAPHITI_RUNS + ("external-cognee-chunks-grid-v3",
                                    "external-hindsight-recall-v1")
_ceilings: dict = {}


def ceiling(run: str) -> tuple:
    if run not in _ceilings:
        _ceilings[run] = laws().ceiling(run)
        assert _ceilings[run][4] == 0, f"{run}: rebuilt history disagrees with the sealed run"
    return _ceilings[run]


def ceiling_rate(runs: list[str], what: str) -> float:
    """Pooled over runs: 'ceiling' share answerable, 'exact', 'beyond' (count),
    'correct' (count)."""
    a = n = inside = beyond = 0
    for run in runs:
        ra, rn, ri, rb, _ = ceiling(run)
        a, n, inside, beyond = a + ra, n + rn, inside + ri, beyond + rb
    return {"ceiling": a / n, "exact": (inside + beyond) / n, "beyond": float(beyond),
            "correct": float(inside + beyond), "answerable": float(a), "n": float(n)}[what]


def retaining_split(what: str) -> float:
    """Extremes over the synthetic retaining runs: lowest exact rate with nothing to
    filter, highest with something to filter."""
    splits = [laws().split(run, c) for run in _RETAINING_RUNS
              for c in ("transaction_as_of", "valid_time")]
    if what == "free_min":
        return min(kf / nf for kf, nf, _, _ in splits if nf)
    if what == "free_max":
        return max(kf / nf for kf, nf, _, _ in splits if nf)
    return max(kc / nc for _, _, kc, nc in splits if nc)


def real_split(system: str, what: str) -> float:
    from temvera.reanalysis import Proportion

    _, _, kc, nc = laws().split_real(laws().REAL[system])
    p = Proportion(kc, nc)
    return {"hits": float(kc), "n": float(nc), "rate": p.rate,
            "low": p.wilson()[0], "high": p.wilson()[1]}[what]


def graphiti_synthetic_conflict_high() -> float:
    from temvera.reanalysis import Proportion

    return max(Proportion(kc, nc).wilson()[1]
               for run in _GRAPHITI_RUNS for c in ("transaction_as_of", "valid_time")
               for _, _, kc, nc in [laws().split(run, c)] if nc)


def _bounds_claims() -> list:
    grid = ["external-mem0-grid-v2"]
    return [
        Claim("5.bounds", "main-grid valid-time ceiling (micro)", "0.385",
              lambda: ceiling_rate(grid, "ceiling"), near="On the main\ngrid that ceiling is"),
        Claim("5.bounds", "main-grid answerable questions", "75",
              lambda: ceiling_rate(grid, "answerable"), 0.5, near="On the main\ngrid that ceiling is"),
        Claim("5.bounds", "main-grid valid-time questions", "195",
              lambda: ceiling_rate(grid, "n"), 0.5, near="On the main\ngrid that ceiling is"),
        Claim("5.bounds", "Mem0 valid_time, mini (micro)", "0.364",
              lambda: ceiling_rate(grid, "exact"), near="(75 of 195): Mem0 reaches"),
        Claim("5.bounds", "Mem0 valid_time, gpt-4o (micro)", "0.374",
              lambda: ceiling_rate(["external-mem0-grid-gpt4o-v1"], "exact"),
              near="(75 of 195): Mem0 reaches"),
        # The prose says none of the three main-grid runs answers above the
        # ceiling; there is no digit to anchor, so this lambda carries the check.
        Claim("5.bounds", "LangMem valid_time (micro)", "0.323",
              lambda: ceiling_rate(["external-langmem-v1"], "exact")
              if not any(ceiling_rate([r], "beyond") for r in
                         ("external-mem0-grid-v2", "external-mem0-grid-gpt4o-v1",
                          "external-langmem-v1"))
              else -1.0,  # a failed guard must read as drift; NaN would not
              near="(75 of 195): Mem0 reaches"),
        *[Claim("5.bounds", f"scale ceiling at {e} entities (case-weighted)", "0.250",
                lambda e=e: ceiling_rate(_MEM0_SCALE[e], "ceiling"),
                near="In the scale sweep the ceiling is") for e in (8, 32, 128)],
        Claim("5.bounds", "Mem0 valid_time at 8 entities", "0.206",
              lambda: ceiling_rate(_MEM0_SCALE[8], "exact"), near="and Mem0's"),
        Claim("5.bounds", "Mem0 valid_time at 32 entities", "0.211",
              lambda: ceiling_rate(_MEM0_SCALE[32], "exact"), near="and Mem0's"),
        Claim("5.bounds", "Mem0 valid_time at 128 entities (3 seeds pooled)", "0.195",
              lambda: ceiling_rate(_MEM0_SCALE[128], "exact"), near="and Mem0's"),
        Claim("5.bounds", "scale answers above the ceiling", "13",
              lambda: ceiling_rate(sum(_MEM0_SCALE.values(), []), "beyond"), 0.5,
              near="sit under it,"),
        Claim("5.bounds", "scale correct valid-time answers", "915",
              lambda: ceiling_rate(sum(_MEM0_SCALE.values(), []), "correct"), 0.5,
              near="sit under it,"),
        Claim("5.bounds", "first bound exceeded, Mem0 mini", "9",
              lambda: float(laws().first_ceiling_beyond("external-mem0-grid-v2")), 0.5,
              near="it was exceeded by"),
        Claim("5.bounds", "first bound exceeded, LangMem", "7",
              lambda: float(laws().first_ceiling_beyond("external-langmem-v1")), 0.5,
              near="it was exceeded by 9 Mem0 and"),
        Claim("5.bounds", "retaining, nothing to filter, lowest", "0.972",
              lambda: retaining_split("free_min"), near="the three retaining stores answer"),
        Claim("5.bounds", "retaining, nothing to filter, highest", "1.000",
              lambda: retaining_split("free_max"), near="the three retaining stores answer"),
        Claim("5.bounds", "retaining, something to filter, highest", "0.009",
              lambda: retaining_split("conflict_max"), near="nothing to filter and at most"),
        Claim("5.bounds", "main-grid share with nothing to filter (transaction)", "0.408",
              lambda: laws().split("external-cognee-chunks-grid-v3", "transaction_as_of")[1] / 228,
              near="at every scale, and"),
        Claim("5.bounds", "Graphiti main-grid transaction (micro)", "0.412",
              lambda: micro("external-graphiti-hybrid-v1", "transaction_as_of", cells()),
              near="Graphiti with one answer more"),
        Claim("5.bounds", "real-data questions with something to filter", "122",
              lambda: real_split("Graphiti", "n"), 0.5, near="test is the benchmark conversations"),
        Claim("5.bounds", "Cognee real-data filtered hits", "0",
              lambda: real_split("Cognee chunks", "hits"), 0.5, near="with something to filter, Cognee answers"),
        Claim("5.bounds", "Hindsight real-data filtered hits", "9",
              lambda: real_split("Hindsight recall", "hits"), 0.5, near="Cognee answers 0 and Hindsight"),
        Claim("5.bounds", "Graphiti real-data filtered hits", "18",
              lambda: real_split("Graphiti", "hits"), 0.5, near="but\nGraphiti"),
        Claim("5.bounds", "Graphiti real-data filtering rate", "0.148",
              lambda: real_split("Graphiti", "rate"), near="but\nGraphiti"),
        # The prose says this interval lies above every synthetic one; the
        # lambda fails the check outright if that stops being true.
        Claim("5.bounds", "Graphiti real-data Wilson low", "0.095",
              lambda: real_split("Graphiti", "low")
              if real_split("Graphiti", "low") > graphiti_synthetic_conflict_high()
              else -1.0, near="but\nGraphiti"),  # -1, not NaN: NaN never reads as drift
        Claim("5.bounds", "Graphiti real-data Wilson high", "0.221",
              lambda: real_split("Graphiti", "high"), near="but\nGraphiti"),
    ]


# -- Retroactive corrections (sec:corrections), preregistered H6 -------------
_corr = None


def corrections():
    global _corr
    if _corr is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "analyze_corrections", ROOT / "scripts" / "analyze_corrections.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _corr = {"module": module, "mem0": module.classify("external-corrections-mem0-v1"),
                 "graphiti": module.classify("external-corrections-graphiti-v1")}
    return _corr


def corr(system: str, kind: str, what: str) -> float:
    hits = corrections()[system][kind]
    return float({"hits": sum(hits), "n": len(hits)}[what]) if what != "rate" \
        else sum(hits) / len(hits)


def corr_subjects(what: str) -> float:
    import json as _json

    from temvera.external_experiment import _events_for
    from temvera.model import Operation

    config = _json.loads((RUNS / "external-corrections-mem0-v1" / "config.json").read_text())
    total = fixed = 0
    for seed in config["seeds"]:
        for scale in config["scales"]:
            events = _events_for(seed, scale["entities"], scale["revisions"],
                                 config["profiles"][0], True, 1, True, config["natural_pools"])
            total += scale["entities"]
            fixed += sum(1 for e in events if e.operation is Operation.INGEST and e.valid_to)
    return float(total if what == "total" else fixed)


def _preregistered(pattern: str) -> float:
    """A threshold printed in the paper must be the one committed beforehand."""
    text = (ROOT / "docs" / "preregistration-h6.md").read_text(encoding="utf-8")
    return 0.10 if re.search(pattern, text) else -1.0


def _corrections_claims() -> list:
    return [
        Claim("5.corr", "subjects", "80", lambda: corr_subjects("total"), 0.5,
              near="ran Mem0 and Graphiti on"),
        Claim("5.corr", "subjects with a correction", "45", lambda: corr_subjects("fixed"), 0.5,
              near="ran Mem0 and Graphiti on"),
        Claim("5.corr", "Mem0 present, uncorrected hits", "35",
              lambda: corr("mem0", "present_uncorrected", "hits"), 0.5, near="answers 35 of"),
        Claim("5.corr", "Mem0 present, uncorrected subjects", "35",
              lambda: corr("mem0", "present_uncorrected", "n"), 0.5, near="answers 35 of"),
        Claim("5.corr", "Mem0 present, corrected hits", "1",
              lambda: corr("mem0", "present_corrected", "hits"), 0.5,
              near="subjects without a correction and"),
        Claim("5.corr", "Mem0 present, corrected subjects", "45",
              lambda: corr("mem0", "present_corrected", "n"), 0.5,
              near="subjects without a correction and"),
        Claim("5.corr", "Mem0 present drop", "0.978",
              lambda: corr("mem0", "present_uncorrected", "rate")
              - corr("mem0", "present_corrected", "rate"), near="drop of at least 0.10 and measured"),
        Claim("5.corr", "Mem0 current value absent afterwards (post hoc)", "41",
              lambda: float(corrections()["module"].vanished("external-corrections-mem0-v1")[0]),
              0.5, near="afterwards, for"),
        Claim("5.corr", "Mem0 corrected interval hits", "69",
              lambda: corr("mem0", "corrected", "hits"), 0.5, near="The\ncorrected interval itself Mem0 answers"),
        Claim("5.corr", "Mem0 corrected interval questions", "78",
              lambda: corr("mem0", "corrected", "n"), 0.5, near="The\ncorrected interval itself Mem0 answers"),
        Claim("5.corr", "Mem0 ordinary superseded interval hits", "0",
              lambda: corr("mem0", "past_uncorrected", "hits"), 0.5, near="against 0 of"),
        Claim("5.corr", "Mem0 ordinary superseded interval questions", "70",
              lambda: corr("mem0", "past_uncorrected", "n"), 0.5, near="against 0 of"),
        Claim("5.corr", "H6a preregistered threshold", "0.10",
              lambda: _preregistered(r"lower than on `present_uncorrected` by at least\s+0\.10"),
              near="we\npredicted a drop of at least"),
        Claim("5.corr", "H6b preregistered threshold", "0.10",
              lambda: _preregistered(r"Graphiti's exact rate on `corrected`\s+is at most 0\.10"),
              near="within the predicted"),
        Claim("5.corr", "Graphiti corrected interval hits", "1",
              lambda: corr("graphiti", "corrected", "hits"), 0.5, near="Graphiti answers the\ncorrected interval"),
        Claim("5.corr", "Graphiti corrected interval questions", "78",
              lambda: corr("graphiti", "corrected", "n"), 0.5, near="Graphiti answers the\ncorrected interval"),
    ]


# -- Added in the 2026-10-21 audit: numbers the paper printed without a row ----
def _cost_sweep(entities: int) -> float:
    """Case-weighted exact accuracy of the cost sweep at one entity count."""
    rows = [r for r in tr("scale-cost-mem0-v1") if r["entities"] == entities]
    return sum(bool(r["exact"]) for r in rows) / len(rows)


def _audit_claims() -> list:
    return [
        Claim("5.5", "cost sweep exact at 2 entities (micro)", "0.609",
              lambda: _cost_sweep(2), near="Case-weighted exact accuracy moved"),
        Claim("5.5", "cost sweep exact at 4 entities (micro)", "0.527",
              lambda: _cost_sweep(4), near="Case-weighted exact accuracy moved"),
        Claim("5.5", "cost sweep exact at 8 entities (micro)", "0.539",
              lambda: _cost_sweep(8), near="Case-weighted exact accuracy moved"),
        Claim("5.5", "Cognee ingests on the grid", "477",
              lambda: telemetry("external-cognee-grid-v1", "ingest_latency", "n"), 0.5,
              near="over the same 20-cell grid ("),
        Claim("5.5", "Cognee queries on the grid", "484",
              lambda: telemetry("external-cognee-grid-v1", "query_latency", "n"), 0.5,
              near="over the same 20-cell grid ("),
        Claim("5.5", "embedding share of spend, %", "0.2",
              lambda: 100 * telemetry("scale-cost-mem0-v1", "usage", "text-embedding-3-small",
                                      "cost_usd") / telemetry("scale-cost-mem0-v1",
                                                               "cost_usd_total"), 0.06,
              near="embeddings account for"),
        Claim("5.5", "cost per ingested turn, USD", "0.0005",
              lambda: telemetry("scale-cost-mem0-v1", "cost_usd_total")
              / telemetry("scale-cost-mem0-v1", "ingest_latency", "n"), 0.00006,
              near="an ingested turn costs about"),
        Claim("5.ext", "LongMemEval instances per type", "10",
              lambda: float(min(__import__("collections").Counter(
                  r["question_type"] for r in res("longmemeval-e7-v2")["per_instance"]).values())),
              0.5, near="single-session-assistant $0.151$ ("),
        Claim("5.other", "synonym queries", "10",
              lambda: float(json.loads((RUNS / "vector-synonym-compare-v1.json").read_text())["queries"]),
              0.5, near="recall@1 $1.0$"),
        Claim("7", "Cognee chunks v1 worker errors", "40",
              lambda: float(res("external-cognee-chunks-grid-v1")["backbone"]["worker_errors"]), 0.5,
              near="paper reported a"),
        Claim("7", "Cognee chunks v1 overall (micro)", "0.207",
              lambda: micro("external-cognee-chunks-grid-v1", cells=cells()),
              near="unexplained worker errors at"),
        Claim("7", "Cognee chunks replication overall (micro)", "0.194",
              lambda: micro("external-cognee-chunks-grid-v3", cells=cells()),
              near="isolated stores that we now cite scores"),
    ]


# -- Read-path filter (sec:reader): scripts/analyze_read_path_filter.py --------
_rp = None


def read_path(config: str, what: str) -> float:
    global _rp
    if _rp is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "analyze_read_path_filter", ROOT / "scripts" / "analyze_read_path_filter.py")
        _rp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_rp)
    return float(_rp.evaluate(_rp.CONFIGS[config])[what])


def _read_path_claims() -> list:
    A = "One rule on the read path is enough"
    return [
        Claim("5.4", "Cognee chunks valid-time hits with the rule", "184",
              lambda: read_path("Cognee chunks", "exact"), 0.5, near="lifts valid-time accuracy from 0", after=A),
        Claim("5.4", "valid-time questions", "195",
              lambda: read_path("Cognee chunks", "questions"), 0.5, near="lifts valid-time accuracy from 0", after=A),
        Claim("5.4", "Cognee chunks valid-time hits without the rule", "0",
              lambda: read_path("Cognee chunks", "exact_unfiltered"), 0.5, near="lifts valid-time accuracy from", after=A),
        Claim("5.4", "Hindsight recall valid-time hits with the rule", "190",
              lambda: read_path("Hindsight recall", "exact"), 0.5, near="for Cognee and to", after=A),
        Claim("5.4", "Graphiti answers where the rule applies", "17",
              lambda: read_path("Graphiti", "applicable"), 0.5, near="the rule applies to only", after=A),
        Claim("5.4", "Graphiti valid-time hits with the rule", "6",
              lambda: read_path("Graphiti", "exact"), 0.5, near="answers and recovers", after=A),
    ]


# -- Current releases (sec:releases), preregistered H7 -------------------------
_RELEASES = {
    "mem0": ("external-mem0-grid-v2", "external-mem0-grid-latest-v1"),
    "graphiti": ("external-graphiti-hybrid-v1", "external-graphiti-hybrid-latest-v1"),
    "cognee chunks": ("external-cognee-chunks-grid-v3", "external-cognee-chunks-grid-latest-v1"),
    "hindsight recall": ("external-hindsight-recall-v1", "external-hindsight-recall-latest-v1"),
    "cognee graph": ("external-cognee-grid-v1", "external-cognee-grid-latest-v1"),
    "hindsight reflect": ("external-hindsight-reflect-v1", "external-hindsight-reflect-latest-v1"),
}


def reader_split(system: str, which: int, what: str) -> float:
    """Valid-time answers that are exact, state the expected value, or state both."""
    rows = [row for row in tr(_RELEASES[system][which])
            if row["category"] == "valid_time" and cell_key(row) in cells()]
    return float(sum({"exact": bool(row["exact"]),
                      "expected": bool(row["present_expected"]),
                      "both": bool(row["present_expected"]) and bool(row["present_stale"]),
                      }[what] for row in rows))


def release(system: str, which: int, category: str) -> float:
    return micro(_RELEASES[system][which], category, cells())


def _h7_threshold() -> float:
    text = (ROOT / "docs" / "preregistration-h7.md").read_text(encoding="utf-8")
    return 0.85 if re.search(r"transaction-scoped\s+accuracy is at least 0\.85", text) else -1.0


def _releases_claims() -> list:
    out = []
    rows = (("Mem0 (0.1.118 $\\to$ 2.2.1)", "mem0"),
            ("Graphiti (0.29.2 $\\to$ 0.31.2)", "graphiti"),
            ("Cognee \\textsc{chunks} (1.4.2 $\\to$ 1.6.5)", "cognee chunks"),
            ("Hindsight \\textsc{recall} (0.9.1 $\\to$ 1.1.0)", "hindsight recall"),
            ("Cognee \\textsc{graph-completion}         &", "cognee graph"),
            ("Hindsight \\textsc{reflect}               &", "hindsight reflect"))
    for anchor, system in rows:
        for which, category in ((0, "transaction_as_of"), (1, "transaction_as_of"),
                                (0, "valid_time"), (1, "valid_time")):
            value = release(system, which, category)
            out.append(Claim("Tab.rel", f"{system} {category} {'now' if which else 'then'}",
                             f"{value:.3f}", lambda s=system, w=which, c=category: release(s, w, c),
                             near=anchor, window=70, after="\\label{tab:releases}"))
    def laws_split():
        return laws().split("external-mem0-grid-latest-v1", "transaction_as_of")

    B = "Graphiti, Cognee and Hindsight retrieve as before"
    out += [
        Claim("6.J", "Cognee 1.6.5 reader valid-time exact", "195",
              lambda: reader_split("cognee graph", 1, "exact"), 0.5,
              near="Cognee's reader still repairs them (", after=B),
        Claim("6.J", "Hindsight 1.1.0 reader states the expected value", "195",
              lambda: reader_split("hindsight reflect", 1, "expected"), 0.5,
              near="names the right value in all", after=B),
        Claim("6.J", "Hindsight 1.1.0 reader states both values", "193",
              lambda: reader_split("hindsight reflect", 1, "both"), 0.5,
              near="restates the later one in", after=B),
        Claim("6.J", "Hindsight 0.9.1 reader states both values", "128",
              lambda: reader_split("hindsight reflect", 0, "both"), 0.5,
              near="restates the later one in 193 of them (", after=B),
        Claim("6.J", "Hindsight 1.1.0 reader valid-time exact", "2",
              lambda: reader_split("hindsight reflect", 1, "exact"), 0.5,
              near="so only", after=B),
        Claim("6.J", "Hindsight 0.9.1 reader valid-time exact", "67",
              lambda: reader_split("hindsight reflect", 0, "exact"), 0.5,
              near="are exact, against", after=B),
    ]
    A = "Mem0 changes design, and its accuracy moves with it"
    out += [
        Claim("5.rel", "current-release retrieval valid_time, lowest", "0.000",
              lambda: min(release(s, 1, "valid_time") for s in
                          ("graphiti", "cognee chunks", "hindsight recall")),
              near="answer valid-time questions at"),
        Claim("5.rel", "current-release retrieval valid_time, highest", "0.005",
              lambda: max(release(s, 1, "valid_time") for s in
                          ("graphiti", "cognee chunks", "hindsight recall")),
              near="answer valid-time questions at 0.000\nto"),
        Claim("5.rel", "Mem0 2.2.1 nothing-to-filter hits", "93", lambda: float(laws_split()[0]), 0.5,
              near="It answers", after=A),
        Claim("5.rel", "Mem0 2.2.1 nothing-to-filter questions", "93", lambda: float(laws_split()[1]),
              0.5, near="It answers 93 of", after=A),
        Claim("5.rel", "Mem0 2.2.1 something-to-filter hits", "2", lambda: float(laws_split()[2]), 0.5,
              near="nothing to filter and", after=A),
        Claim("5.rel", "Mem0 2.2.1 something-to-filter questions", "135", lambda: float(laws_split()[3]),
              0.5, near="nothing to filter and 2 of", after=A),
        Claim("5.rel", "Mem0 0.1.118 transaction (micro)", "0.952", lambda: release("mem0", 0, "transaction_as_of"),
              near="accuracy falls from", after=A),
        Claim("5.rel", "Mem0 2.2.1 transaction (micro)", "0.417", lambda: release("mem0", 1, "transaction_as_of"),
              near="accuracy falls from 0.952 to", after=A),
        Claim("5.rel", "share with nothing to filter", "0.408",
              lambda: laws_split()[1] / (laws_split()[1] + laws_split()[3]), near="the share of those", after=A),
        Claim("5.rel", "Mem0 0.1.118 valid_time (micro)", "0.364", lambda: release("mem0", 0, "valid_time"),
              near="valid-time accuracy from", after=A),
        Claim("5.rel", "Mem0 2.2.1 valid_time (micro)", "0.000", lambda: release("mem0", 1, "valid_time"),
              near="its valid-time accuracy from", after=A),
        Claim("5.rel", "H7b preregistered threshold", "0.85", lambda: _h7_threshold(),
              near="answer at least", after=A),
        Claim("5.rel", "Mem0 2.2.1 current value vanished after correction", "1",
              lambda: float(corrections()["module"].vanished("external-corrections-mem0-latest-v1")[0]),
              0.5, near="answer for", after=A),
        Claim("5.rel", "corrected subjects", "45",
              lambda: float(corrections()["module"].vanished("external-corrections-mem0-latest-v1")[1]),
              0.5, near="answer for 1 of", after=A),
        Claim("5.rel", "Mem0 0.1.118 vanished", "41",
              lambda: float(corrections()["module"].vanished("external-corrections-mem0-v1")[0]),
              0.5, near="against", after=A),
        Claim("5.rel", "Mem0 2.2.1 present after correction hits", "0",
              lambda: float(sum(_corr_latest("present_corrected"))), 0.5,
              near="neither the present nor the corrected interval (", after=A),
        Claim("5.rel", "Mem0 2.2.1 corrected interval questions", "78",
              lambda: float(len(_corr_latest("corrected"))), 0.5, near="0 of 45 and 0 of", after=A),
        Claim("5.rel", "read-path Cognee 1.6.5", "184", lambda: _rp_latest("external-cognee-chunks-grid-latest-v1", "exact"),
              0.5, near="recovers", after="The read-path rule carries over"),
        Claim("5.rel", "read-path Hindsight 1.1.0", "183", lambda: _rp_latest("external-hindsight-recall-latest-v1", "exact"),
              0.5, near="recovers 184,", after="The read-path rule carries over"),
        Claim("5.rel", "read-path Mem0 2.2.1", "125", lambda: _rp_latest("external-mem0-grid-latest-v1", "exact"),
              0.5, near="recovers 184, 183 and", after="The read-path rule carries over"),
        Claim("5.rel", "Mem0 2.2.1 dated answers", "176", lambda: _rp_latest("external-mem0-grid-latest-v1", "applicable"),
              0.5, near="carry a date in", after="The read-path rule carries over"),
    ]
    return out


def _corr_latest(kind: str) -> list:
    return corrections()["module"].classify("external-corrections-mem0-latest-v1")[kind]


def _rp_latest(run: str, what: str) -> float:
    read_path("Cognee chunks", "exact")  # loads the module
    return float(_rp.evaluate(run)[what])


# -- Numbers a coverage sweep found printed without a row (2026-10-22) ---------
def _side(what: str) -> float:
    syn = json.loads((RUNS / "vector-synonym-compare-v1.json").read_text())
    sec = res("security-evaluation-v0")["governed"]
    abl = res("channel-ablation-v0")
    return float({"learned": syn["learned_recall_at_1"], "hashing": syn["hashing_recall_at_1"],
                  "accepted": round(sec["attack_write_acceptance_rate"] * sec["attacks"]),
                  "attacks": sec["attacks"],
                  "activated": round(sec["attack_activation_rate"] * sec["attacks"]),
                  "ablation_min": min(row["evidence_recall_at_k"] for row in abl),
                  "ablation_second": sorted(row["evidence_recall_at_k"] for row in abl[1:])[1]}[what])


def _coverage_claims() -> list:
    return [
        Claim("abs", "Mem0 transaction_as_of (micro)", "0.952",
              lambda: micro("external-mem0-grid-v2", "transaction_as_of", cells()),
              near="queries well ("),
        Claim("5.other", "learned channel recall@1", "1.0", lambda: _side("learned"),
              near="held-out synonyms at recall@1"),
        Claim("5.other", "hashing channel recall@1", "0.0", lambda: _side("hashing"),
              near="dependency-free hashing channel scored"),
        Claim("5.other", "attacks admitted as inert data", "3", lambda: _side("accepted"), 0.5,
              near="signed tenant-scoped gating admitted"),
        Claim("5.other", "attacks in the threat fixture", "4", lambda: _side("attacks"), 0.5,
              near="signed tenant-scoped gating admitted $3/"),
        Claim("5.other", "attacks activated", "0", lambda: _side("activated"), 0.5,
              near="as inert data\nwhile activating"),
        # Every removal but the lowest must sit at 1.0, so the second-lowest is checked.
        Claim("7", "ablation removals kept at full recall", "1.0",
              lambda: _side("ablation_second"), near="every removal but one kept recall at"),
        Claim("7", "ablation without the temporal channel", "0.79",
              lambda: _side("ablation_min"), 0.005, near="temporal channel lowered it to"),
        Claim("Lim", "candidate supersessions", "69", lambda: lme_pairs("candidates"), 0.5,
              near="covers 62 of"),
        Claim("Lim", "adjudicated supersessions", "19", lambda: lme_pairs("adjudicated"), 0.5,
              near="candidate\nsupersessions,"),
        Claim("Lim", "first replication expiry move", "0.125",
              lambda: micro("external-mem0-grid-v2", "expiry_boundary", cells())
              - micro("external-mem0-grid-v1", "expiry_boundary", cells()),
              near="small-denominator category by"),
        Claim("Ack", "disputed LongMemEval pairs", "26",
              lambda: lme_pairs("candidates") - lme_pairs("agreement"), 0.5,
              near="the labels for the"),
    ]


CLAIMS = CLAIMS + _grid_claims() + _scale_claims() + _real_claims() + _bounds_claims() + _corrections_claims() + _audit_claims() + _read_path_claims() + _releases_claims() + _coverage_claims()


def main() -> int:
    tex = PAPER.read_text(encoding="utf-8")
    if "--list" in sys.argv:
        for claim in CLAIMS:
            print(f"  {claim.where:<7} {claim.label:<44} {claim.printed}")
        return 0

    drift: list[str] = []
    absent: list[str] = []
    for claim in CLAIMS:
        actual = claim.compute()
        if abs(actual - float(claim.printed.replace("{,}", ""))) > claim.tol:
            drift.append(f"  {claim.where:<7} {claim.label:<44} paper {claim.printed}, runs {actual:.4f}")
        window = tex
        if claim.near is not None:
            start = tex.find(claim.after) if claim.after is not None else 0
            spot = tex.find(claim.near, max(start, 0)) if start >= 0 else -1
            if spot < 0:
                absent.append(f"  {claim.where:<7} {claim.label:<44} anchor text gone: {claim.near!r}")
                continue
            window = tex[spot : spot + claim.window + len(claim.near)]
        if not re.search(rf"(?<![\d.]){re.escape(claim.printed)}(?![\d])", window):
            where = "near its anchor" if claim.near else "in main.tex"
            absent.append(f"  {claim.where:<7} {claim.label:<44} {claim.printed} not {where}")

    print(f"checked {len(CLAIMS)} claims against sealed runs")
    if drift:
        print("\nDRIFTED FROM THE RUNS:")
        print("\n".join(drift))
    if absent:
        print("\nNO LONGER PRINTED IN THE PAPER:")
        print("\n".join(absent))
    if drift or absent:
        return 1
    print("every claim matches its run and still appears in the paper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
