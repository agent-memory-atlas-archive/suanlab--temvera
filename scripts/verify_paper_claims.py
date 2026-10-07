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


GRID = (
    "external-mem0-grid-v2",
    "external-langmem-v1",
    "external-graphiti-hybrid-v1",
    "external-cognee-chunks-grid-v1",
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
        "Cognee chunks": ("external-cognee-chunks-grid-v1", "0.207", "0.015", "0.089"),
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
    Claim("5.5", "Cognee chunks query mean", "4.53",
          lambda: telemetry("external-cognee-chunks-grid-v1", "query_latency", "mean_s"), 0.006,
          near="graph build runs at the first query of each checkpoint"),
    Claim("5.5", "scale-cost e8 synthetic value tokens, %", "19",
          lambda: _scale_cost_fallback_pct(8), 0.5,
          near="than the natural-name relabelling holds"),
    # -- abstract: figures printed only in the abstract and tables -------------
    Claim("abs", "LangMem transaction_as_of (micro)", "0.890",
          lambda: micro("external-langmem-v1", "transaction_as_of", cells()),
          near="queries well (0.952 and"),
    Claim("abs", "Cognee reader valid_time hits", "192",
          lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[0], 0.5,
          near="reader answers"),
    Claim("abs", "Cognee reader valid_time cases", "195",
          lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[1], 0.5,
          near="reader answers"),
    Claim("abs", "Hindsight reader valid_time hits", "67",
          lambda: micro_counts("external-hindsight-reflect-v1", "valid_time", cells())[0], 0.5,
          near="Hindsight's answers"),
    Claim("abs", "Mem0 valid_time (micro)", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="historical ones poorly"),
    Claim("abs", "LangMem valid_time (micro)", "0.323",
          lambda: micro("external-langmem-v1", "valid_time", cells()),
          near="historical ones poorly"),
    Claim("abs", "Cognee chunks valid_time, top of the retaining range", "0.015",
          lambda: micro("external-cognee-chunks-grid-v1", "valid_time", cells()),
          near="score between 0.000 and"),
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
    Claim("Tab.claims", "Cognee valid_time beside its claim", "0.015",
          lambda: micro("external-cognee-chunks-grid-v1", "valid_time", cells()),
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


CLAIMS = CLAIMS + _grid_claims() + _scale_claims()


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
            spot = tex.find(claim.near)
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
