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


def lost_history_counts(run: str) -> tuple[int, int]:
    """(non-exact cases, those whose answer holds a superseded or deleted value
    with the expected one absent), purge judged under the request's scope."""
    rows = _purge_scope_module().rows_request_scope(run, cells())
    wrong = [(r, stale) for r, exact, stale in rows if not exact]
    return len(wrong), sum(stale and not r["present_expected"] for r, stale in wrong)


def lost_history_share(run: str) -> float:
    wrong, lost = lost_history_counts(run)
    return 100 * lost / wrong


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


def _purge_scope_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_purge_scope

    return analyze_purge_scope


def overall_rs(run: str, cells_=None, k: int | None = None) -> float:
    """Overall exact with purge under the request's own scope (E-096)."""
    o = _purge_scope_module().overall(run, cells() if cells_ is None else cells_, k)
    return o["request_scope"] / o["questions"]


def overall_rs_count(run: str, cells_=None) -> float:
    return float(_purge_scope_module().overall(run, cells_)["request_scope"])


def _fair_cells() -> set:
    """Cells both Graphiti fairness runs (cosine-only and hybrid) share."""
    mod = _purge_scope_module()
    runs = ("external-graphiti-grid-v1", "external-graphiti-hybrid-v1")
    return set.intersection(*({mod._cell(r) for r in mod._rows(run)} for run in runs))


def _fair(run: str) -> dict:
    return _purge_scope_module().overall(run, _fair_cells())


def _fair_vt(run: str) -> tuple[int, int]:
    rows = [x for x in _purge_scope_module().rows_request_scope(run, _fair_cells())
            if x[0]["category"] == "valid_time"]
    return sum(x[1] for x in rows), len(rows)


def purge_rs(run: str) -> float:
    o = _purge_scope_module().request_scope(run, cells())
    return o["request_scope"] / o["questions"]


def _seed7_cells(run: str) -> set:
    return {cell_key(r) for r in tr(run) if r.get("system") != "oracle" and r["seed"] == 7}


_VARIANCE_CITED = {"mem0": "external-mem0-grid-v2", "graphiti": "external-graphiti-hybrid-v1",
                   "langmem": "external-langmem-v1", "cognee-chunks": "external-cognee-chunks-grid-v3",
                   "cognee-graph": "external-cognee-grid-v1",
                   "hindsight-recall": "external-hindsight-recall-v1",
                   "hindsight-reflect": "external-hindsight-reflect-v1"}


def _replicate_counts(name: str) -> list[float]:
    cited = _VARIANCE_CITED[name]
    runs = [f"variance-{name}-r{r}-v1" for r in (1, 2, 3)]
    return [overall_rs_count(cited, _seed7_cells(cited))] + [overall_rs_count(r, None) for r in runs]


def replicate_rs(name: str) -> float:
    counts = _replicate_counts(name)
    return counts[0] if len(set(counts)) == 1 else -1.0


def replicate_rs_move(name: str) -> float:
    counts = _replicate_counts(name)
    return max(abs(c - counts[0]) for c in counts[1:])


def _grid_claims() -> list[Claim]:
    rows = {
        "external-mem0-grid-v2": "Mem0 (consolidates)",
        "external-langmem-v1": "LangMem (consolidates)",
        "external-graphiti-hybrid-v1": "Graphiti (retains)",
        "external-cognee-chunks-grid-v3": "Cognee \\textsc{chunks} (retains)",
        "external-hindsight-recall-v1": "Hindsight \\textsc{recall} (retains)",
        "external-cognee-grid-v1": "Cognee \\textsc{graph-completion}",
        "external-hindsight-reflect-v1": "Hindsight \\textsc{reflect}       &",
    }
    T = "\\label{tab:reader}"
    out = []
    for run, anchor in rows.items():
        overall = f"{overall_rs(run):.3f}"
        valid = f"{micro(run, 'valid_time', cells()):.3f}"
        purge = f"{purge_rs(run):.3f}"
        out += [
            Claim("Tab.2/3", f"{run} overall, request scope", overall,
                  lambda r=run: overall_rs(r), near=anchor, window=40, after=T),
            Claim("Tab.2/3", f"{run} valid_time (micro)", valid,
                  lambda r=run: micro(r, "valid_time", cells()), near=anchor, window=60, after=T),
            Claim("Tab.2/3", f"{run} purge, request scope", purge,
                  lambda r=run: purge_rs(r), near=anchor, window=90, after=T),
        ]
    E = "\\label{tab:external}"
    trio = ("external-mem0-grid-v2", "external-langmem-v1", "external-graphiti-hybrid-v1")
    for run in trio:
        out += [
            Claim("Tab.2", f"{run} purge row, request scope", f"{purge_rs(run):.3f}",
                  lambda r=run: purge_rs(r), near="\\texttt{purge}               &", window=45, after=E),
            Claim("Tab.2", f"{run} overall row, request scope", f"{overall_rs(run):.3f}",
                  lambda r=run: overall_rs(r), near="Overall exact                &", window=45, after=E),
            Claim("Tab.2", f"{run} exact at k=1, request scope", f"{overall_rs(run, k=1):.3f}",
                  lambda r=run: overall_rs(r, k=1), near="Exact at $k{=}1$             &", window=45, after=E),
            Claim("Tab.2", f"{run} purge as first specified", f"{micro(run, 'purge', cells()):.3f}",
                  lambda r=run: micro(r, "purge", cells()), near="purge\nreads", window=40),
            Claim("Tab.2", f"{run} overall as first specified", f"{micro(run, cells=cells()):.3f}",
                  lambda r=run: micro(r, cells=cells()), near="and overall", window=40,
                  after="as our generator first specified it, purge"),
        ]
    return out


CLAIMS: list[Claim] = [
    # -- Table 1, internal baselines: cell-averaged over 270 cells --------------
    Claim("5.1", "oracle exact (macro), every cell", "1",
          lambda: internal("oracle", "exact_state_accuracy"), near="recall and stale-use at $", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "internal-baseline cells", "270",
          lambda: float(sum(r["system"] == "oracle" for r in res("lifecycle-grid-robust-v1"))), 0.5, near="Across", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "append-only recall", "0.915", lambda: internal("append_only", "evidence_recall"),
          near="recalls the evidence ($", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "append-only exact", "0.272", lambda: internal("append_only", "exact_state_accuracy"),
          near="but answers\n$", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "append-only exact, high churn", "0.255",
          lambda: internal("append_only", "exact_state_accuracy", "high_churn"),
          near="exactly, $", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "append-only stale, high churn", "0.662",
          lambda: internal("append_only", "stale_use_rate", "high_churn"),
          near="under high churn with $", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "last-write-wins exact", "0.603", lambda: internal("last_write_wins", "exact_state_accuracy"),
          near="last-write-wins answers $", after="The oracle is exact; non-temporal baselines are not"),
    Claim("5.1", "BM25@1 (most recent turn) exact", "0.576", lambda: internal("bm25_at_1", "exact_state_accuracy"),
          near="the most recent turn $", after="The oracle is exact; non-temporal baselines are not"),
    # -- 5.2 prose: the subsection the audit found had drifted ------------------
    Claim("5.2", "Mem0 transaction_as_of (micro)", "0.952",
          lambda: micro("external-mem0-grid-v2", "transaction_as_of", cells()),
          near="transaction-scoped current queries"),
    Claim("5.2", "Mem0 valid_time (micro)", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="much weaker on historical valid time"),
    Claim("5.2", "Mem0 lost-history share of non-exact", "87.6",
          lambda: lost_history_share("external-mem0-grid-v2"), 0.06,
          near="Of its non-exact"),
    Claim("5.2", "Mem0 lost-history cases", "170",
          lambda: float(lost_history_counts("external-mem0-grid-v2")[1]), 0.5, near="87.6\\% ("),
    Claim("5.2", "Mem0 non-exact cases (request scope)", "194",
          lambda: float(lost_history_counts("external-mem0-grid-v2")[0]), 0.5, near="87.6\\% (170/"),
    Claim("5.2", "LangMem overall (request scope)", "0.583",
          lambda: overall_rs("external-langmem-v1"), near="every axis --- exact $"),
    Claim("5.2", "LangMem overall at k=1 (request scope)", "0.601",
          lambda: overall_rs("external-langmem-v1", k=1), near="budget-stability ($"),
    Claim("5.2", "LangMem overall at k=5 (request scope)", "0.583",
          lambda: overall_rs("external-langmem-v1", k=5), near="budget-stability ($0.601 \\to\n"),
    Claim("5.2", "Graphiti overall exact (request scope)", "0.194",
          lambda: overall_rs("external-graphiti-hybrid-v1"), near="yet scores $"),
    Claim("5.2", "fairness: Graphiti hybrid hits on shared cells", "29",
          lambda: float(_fair("external-graphiti-hybrid-v1")["request_scope"]), 0.5,
          near="retrieval answers"),
    Claim("5.2", "fairness: Graphiti cosine hits on shared cells", "28",
          lambda: float(_fair("external-graphiti-grid-v1")["request_scope"]), 0.5,
          near="of 154 against"),
    Claim("5.2", "fairness: questions on shared cells", "154",
          lambda: float(_fair("external-graphiti-grid-v1")["questions"]), 0.5,
          near="retrieval answers 29 of"),
    Claim("5.2", "fairness: valid-time hits, both runs", "0",
          lambda: float(max(_fair_vt(r)[0] for r in ("external-graphiti-grid-v1",
                                                     "external-graphiti-hybrid-v1"))), 0.5,
          near="cosine-only, with"),
    Claim("5.2", "fairness: valid-time questions on shared cells", "44",
          lambda: float(_fair_vt("external-graphiti-grid-v1")[1]), 0.5, near="cosine-only, with 0 of"),
    Claim("5.2", "fairness: Mem0 isolated DB (request scope)", "0.599",
          lambda: overall_rs("external-mem0-grid-v2"), near="isolated database scores $"),
    Claim("5.2", "fairness: Mem0 shared DB (request scope)", "0.616",
          lambda: overall_rs("external-mem0-grid-v1"), near="isolated database scores $0.599$ against\n$"),
    Claim("5.2", "Graphiti evidence recall (macro)", "0.937",
          lambda: macro_metric("external-graphiti-hybrid-v1", "evidence_recall"),
          near="It reaches"),
    Claim("5.2", "Graphiti rank-1 names subject, %", "91.3",
          lambda: rank1_names_subject("external-graphiti-hybrid-v1"), 0.06,
          near="naming the queried subject at rank"),
    Claim("5.2", "Mem0 valid_time at k=1 (micro)", "0.379",
          lambda: k_sweep(tr("external-mem0-grid-v2"), budgets=(1,), cells=cells())[1]
          ["by_category"]["valid_time"]["rate"],
          near="is close ("),
    Claim("5.2", "Graphiti valid_time at k=1 (micro)", "0.354",
          lambda: k_sweep(tr("external-graphiti-hybrid-v1"), budgets=(1,), cells=cells())[1]
          ["by_category"]["valid_time"]["rate"],
          near="($0.379$ against $"),
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
    # -- 5.3 deletion ----------------------------------------------------------
    # -- 5.5 cost and latency --------------------------------------------------
    Claim("5.5", "Cognee ingest mean", "0.65",
          lambda: telemetry("external-cognee-grid-v1", "ingest_latency", "mean_s"), 0.006,
          near="averages 6.91\\,s"),
    Claim("5.5", "Cognee query mean", "6.91",
          lambda: telemetry("external-cognee-grid-v1", "query_latency", "mean_s"), 0.006,
          near="measured separately, averages"),
    Claim("5.4", "reader expiry, best of the two (micro)", "0.125",
          lambda: max(micro(r, "expiry_boundary", cells())
                      for r in ("external-cognee-grid-v1", "external-hindsight-reflect-v1")),
          near="Expiry stays low\nfor both readers"),
    Claim("5.4", "expiry cases per configuration", "16",
          lambda: _expiry_cases(), 0.5, near="Expiry stays low\nfor both readers"),
    Claim("Fig.1", "expiry cases per configuration", "16",
          lambda: _expiry_cases(), 0.5, near="Expiry rests on"),
    Claim("Fig.1", "Wilson upper bound of 0 of 16", "0.19",
          lambda: _wilson_zero_of(_expiry_cases()), 0.006, near="Expiry rests on"),
    # -- second backbone: Mem0 and Graphiti grid on gpt-4o (case-weighted) -----
    Claim("5.2", "largest per-category change, gpt-4o vs mini (cases)", "2",
          lambda: _backbone_max_shift(), 0.5, near="otherwise unchanged, moves no category"),
    Claim("5.2", "Mem0 overall, mini (request scope)", "0.599",
          lambda: overall_rs("external-mem0-grid-v2"), near="Mem0 goes from"),
    Claim("5.2", "Mem0 overall, gpt-4o (request scope)", "0.603",
          lambda: overall_rs("external-mem0-grid-gpt4o-v1"), near="Mem0 goes from $0.599$ to"),
    Claim("5.2", "Mem0 valid_time, mini (micro)", "0.364",
          lambda: micro("external-mem0-grid-v2", "valid_time", cells()),
          near="overall and from"),
    Claim("5.2", "Mem0 valid_time, gpt-4o (micro)", "0.374",
          lambda: micro("external-mem0-grid-gpt4o-v1", "valid_time", cells()),
          near="overall and from"),
    Claim("5.2", "Graphiti overall, mini (request scope)", "0.194",
          lambda: overall_rs("external-graphiti-hybrid-v1"), near="Graphiti from"),
    Claim("5.2", "Graphiti overall, gpt-4o (request scope)", "0.192",
          lambda: overall_rs("external-graphiti-hybrid-gpt4o-v1"), near="Graphiti from $0.194$ to"),
    Claim("5.2", "Graphiti valid_time hits, gpt-4o", "0",
          lambda: micro_counts("external-graphiti-hybrid-gpt4o-v1", "valid_time", cells())[0],
          0.5, near="on valid time it\nanswers"),
    Claim("5.2", "Graphiti valid_time hits, mini", "0",
          lambda: micro_counts("external-graphiti-hybrid-v1", "valid_time", cells())[0],
          0.5, near="on valid time it\nanswers"),
    Claim("5.2", "Graphiti valid_time cases", "195",
          lambda: micro_counts("external-graphiti-hybrid-gpt4o-v1", "valid_time", cells())[1],
          0.5, near="on valid time it\nanswers"),
    # -- replicates: four cells, cited run + three repeats (case counts) -------
    Claim("5.2", "Mem0 overall hits, identical in all four runs (request scope)", "58",
          lambda: replicate_rs("mem0"), 0.5, near="exactly for Mem0 and Graphiti ("),
    Claim("5.2", "Graphiti overall hits, identical in all four runs (request scope)", "19",
          lambda: replicate_rs("graphiti"), 0.5, near="exactly for Mem0 and Graphiti (58 and"),
    Claim("5.2", "Cognee reader overall hits, identical in all four runs (request scope)", "84",
          lambda: replicate_rs("cognee-graph"), 0.5, near="for Cognee's reader ("),
    Claim("5.2", "retrieval layers of Cognee and Hindsight, all four runs (request scope)", "19",
          lambda: replicate_rs("cognee-chunks") if replicate_rs("cognee-chunks") == replicate_rs("hindsight-recall") else -1.0,
          0.5, near="retrieval layers of Cognee and Hindsight\n("),
    Claim("5.2", "LangMem largest replicate move (request scope)", "1",
          lambda: replicate_rs_move("langmem"), 0.5, near="move LangMem by at most"),
    Claim("5.2", "cases in the four replicate cells", "97",
          lambda: replicate("mem0", "cases") if replicate("mem0", "cases")
          == replicate("graphiti", "cases") else -1.0, 0.5,
          near="four of the grid's cells ("),
    # -- abstract: figures printed only in the abstract and tables -------------
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
    # -- 5.6 external validity -------------------------------------------------
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
    out = [
        Claim("5.scale", "Mem0 stale share at 32 entities (prose)", "0.463",
              lambda: scale_rate("mem0", 32, "stale"), near="superseded value rises from"),
        Claim("5.scale", "Mem0 stale share at 128 entities (prose)", "0.498",
              lambda: scale_rate("mem0", 128, "stale"), near="superseded value rises from 0.463 to"),
    ]
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
              lambda: lme_pairs("candidates") - lme_pairs("agreement"), 0.5, near="agreed on 43 pairs. The other"),
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
              lambda: lme("Mem0", "valid_time", "cases"), near="valid time (of"),
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
              near="corresponding gap,"),
        Claim("5.real", "grid Hindsight reader valid_time hits", "67",
              lambda: micro_counts("external-hindsight-reflect-v1", "valid_time", cells())[0],
              0.5, near="corresponding gap,"),
        Claim("5.real", "grid reader valid_time cases", "195",
              lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[1], 0.5,
              near="corresponding gap,"),
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
        Claim("intro", "real-data supersessions", "62", lambda: lme_pairs("used"),
              near="in direction on"),
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
              lambda: ceiling_rate(grid, "exact"), near="LangMem 7.\nMem0 reaches"),
        Claim("5.bounds", "Mem0 valid_time, gpt-4o (micro)", "0.374",
              lambda: ceiling_rate(["external-mem0-grid-gpt4o-v1"], "exact"),
              near="LangMem 7.\nMem0 reaches"),
        # The prose says none of the three main-grid runs answers above the
        # ceiling; there is no digit to anchor, so this lambda carries the check.
        Claim("5.bounds", "LangMem valid_time (micro)", "0.323",
              lambda: ceiling_rate(["external-langmem-v1"], "exact")
              if not any(ceiling_rate([r], "beyond") for r in
                         ("external-mem0-grid-v2", "external-mem0-grid-gpt4o-v1",
                          "external-langmem-v1"))
              else -1.0,  # a failed guard must read as drift; NaN would not
              near="LangMem 7.\nMem0 reaches"),
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
        Claim("7", "Cognee chunks v1 worker errors", "40",
              lambda: float(res("external-cognee-chunks-grid-v1")["backbone"]["worker_errors"]), 0.5,
              near="run with"),
        Claim("7", "Cognee chunks v1 overall (micro)", "0.207",
              lambda: micro("external-cognee-chunks-grid-v1", cells=cells()),
              near="once\nreported at"),
        Claim("7", "Cognee chunks replication overall (micro)", "0.194",
              lambda: micro("external-cognee-chunks-grid-v3", cells=cells()),
              near="isolated replication at"),
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
              lambda: read_path("Cognee chunks", "exact"), 0.5, near="lifts valid-time accuracy\nfrom 0", after=A),
        Claim("5.4", "valid-time questions", "195",
              lambda: read_path("Cognee chunks", "questions"), 0.5, near="lifts valid-time accuracy\nfrom 0", after=A),
        Claim("5.4", "Cognee chunks valid-time hits without the rule", "0",
              lambda: read_path("Cognee chunks", "exact_unfiltered"), 0.5, near="lifts valid-time accuracy\nfrom", after=A),
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
              near="restates the later one in 193 of\nthem (", after=B),
        Claim("6.J", "Hindsight 1.1.0 reader valid-time exact", "2",
              lambda: reader_split("hindsight reflect", 1, "exact"), 0.5,
              near="so only", after=B),
        Claim("6.J", "Hindsight 0.9.1 reader valid-time exact", "67",
              lambda: reader_split("hindsight reflect", 0, "exact"), 0.5,
              near="are exact, against", after=B),
    ]
    out.append(Claim("6.J", "Hindsight 1.1.0 reader judged", "195",
                     lambda: h9("h9-judge-gpt4o-hindsight-reflect-latest-v1"), 0.5,
                     near="credits both releases with all", after=B))
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
        # Every removal but the lowest must sit at 1.0, so the second-lowest is checked.
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


# -- Cluster-aware statistics (scripts/analyze_statistics.py) -----------------
_stats_report = None


def stats() -> dict:
    global _stats_report
    if _stats_report is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import analyze_statistics

        _stats_report = analyze_statistics.analyse()
    return _stats_report


def _stats_claims() -> list:
    eq = lambda key: stats()["equivalence"][key]  # noqa: E731
    fam = lambda: stats()["family"]  # noqa: E731
    A = "inference is made over"
    return [
        Claim("5.stats", "histories in the grid", "20",
              lambda: float(stats()["cells"]), 0.5, near="questions come from", after=A),
        Claim("5.stats", "seeds behind the histories", "5",
              lambda: float(max(e["seeds"] for e in fam())), 0.5, near="histories generated from", after=A),
        Claim("5.stats", "comparisons in the declared family", "six",
              lambda: float(len(fam())), 0.5, near="a family of"),
        Claim("5.stats", "same sign in every history", "20",
              lambda: float(min(e["histories_same_sign"] for e in fam())), 0.5,
              near="same sign\nin all", after=A),
        Claim("5.stats", "same sign in every seed", "5",
              lambda: float(min(e["seeds_same_sign"] for e in fam())), 0.5,
              near="histories and all", after=A),
        Claim("5.stats", "history permutation p (mantissa)", "1.9",
              lambda: round(max(e["p_permutation_histories"] for e in fam()) * 1e6, 1), 0.05,
              near="histories gives $p =", after=A),
        Claim("5.stats", "seed permutation floor", "0.0625",
              lambda: max(e["p_permutation_seeds"] for e in fam()), 0.00005,
              near="cannot go below $", after=A),
        Claim("5.stats", "bootstrap draws", "4{,}000",
              lambda: float(stats()["resamples"]), 0.5, near="whole histories ("),
        Claim("5.stats", "equivalence margin that holds", "0.10",
              lambda: 0.10 if eq("margins")["0.1"] else -1.0, near="is equivalent within"),
        Claim("5.stats", "k=1 paired difference", "0.026", lambda: eq("difference"),
              near="(difference $+"),
        Claim("5.stats", "k=1 90% interval low", "0.000", lambda: eq("low90"),
              near="90\\% cluster interval $["),
        Claim("5.stats", "k=1 90% interval high", "0.057", lambda: eq("high90"),
              near="90\\% cluster interval $[0.000, "),
        Claim("5.stats", "equivalence margin that fails", "0.05",
              lambda: 0.05 if not eq("margins")["0.05"] else -1.0, near="but not within"),
    ]


# -- H9: a common reader and an asserted-value judge (docs/preregistration-h9.md)
def h9(run: str, category: str = "valid_time") -> float:
    return float(res(run)["by_category"][category]["exact"])


def h9_rate(run: str, category: str = "valid_time") -> float:
    entry = res(run)["by_category"][category]
    return entry["exact"] / entry["n"]


_GRID_JUDGED = ("cognee-graph-v1", "hindsight-reflect-v1", "cognee-graph-latest-v1",
                "hindsight-reflect-latest-v1")


def judge_agrees_with_scorer() -> tuple[int, int]:
    agree = total = 0
    for run in _GRID_JUDGED:
        rows = [r for r in tr(f"h9-judge-gpt4o-{run}") if r["source_exact"]]
        agree += sum(bool(r["exact"]) for r in rows)
        total += len(rows)
    return agree, total


def judges_agree_percent() -> float:
    agree = total = 0
    for run in _GRID_JUDGED:
        a, b = tr(f"h9-judge-gpt4o-{run}"), tr(f"h9-judge-gpt4omini-{run}")
        if [r["case_id"] for r in a] != [r["case_id"] for r in b]:
            return -1.0
        agree += sum(x["exact"] == y["exact"] for x, y in zip(a, b))
        total += len(a)
    return 100 * agree / total


def _reader_ceiling(reader: str, source: str, which: int) -> float:
    return float(laws().reader_ceiling(reader, source)[which])


def _purge_scope(run: str, key: str) -> float:
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_purge_scope

    return float(analyze_purge_scope.request_scope(run)[key])


def _h9_prediction(threshold: str) -> float:
    text = (ROOT / "docs" / "preregistration-h9.md").read_text(encoding="utf-8")
    return float(threshold) if f"at least {threshold}" in text else -1.0


def _h9_claims() -> list:
    T = "\\label{tab:reader}"
    rows = (("Mem0 (consolidates)", "h9-reader-mem0-v1"),
            ("LangMem (consolidates)", "h9-reader-langmem-v1"),
            ("Graphiti (retains)", "h9-reader-graphiti-v1"),
            ("Cognee \\textsc{chunks} (retains)", "h9-reader-cognee-chunks-v1"),
            ("Hindsight \\textsc{recall} (retains)", "h9-reader-hindsight-recall-v1"),
            ("Cognee \\textsc{graph-completion}", "h9-judge-gpt4o-cognee-graph-v1"),
            ("Hindsight \\textsc{reflect}       &", "h9-judge-gpt4o-hindsight-reflect-v1"))
    out = [Claim("Tab.reader", f"read valid_time: {run}", f"{h9_rate(run):.3f}",
                 lambda r=run: h9_rate(r), near=anchor, window=60, after=T)
           for anchor, run in rows]
    S = "Read, the retaining stores recover most of it"
    C = "Read, the consolidating stores do not"
    out += [
        Claim("5.4", "common reader: Cognee chunks", "142",
              lambda: h9("h9-reader-cognee-chunks-v1"), 0.5, near="answers 142", after=S),
        Claim("5.4", "common reader: Hindsight recall", "150",
              lambda: h9("h9-reader-hindsight-recall-v1"), 0.5, near="answers 142 and", after=S),
        Claim("5.4", "unread retrieval text", "0",
              lambda: micro("external-cognee-chunks-grid-v3", "valid_time", cells()), 0.5,
              near="which the same text unread answers", after=S),
        Claim("5.4", "preregistered common-reader threshold", "0.80",
              lambda: _h9_prediction("0.80"), near="we had predicted at least", after=S),
        Claim("5.4", "common reader: Graphiti", "22",
              lambda: h9("h9-reader-graphiti-v1"), 0.5, near="mostly carry no dates, it answers", after=S),
        Claim("5.4", "Cognee reader exact", "192",
              lambda: micro_counts("external-cognee-grid-v1", "valid_time", cells())[0], 0.5,
              near="Cognee's answers", after=S),
        Claim("5.4", "Hindsight reader exact", "67",
              lambda: micro_counts("external-hindsight-reflect-v1", "valid_time", cells())[0], 0.5,
              near="recovering only", after=S),
        Claim("5.4", "Hindsight reader names right value", "195",
              lambda: reader_split("hindsight reflect", 0, "expected"), 0.5,
              near="names the right value in all", after=S),
        Claim("5.4", "judge agrees with scorer", "1{,}202",
              lambda: float(judge_agrees_with_scorer()[0]), 0.5, near="exact scorer on", after=S),
        Claim("5.4", "answers the scorer accepts", "1{,}203",
              lambda: float(judge_agrees_with_scorer()[1]), 0.5, near="1{,}202 of the", after=S),
        Claim("5.4", "two judges agree, %", "99.6", judges_agree_percent, 0.05,
              near="with a second judge on", after=S),
        Claim("5.4", "Cognee reader judged", "195",
              lambda: h9("h9-judge-gpt4o-cognee-graph-v1"), 0.5, near="credits both readers with", after=S),
        Claim("5.4", "Hindsight reader judged", "195",
              lambda: h9("h9-judge-gpt4o-hindsight-reflect-v1"), 0.5,
              near="credits both readers with 195 of", after=S),
        Claim("5.4", "common reader: Mem0", "73",
              lambda: h9("h9-reader-mem0-v1"), 0.5, near="answers\n73", after=C),
        Claim("5.4", "common reader: LangMem", "71",
              lambda: h9("h9-reader-langmem-v1"), 0.5, near="73 and", after=C),
        Claim("5.4", "Mem0 reader answers beyond ceiling", "One",
              lambda: _reader_ceiling("h9-reader-mem0-v1", "external-mem0-grid-v2", 1), 0.5,
              near="\\S\\ref{sec:bounds}.", after=C),
        Claim("5.4", "LangMem reader answers beyond ceiling", "five",
              lambda: _reader_ceiling("h9-reader-langmem-v1", "external-langmem-v1", 1), 0.5,
              near="One and", after=C),
        Claim("5.4", "purge questions", "45",
              lambda: _purge_scope("external-mem0-grid-v2", "questions"), 0.5,
              near="answers 0 or 1 of"),
        Claim("5.4", "purge, request scope: best of the rest", "1",
              lambda: max(_purge_scope(r, "request_scope") for r in (
                  "external-mem0-grid-v2", "external-graphiti-hybrid-v1",
                  "external-cognee-chunks-grid-v3", "external-hindsight-recall-v1",
                  "external-cognee-grid-v1", "external-hindsight-reflect-v1")), 0.5,
              near="answers 0 or"),
        Claim("5.4", "purge, request scope: LangMem", "9",
              lambda: _purge_scope("external-langmem-v1", "request_scope"), 0.5,
              near="except LangMem ("),
    ]
    return out


# -- H9 on the benchmark conversations ----------------------------------------
_LME_READER = {
    "Mem0": ("lme-bitemporal-mem0-agreement-v1", "lme-bitemporal-mem0-adjudicated-v1"),
    "LangMem": ("lme-bitemporal-langmem-agreement-v1", "lme-bitemporal-langmem-adjudicated-v1"),
    "Graphiti": ("lme-bitemporal-graphiti-agreement-v1", "lme-bitemporal-graphiti-adjudicated-v1"),
    "Cognee chunks": ("lme-bitemporal-cognee-chunks-agreement-v3",
                      "lme-bitemporal-cognee-chunks-adjudicated-v1"),
    "Hindsight recall": ("lme-bitemporal-hindsight-recall-agreement-v2",
                         "lme-bitemporal-hindsight-recall-adjudicated-v1"),
}


def lme_read(system: str) -> float:
    return sum(h9(f"h9-reader-{run}") for run in _LME_READER[system])


def lme_judged(system: str) -> float:
    runs = {"Cognee": ("lme-bitemporal-cognee-graph-agreement-v3",
                       "lme-bitemporal-cognee-graph-adjudicated-v1"),
            "Hindsight": ("lme-bitemporal-hindsight-reflect-agreement-v2",
                          "lme-bitemporal-hindsight-reflect-adjudicated-v1")}[system]
    return sum(h9(f"h9-judge-gpt4o-{run}") for run in runs)


def lme_abstention(what: str) -> float:
    rows = [r for r in tr("h9-reader-lme-bitemporal-cognee-chunks-agreement-v3")
            if r["category"] == "valid_time"]
    source = lambda r: r["source_answer"].casefold()  # noqa: E731
    dated = [r for r in rows
             if any(e.casefold() in source(r) for e in r["expected_values"])
             and any(s.casefold() in source(r) for s in r["stale_values"])
             and len(set(re.findall(r"\[(\d{4}/\d\d/\d\d)", r["source_answer"]))) >= 2]
    return float({"pairs": len(rows), "dated": len(dated),
                  "unknown": sum(r["value"].strip().upper().startswith("UNKNOWN")
                                 for r in dated)}[what])


def _read_range() -> tuple[float, float]:
    rates = [h9_rate(r) for r in ("h9-reader-cognee-chunks-v1", "h9-reader-hindsight-recall-v1",
                                  "h9-judge-gpt4o-cognee-graph-v1",
                                  "h9-judge-gpt4o-hindsight-reflect-v1")]
    return min(rates), max(rates)


def _h9_real_claims() -> list:
    A = "A plain reader does not recover it here"
    return [
        Claim("intro", "retaining stores read: lowest", "0.73", lambda: _read_range()[0],
              0.005, near="return dates answer"),
        Claim("intro", "Graphiti common reader", "0.11", lambda: h9_rate("h9-reader-graphiti-v1"), 0.005,
              near="undated facts"),
        Claim("intro", "retaining stores read: highest", "1.00", lambda: _read_range()[1],
              0.005, near="return dates answer 0.73 to"),
        Claim("5.real", "judged Cognee reader, LME", "29", lambda: lme_judged("Cognee"), 0.5,
              near="does not close it ("),
        Claim("5.real", "judged Hindsight reader, LME", "15", lambda: lme_judged("Hindsight"), 0.5,
              near="does not close it (29 against"),
        Claim("5.real", "common reader, Cognee chunks, LME", "3", lambda: lme_read("Cognee chunks"),
              0.5, near="transcripts, answers", after=A),
        Claim("5.real", "common reader, LME valid-time questions", "60",
              lambda: float(sum(len([r for r in tr(f"h9-reader-{run}") if r["category"] == "valid_time"])
                                for run in _LME_READER["Cognee chunks"])), 0.5,
              near="of 60 valid-time questions from Cognee", after=A),
        Claim("5.real", "common reader, best other store, LME", "13",
              lambda: max(lme_read(s) for s in ("Mem0", "LangMem", "Graphiti", "Hindsight recall")),
              0.5, near="at most", after=A),
        Claim("5.real", "agreement pairs, LME", "41", lambda: lme_abstention("pairs"), 0.5,
              near="For all", after=A),
        Claim("5.real", "agreement pairs with both values and dates", "41",
              lambda: lme_abstention("dated") if lme_abstention("dated") == lme_abstention("pairs")
              else -1.0, 0.5, near="For all", after=A),
        Claim("5.real", "reader abstained", "35", lambda: lme_abstention("unknown"), 0.5,
              near="answered \\textsc{unknown} for", after=A),
    ]


def _latency(run: str, which: str) -> float:
    return float(res(run)["telemetry"][f"{which}_latency"]["p95_s"])


# -- H12: only the retention policy changes (scripts/controlled_policy.py) ------
def policy(name: str, category: str, column: str) -> float:
    return float(res("controlled-policy-v1")["summary"][f"{name}:{category}"][column])


def policy_beyond_ceiling(name: str) -> float:
    from temvera.external_experiment import _events_for
    from temvera.nl_workload import build_nl_cases
    from temvera.reanalysis import consolidation_answerable

    config = json.loads((RUNS / "external-mem0-grid-v2" / "config.json").read_text())
    profiles = {p["name"]: p for p in config["profiles"]}
    rows = [r for r in tr("controlled-policy-v1")
            if r["policy"] == name and r["category"] == "valid_time"]
    beyond = 0
    for cell in sorted({(r["profile"], r["entities"], r["revisions"], r["seed"]) for r in rows}):
        events = _events_for(cell[3], cell[1], cell[2], profiles[cell[0]], True,
                             int(config.get("attributes", 1)),
                             bool(config.get("distinct_values", False)),
                             config.get("natural_pools", "standard"))
        answerable = consolidation_answerable(events, build_nl_cases(events))
        beyond += sum(r["exact_read"] and not answerable[r["case_id"]] for r in rows
                      if (r["profile"], r["entities"], r["revisions"], r["seed"]) == cell)
    return float(beyond)


def _h12_claims() -> list:
    A = "The retention policy alone reproduces the split"
    return [
        Claim("5.4", "consolidate valid_time returned", "75",
              lambda: policy("consolidate", "valid_time", "exact_returned"), 0.5,
              near="Consolidating, the store answers", after=A),
        Claim("5.4", "valid_time questions", "195",
              lambda: policy("consolidate", "valid_time", "n"), 0.5, near="75 of", after=A),
        Claim("5.4", "consolidate valid_time read", "74",
              lambda: policy("consolidate", "valid_time", "exact_read"), 0.5,
              near="as returned and", after=A),
        Claim("5.4", "consolidation ceiling (count)", "75",
              lambda: float(laws().ceiling("external-mem0-grid-v2")[0]), 0.5,
              near="against a ceiling of", after=A),
        Claim("5.4", "consolidate read beyond ceiling", "none",
              lambda: 0.0 if policy_beyond_ceiling("consolidate") == 0 else -1.0, 0.5,
              near="against a ceiling of 75 and with", after=A),
        Claim("5.4", "retain valid_time returned", "31",
              lambda: policy("retain", "valid_time", "exact_returned"), 0.5,
              near="retaining, it answers", after=A),
        Claim("5.4", "retain valid_time read", "151",
              lambda: policy("retain", "valid_time", "exact_read"), 0.5,
              near="as returned and", after="retaining, it answers"),
        Claim("5.4", "transaction-scoped read, both", "228",
              lambda: min(policy(p, "transaction_as_of", "exact_read") for p in ("retain", "consolidate"))
              if policy("retain", "transaction_as_of", "exact_read") == policy("retain", "transaction_as_of", "n")
              else -1.0, 0.5, near="answer all", after=A),
        Claim("5.4", "H12a threshold", "0.05",
              lambda: 0.05 if "retain answers at most 0.05" in (ROOT / "docs" / "preregistration-h11-h12.md").read_text() else -1.0,
              near="we had predicted at most", after=A),
    ]


# -- H8: replicates and gpt-4o for LangMem, Cognee, Hindsight -------------------
_h8_report = None


def h8() -> dict:
    global _h8_report
    if _h8_report is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import analyze_h8

        _h8_report = {"replicates": analyze_h8.replicates(), "backbone": analyze_h8.backbone()}
    return _h8_report


def h8_rate(name: str, model: str, category: str) -> float:
    entry = h8()["backbone"][name][model]
    return entry[category] / entry[f"{category}_n"]


def h8_count(name: str, model: str, category: str) -> float:
    return float(h8()["backbone"][name][model][category])


def h8_rep(name: str) -> list[dict]:
    return h8()["replicates"][name]["replicates"]


def _h8_claims() -> list:
    A = "A stronger backbone moves no system across the divide"
    R = "Repeated runs agree, except one reader"
    rv = lambda name: [r["valid_time"] for r in h8_rep(name)]  # noqa: E731
    return [
        Claim("5.2", "LangMem valid_time, mini", "0.323",
              lambda: h8_rate("langmem", "gpt-4o-mini", "valid_time"), near="LangMem's valid-time accuracy falls from", after=A),
        Claim("5.2", "LangMem valid_time, gpt-4o", "0.262",
              lambda: h8_rate("langmem", "gpt-4o", "valid_time"), near="falls from 0.323 to", after=A),
        Claim("5.2", "LangMem gpt-4o answers beyond ceiling", "no",
              lambda: 0.0 if h8()["backbone"]["langmem"]["ceiling"]["beyond"] == 0 else -1.0, 0.5,
              near="with", after="still under the ceiling"),
        Claim("5.2", "LangMem transaction, mini", "0.890",
              lambda: h8_rate("langmem", "gpt-4o-mini", "transaction_as_of"), near="transaction-scoped\naccuracy from", after=A),
        Claim("5.2", "LangMem transaction, gpt-4o", "0.789",
              lambda: h8_rate("langmem", "gpt-4o", "transaction_as_of"), near="accuracy from 0.890 to", after=A),
        Claim("5.2", "H8d transaction threshold", "0.80",
              lambda: 0.80 if "transaction-scoped\n  accuracy at least 0.80" in (ROOT / "docs" / "preregistration-h8.md").read_text() else -1.0,
              near="below the", after=A),
        Claim("5.2", "Hindsight recall gpt-4o valid time", "0",
              lambda: h8_count("hindsight-recall", "gpt-4o", "valid_time"), 0.5,
              near="retrieval layer answers", after=A),
        Claim("5.2", "Cognee reader gpt-4o valid time", "194",
              lambda: h8_count("cognee-graph", "gpt-4o", "valid_time"), 0.5, near="Cognee's\nreader answers", after=A),
        Claim("5.2", "Hindsight reader gpt-4o valid time", "159",
              lambda: h8_count("hindsight-reflect", "gpt-4o", "valid_time"), 0.5, near="Hindsight's", after="reader answers 194"),
        Claim("5.2", "Hindsight reader mini valid time", "67",
              lambda: h8_count("hindsight-reflect", "gpt-4o-mini", "valid_time"), 0.5, near="exactly where it answered", after=A),
        Claim("5.2", "retrieval layers valid time in replicates", "0",
              lambda: float(max(max(rv(n)) for n in ("cognee-chunks", "hindsight-recall"))), 0.5,
              near="every retaining retrieval layer\nat", after=R),
        Claim("5.2", "valid-time questions in replicate cells", "38",
              lambda: float(h8()["replicates"]["langmem"]["cited"]["valid_time_n"]), 0.5,
              near="layer\nat 0 of", after=R),
        Claim("5.2", "Hindsight reader largest move", "10",
              lambda: float(h8()["replicates"]["hindsight-reflect"]["max_overall_move"]), 0.5,
              near="moves\nby up to", after=R),
        Claim("5.2", "Hindsight reader replicate valid time r1", "8", lambda: float(rv("hindsight-reflect")[0]),
              0.5, near="cases and answers", after=R),
        Claim("5.2", "Hindsight reader replicate valid time r2", "12", lambda: float(rv("hindsight-reflect")[1]),
              0.5, near="answers 8,", after=R),
        Claim("5.2", "Hindsight reader replicate valid time r3", "14", lambda: float(rv("hindsight-reflect")[2]),
              0.5, near="12 and", after=R),
        Claim("5.2", "Hindsight reader cited valid time (4 cells)", "19",
              lambda: float(h8()["replicates"]["hindsight-reflect"]["cited"]["valid_time"]), 0.5,
              near="the cited\nrun answered", after=R),
        Claim("5.2", "Cognee reader valid time in every replicate", "38",
              lambda: float(min(rv("cognee-graph"))) if len(set(rv("cognee-graph"))) == 1 else -1.0, 0.5,
              near="Cognee's reader (", after=R),
    ]


# -- H11b: whole-store census (scripts/store_census.py) ------------------------
def census(system: str, key: str) -> float:
    return float(res("store-census-v1")["summary"][system][key])


def _census_claims() -> list:
    A = "We read whole stores to check this"
    B = "the full-store census of"
    return [
        Claim("4", "revision-only histories in the census", "ten",
              lambda: float(len({(r["entities"], r["seed"]) for r in res("store-census-v1")["rows"]
                                 if r["system"] == "mem0"})), 0.5, near="after ingesting each of the", after=A),
        Claim("4", "Mem0 superseded kept", "none",
              lambda: census("mem0", "kept"), 0.5, near="is not counted) hold", after=A),
        Claim("4", "superseded values", "75", lambda: census("mem0", "superseded"), 0.5,
              near="hold none of", after=A),
        Claim("4", "LangMem superseded kept", "7", lambda: census("langmem", "kept"), 0.5,
              near="LangMem's store holds", after=A),
        Claim("4", "Graphiti superseded kept", "75", lambda: census("graphiti", "kept"), 0.5,
              near="Graphiti's holds all", after=A),
        Claim("4", "Graphiti invalid_at set", "61", lambda: census("graphiti", "invalid_at_set"), 0.5,
              near="for", after="but not reliably:"),
        Claim("4", "Graphiti invalid_at correct day", "43",
              lambda: census("graphiti", "invalid_at_correct"), 0.5, near="and for", after="has the field set,"),
        Claim("5.2f", "census: superseded values with no invalidated edge", "14",
              lambda: census("graphiti", "superseded") - census("graphiti", "invalid_at_set"), 0.5,
              near="census of", after="Two structural limits cap it."),
        Claim("5.bounds", "census: Mem0 keeps", "none", lambda: census("mem0", "kept"), 0.5,
              near="served memories keep", after=B),
        Claim("5.bounds", "census: LangMem keeps", "7", lambda: census("langmem", "kept"), 0.5,
              near="superseded\nvalues, LangMem", after=B),
    ]


# -- H10: deletion across five systems (src/temvera/deletion_study.py) ---------
_DEL_SYSTEMS = ("mem0", "langmem", "graphiti", "cognee", "hindsight")


def deletion(system: str, condition: str, key: str) -> float:
    return float(res(f"deletion-study-{system}-v1")["summary"][f"{system}:{condition}"][key])


def deletion_records(system: str, condition: str) -> list[dict]:
    return [r for r in res(f"deletion-study-{system}-v1")["records"] if r["condition"] == condition]


def mem0_events(condition: str, event: str) -> float:
    return float(sum(r.get("mem0_events", {}).get(event, 0) for r in deletion_records("mem0", condition)))


def mem0_dropped() -> float:
    return float(sum(r["mem0_dropped_actions"] for c in ("prose-1", "prose-2", "prose-3")
                     for r in deletion_records("mem0", c)))


def offpath(system: str, condition: str = "api-oracle", store: str | None = None) -> float:
    return float(sum(any(s["occurrences"] > 0 and (s["store"] == store if store else not s["reachable"])
                         for s in r["stores"])
                     for r in deletion_records(system, condition) if r["purged"]))


def _deletion_claims() -> list:
    T = "\\label{tab:deletion}"
    rows = {"mem0": "Mem0      &", "langmem": "LangMem   &", "graphiti": "Graphiti  &",
            "cognee": "Cognee    &", "hindsight": "Hindsight &"}
    out = []
    for system, anchor in rows.items():
        values = [("prose-1", "leaked"), ("prose-2", "leaked"), ("prose-3", "leaked"),
                  ("api-oracle", "leaked"), ("api-caller", "leaked"), ("api-caller", "kept_present")]
        for condition, key in values:
            value = deletion(system, condition, key)
            out.append(Claim("Tab.del", f"{system} {condition} {key}", f"{value:.0f}",
                             lambda s=system, c=condition, k=key: deletion(s, c, k), 0.5,
                             near=anchor, window=50, after=T))
        value = offpath(system)
        out.append(Claim("Tab.del", f"{system} off-path residue histories", f"{value:.0f}",
                         lambda s=system: offpath(s), 0.5, near=anchor, window=50, after=T))
    S = "We ran all five systems through one deletion protocol"
    P = "Prose is ignored by three systems"
    H = "With the right handles, no API leaves"
    out += [
        Claim("5.3", "seeded histories", "Ten", lambda: float(len(deletion_records("mem0", "prose-1"))), 0.5,
              near="committed before the runs.", after=S),
        Claim("5.3", "purged people", "24", lambda: deletion("mem0", "prose-1", "purged"), 0.5,
              near="histories hold", after=S),
        Claim("5.3", "never-purged people", "36", lambda: deletion("mem0", "prose-1", "kept_total"), 0.5,
              near="purged and", after=S),
        Claim("5.3", "Mem0 DELETE actions under prose-2", "23", lambda: mem0_events("prose-2", "DELETE"), 0.5,
              near="its extractor emitted", after=P),
        Claim("5.3", "Mem0 leaks under prose-2", "2", lambda: deletion("mem0", "prose-2", "leaked"), 0.5,
              near="actions and", after=P),
        Claim("5.3", "Mem0 leaks under prose-1", "24", lambda: deletion("mem0", "prose-1", "leaked"), 0.5,
              near="told the other two,", after=P),
        Claim("5.3", "Mem0 leaks under prose-3", "24", lambda: deletion("mem0", "prose-3", "leaked"), 0.5,
              near="told the other two, 24 of", after=P),
        Claim("5.3", "Mem0 dropped actions logged", "no", mem0_dropped, 0.5,
              near="and it logged", after=P),
        Claim("5.3", "LangMem leaks prose-1", "15", lambda: deletion("langmem", "prose-1", "leaked"), 0.5,
              near="LangMem leaks", after=P),
        Claim("5.3", "LangMem leaks prose-2", "3", lambda: deletion("langmem", "prose-2", "leaked"), 0.5,
              near="LangMem leaks 15,", after=P),
        Claim("5.3", "LangMem leaks prose-3", "6", lambda: deletion("langmem", "prose-3", "leaked"), 0.5,
              near="3 and", after=P),
        Claim("5.3", "LangMem kept under prose-1", "30", lambda: deletion("langmem", "prose-1", "kept_present"), 0.5,
              near="(it answers", after=P),
        Claim("5.3", "H10a threshold", "80",
              lambda: 80.0 if "at least 80% of purged subjects" in (ROOT / "docs" / "preregistration-h10.md").read_text() else -1.0,
              0.5, near="leak at least", after=P),
        Claim("5.3", "off-path residue histories, Mem0/Cognee/Hindsight", "9",
              lambda: min(offpath(s) for s in ("mem0", "cognee", "hindsight")), 0.5, near="in all", after=H),
        Claim("5.3", "Graphiti entity summaries hold it", "9",
              lambda: offpath("graphiti", store="neo4j_entity_nodes"), 0.5, near="hold it in all", after=H),
        Claim("5.3", "Cognee reachable residue after forget", "3",
              lambda: max(offpath("cognee", store="cognee_graph_store"),
                          offpath("cognee", store="cognee_vector_store")),
              0.5, near="up to", after=H),
        Claim("5.3", "LangMem off-path residue", "nothing",
              lambda: offpath("langmem") + offpath("langmem", store="langmem_store"), 0.5,
              near="keeps", after="Only LangMem"),
    ]
    for system, word, value in (("mem0", "Mem0 still answers", None), ("graphiti", "Graphiti", None),
                                ("langmem", "LangMem", None), ("cognee", "Cognee", None),
                                ("hindsight", "and Hindsight", None)):
        out.append(Claim("5.3", f"{system} kept under realistic caller",
                         f"{deletion(system, 'api-caller', 'kept_present'):.0f}",
                         lambda s=system: deletion(s, "api-caller", "kept_present"), 0.5,
                         near=word, after="Of the 36 never-purged people"))
    out.append(Claim("5.3", "purge questions expecting a deleted value", "29",
                     lambda: _purge_scope("external-mem0-grid-v2", "expect_deleted"), 0.5,
                     near="holds earlier values in the projections a query reads, and"))
    return out


def _contribution_census_claims() -> list:
    A = "Evidence for where temporal answers fail"
    return [
        Claim("intro", "served memories keep, Mem0", "0", lambda: census("mem0", "kept"), 0.5,
              near="memories keep", after=A),
        Claim("intro", "served memories keep, LangMem", "7", lambda: census("langmem", "kept"), 0.5,
              near="memories keep 0 and", after=A),
        Claim("intro", "superseded values", "75", lambda: census("mem0", "superseded"), 0.5,
              near="0 and 7 of", after=A),
    ]


def _abstract_claims_v2() -> list:
    A = "\\begin{abstract}"
    retrieval = ("external-graphiti-hybrid-v1", "external-cognee-chunks-grid-v3",
                 "external-hindsight-recall-v1")
    return [
        Claim("abs", "failed preregistered predictions", "sixteen", falsified_predictions, 0.5,
              near="ran;", after=A),
        Claim("abs", "Mem0 valid_time (micro)", "0.364",
              lambda: micro("external-mem0-grid-v2", "valid_time", cells()), near="(Mem0:", after=A),
        Claim("abs", "consolidation ceiling", "0.385",
              lambda: ceiling_rate(["external-mem0-grid-v2"], "ceiling"), near="0.364 against", after=A),
        Claim("abs", "retaining retrieval layers answer no valid-time question", "no",
              lambda: max(micro(r, "valid_time", cells()) for r in retrieval), 0.0005,
              near="the history answer", after=A),
        Claim("abs", "common reader, lowest", "0.73",
              lambda: min(h9_rate(r) for r in ("h9-reader-cognee-chunks-v1", "h9-reader-hindsight-recall-v1")),
              0.005, near="common reader answers", after=A),
        Claim("abs", "common reader, highest", "0.77",
              lambda: max(h9_rate(r) for r in ("h9-reader-cognee-chunks-v1", "h9-reader-hindsight-recall-v1")),
              0.005, near="answers 0.73 to", after=A),
        Claim("abs", "systems ignoring prose", "Three",
              lambda: float(sum(all(deletion(s, c, "leaked") == deletion(s, c, "purged")
                                    for c in ("prose-1", "prose-2", "prose-3")) for s in _DEL_SYSTEMS)),
              0.5, near="common reader does.", after=A),
        Claim("abs", "most never-named people erased", "28",
              lambda: max(deletion(s, "api-caller", "kept_total") - deletion(s, "api-caller", "kept_present")
                          for s in _DEL_SYSTEMS), 0.5, near="erases up to", after=A),
        Claim("abs", "never-named people", "36", lambda: deletion("mem0", "api-caller", "kept_total"), 0.5,
              near="up to\n28 of", after=A),
    ]


def _pre_correction(name: str, key: str) -> float:
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_corrections

    judge = {"cognee-graph": "h11-judge-gpt4o-final-store-cognee-graph-v1",
             "hindsight-reflect": "h11-judge-gpt4o-final-store-hindsight-reflect-v1"}.get(name)
    return float(analyze_corrections.pre_correction(f"final-store-corrections-{name}-v1", judge)[key])


def falsified_predictions() -> float:
    """Rows marked falsified in the outcome tables of the preregistrations."""
    total = 0
    for path in sorted((ROOT / "docs").glob("preregistration-h*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| H") and "**falsified**" in line:
                total += 1
    return float(total)


def _final_store_claims() -> list:
    A = "Asked of the final store, the readers recover most of what it knew"
    pc = _pre_correction
    return [
        Claim("5.corr", "pre-correction questions", "45", lambda: pc("mem0", "questions"), 0.5,
              near="and asked the", after=A),
        Claim("5.corr", "Mem0 strict", "0", lambda: pc("mem0", "strict"), 0.5, near="Mem0 and LangMem\nanswer", after=A),
        Claim("5.corr", "LangMem strict", "0", lambda: pc("langmem", "strict"), 0.5, near="Mem0 and LangMem\nanswer", after=A),
        Claim("5.corr", "Cognee chunks strict", "0", lambda: pc("cognee-chunks", "strict"), 0.5,
              near="Hindsight and Graphiti", after=A),
        Claim("5.corr", "Hindsight recall strict", "4", lambda: pc("hindsight-recall", "strict"), 0.5,
              near="Graphiti 0,", after=A),
        Claim("5.corr", "Graphiti strict", "9", lambda: pc("graphiti", "strict"), 0.5, near="0, 4 and", after=A),
        Claim("5.corr", "Hindsight reader strict", "25", lambda: pc("hindsight-reflect", "strict"), 0.5,
              near="readers of Hindsight and Cognee", after=A),
        Claim("5.corr", "Cognee reader strict", "41", lambda: pc("cognee-graph", "strict"), 0.5,
              near="Hindsight and Cognee 25 and", after=A),
        Claim("5.corr", "retrieval layers, grid scorer, lowest", "21",
              lambda: min(pc(n, "exact") for n in ("cognee-chunks", "hindsight-recall", "graphiti")), 0.5,
              near="retrieval layers score", after=A),
        Claim("5.corr", "retrieval layers, grid scorer, highest", "27",
              lambda: max(pc(n, "exact") for n in ("cognee-chunks", "hindsight-recall", "graphiti")), 0.5,
              near="score 21 to", after=A),
        Claim("5.corr", "Hindsight reader, grid scorer", "34", lambda: pc("hindsight-reflect", "exact"), 0.5,
              near="and the readers", after="score 21 to 27"),
        Claim("5.corr", "Cognee reader, grid scorer", "42", lambda: pc("cognee-graph", "exact"), 0.5,
              near="readers 34\nand", after=A),
        Claim("5.corr", "H11a retrieval-layer threshold", "5",
              lambda: 5.0 if "no retrieval-layer configuration more than 5" in (ROOT / "docs" / "preregistration-h11-h12.md").read_text() else -1.0,
              0.5, near="against the", after="score 21 to 27"),
        Claim("5.corr", "H11a reader threshold", "15",
              lambda: 15.0 if "answers more\n  than 15 exactly" in (ROOT / "docs" / "preregistration-h11-h12.md").read_text() else -1.0,
              0.5, near="against the 5 and", after=A),
    ]


def _claims_table_claims() -> list:
    T = "\\label{tab:claims}"
    rows = (("Graphiti  &", "h9-reader-graphiti-v1"), ("Hindsight$^\\dagger$", "h9-reader-hindsight-recall-v1"),
            ("Cognee    &", "h9-reader-cognee-chunks-v1"), ("Mem0      &", "h9-reader-mem0-v1"),
            ("LangMem   &", "h9-reader-langmem-v1"))
    out = [Claim("Tab.claims", f"read valid_time {run}", f"{h9_rate(run):.3f}",
                 lambda r=run: h9_rate(r), near=anchor, window=110, after=T) for anchor, run in rows]
    out.append(Claim("Tab.rel", "readers judged valid time, both releases", "195",
                     lambda: min(h9(f"h9-judge-gpt4o-{r}") for r in _GRID_JUDGED), 0.5,
                     near="answers all", after="\\caption{The main grid on the measured"))
    return out


# -- H13 (docs/preregistration-h13.md) ----------------------------------------
def minimal_pairs(kind: str | None = None, template: str | None = None, key: str = "judge_right") -> float:
    summary = res("judge-minimal-pairs-v1")["summary"]
    return float(sum(v[key] if key != "n" else v["n"] for k, v in summary.items()
                     if (kind is None or k.startswith(kind + ":"))
                     and (template is None or k.endswith(":" + template))))


def _h15():
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_h15

    return analyze_h15


def _h15_right(run: str) -> float:
    return float(sum(r for r, _ in _h15().template_accuracy(run).values()))


def _h15_consensus(source: str) -> float:
    return float(_h15().consensus(source)["both"])


def _h15_claims() -> list:
    C = "Asked of the final store, the readers recover most of what it knew"
    native = ("final-store-corrections-cognee-graph-v1", "final-store-corrections-hindsight-reflect-v1")
    return [
        Claim("5.corr", "gpt-4o right on constructed answers", "450",
              lambda: _h15_right("h15-annotate-gpt4o-v1"), 0.5, near="They are right on", after=C),
        Claim("5.corr", "gpt-5.4 right on constructed answers", "448",
              lambda: _h15_right("h15-annotate-gpt54-v1"), 0.5, near="right on 450 and", after=C),
        Claim("5.corr", "constructed answers", "450",
              lambda: float(sum(n for _, n in _h15().template_accuracy("h15-annotate-gpt4o-v1").values())),
              0.5, near="448\nof", after=C),
        Claim("5.corr", "annotator agreement on reader answers", "89",
              lambda: float(_h15().agreement("native")[0]), 0.5, near="agree on", after=C),
        Claim("5.corr", "reader answers annotated", "90",
              lambda: float(_h15().agreement("native")[1]), 0.5, near="agree on 89 of the", after=C),
        Claim("5.corr", "consensus credits Cognee reader", "42",
              lambda: _h15_consensus(native[0]), 0.5, near="Cognee's reader", after=C),
        Claim("5.corr", "consensus credits Hindsight reader", "29",
              lambda: _h15_consensus(native[1]), 0.5, near="times and Hindsight's", after=C),
        Claim("5.corr", "strict passes rejected by an annotator (none)", "no",
              lambda: float(sum(_h15().consensus(s)["strict_not_credited_by_either"] for s in native)),
              0.5, near="they reject", after=C),
    ]


def timing(model: str, answer: str) -> float:
    return float(res("lme-timing-labels-v1")["summary"]["by_model"][model][answer])


def persist_lme(system: str) -> float:
    return sum(h9(f"h13-persist-{run}") for run in _LME_READER[system])


def persist_unknown_agreement() -> float:
    rows = [r for r in tr("h13-persist-lme-bitemporal-cognee-chunks-agreement-v3") if r["category"] == "valid_time"]
    return float(sum(r["value"].strip().upper().startswith("UNKNOWN") for r in rows))


def verified(system: str, key: str) -> float:
    return float(res(f"deletion-verified-{system}-v1")["summary"][f"{system}:api-verified"][key])


def langmem_deletes(condition: str, key: str) -> float:
    return float(res("deletion-langmem-deletes-v1")["summary"][f"langmem:{condition}"][key])


def final_store_read(name: str) -> float:
    return _pre_correction_read(name)


def _pre_correction_read(name: str) -> float:
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_corrections

    return float(analyze_corrections.pre_correction(
        f"final-store-corrections-{name}-v1", f"h13-reader-final-store-{name}")["judged"])


def _h13_claims() -> list:
    J = "Read, the retaining stores recover most of it"
    G = "LongMemEval does not say when a change"
    P = "A plain reader does not recover it here"
    D = "Prose is ignored by three systems"
    W = "Without the handles, an unchecked caller"
    F = "Asked of the final store, the readers recover most of what it knew"
    return [
        Claim("5.4", "judge right on constructed valid-time answers", "279",
              lambda: minimal_pairs("valid_time"), 0.5, near="and is right on", after=J),
        Claim("5.4", "constructed valid-time answers", "280",
              lambda: minimal_pairs("valid_time", key="n"), 0.5, near="right on 279\nof", after=J),
        Claim("5.4", "valid-time templates", "seven",
              lambda: float(sum(1 for k in res("judge-minimal-pairs-v1")["summary"] if k.startswith("valid_time:"))),
              0.5, near="construction (", after=J),
        Claim("5.4", "questions per template", "40",
              lambda: minimal_pairs("valid_time", "value_only", "n"), 0.5, near="templates over", after=J),
        Claim("5.real", "timing pairs identified by both quote-checked labellers", "none",
              lambda: float(res("h15-lme-timing-quotes-v1")["summary"]["identified"]), 0.5,
              near="agree on a date for", after=G),
        Claim("5.real", "timing pairs relabelled", "60",
              lambda: float(res("h15-lme-timing-quotes-v1")["summary"]["pairs"]), 0.5,
              near="none of the", after=G),
        Claim("5.real", "gpt-5.4 UNKNOWN labels", "60",
              lambda: float(res("h15-lme-timing-quotes-v1")["summary"]["by_model"]["gpt-5.4-2026-03-05"]["UNKNOWN"]),
              0.5, near="for all", after=G),
        Claim("5.real", "persistence contract, Cognee chunks LME", "7", lambda: persist_lme("Cognee chunks"), 0.5,
              near="changes little ---", after=P),
        Claim("5.real", "persistence contract, still unknown", "31", persist_unknown_agreement, 0.5,
              near="still \\textsc{unknown} for", after=P),
        Claim("5.real", "persistence contract, grid Cognee chunks", "0.733",
              lambda: h9_rate("h13-persist-external-cognee-chunks-grid-v3"), near="does no harm (", after=P),
        Claim("5.real", "persistence contract, grid Hindsight recall", "0.851",
              lambda: h9_rate("h13-persist-external-hindsight-recall-v1"), near="(0.733 and", after=P),
        Claim("5.3", "LangMem deletes enabled, leaks", "none",
              lambda: sum(langmem_deletes(c, "leaked") for c in ("prose-1", "prose-2", "prose-3")), 0.5,
              near="deletion\nenabled it leaks", after=D),
        Claim("5.3", "LangMem deletes enabled, kept prose-1", "6", lambda: langmem_deletes("prose-1", "kept_present"),
              0.5, near="keeps only", after=D),
        Claim("5.3", "LangMem deletes enabled, kept prose-2", "8", lambda: langmem_deletes("prose-2", "kept_present"),
              0.5, near="keeps only 6,", after=D),
        Claim("5.3", "LangMem deletes enabled, kept prose-3", "2", lambda: langmem_deletes("prose-3", "kept_present"),
              0.5, near="8 and", after=D),
        Claim("5.3", "verified caller keeps all", "36",
              lambda: min(verified(s, "kept_present") for s in ("mem0", "graphiti", "cognee", "hindsight")), 0.5,
              near="keeps all", after=W),
        Claim("5.3", "verified caller LangMem kept", "33", lambda: verified("langmem", "kept_present"), 0.5,
              near="Graphiti, Cognee and Hindsight, and", after=W),
        Claim("5.3", "verified caller leaks", "0",
              lambda: sum(verified(s, "leaked") for s in _DEL_SYSTEMS), 0.5,
              near="removes every purged value as well", after=W),
        Claim("5.3", "LangMem kept under oracle", "30", lambda: deletion("langmem", "api-oracle", "kept_present"),
              0.5, near="keeps only 30", after=W),
        Claim("5.corr", "common reader final store, Cognee chunks", "8", lambda: final_store_read("cognee-chunks"),
              0.5, near="the correction, for", after=F),
        Claim("5.corr", "common reader final store, Hindsight recall", "8", lambda: final_store_read("hindsight-recall"),
              0.5, near="the correction, for", after=F),
        Claim("5.corr", "common reader final store, Graphiti", "2", lambda: final_store_read("graphiti"),
              0.5, near="Hindsight's recall,", after=F),
        Claim("5.corr", "common reader final store, Mem0 and LangMem", "none",
              lambda: final_store_read("mem0") + final_store_read("langmem"), 0.5, near="Graphiti and", after=F),
        Claim("5.corr", "judge credits history-stated known-then answers", "3",
              lambda: minimal_pairs("known_then", "history_stated"), 0.5, near="credits them", after=F),
        Claim("5.corr", "known-then constructed answers per template", "40",
              lambda: minimal_pairs("known_then", "history_stated", "n"), 0.5, near="3 times in", after=F),
    ]


# -- H14: one store growing to 3,000 turns (scripts/scale_cost.py) ------------
def _growth():
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_scale_cost

    return analyze_scale_cost


def growth_cp(system: str, turns: int) -> dict:
    return next(c for c in res(f"scale-growth-{system}-v1")["checkpoints"] if c["turns"] == turns)


def growth_exact(system: str, path: str, turns: int, category: str) -> float:
    return float(_growth().rate(growth_cp(system, turns), path, category)[0])


def growth_judged(path: str, turns: int, category: str) -> float:
    src, jud = tr("scale-growth-hindsight-v1"), tr("h14-judge-gpt4o-scale-growth-hindsight-v1")
    if [r["case_id"] for r in src] != [r["case_id"] for r in jud]:
        return -1.0
    return float(sum(bool(j["exact"]) for s, j in zip(src, jud)
                     if s["path"] == path and s["checkpoint"] == turns and s["category"] == category))


def _growth_claims() -> list:
    T = "\\label{tab:growth}"
    gp = lambda s, n: _growth().per_turn(growth_cp(s, n))["usd"]  # noqa: E731
    q95 = lambda s, n, p="retrieval": growth_cp(s, n)["query_latency"][p]["p95_s"]  # noqa: E731
    rows = (("mem0", "Mem0                &"), ("graphiti", "Graphiti            &"),
            ("hindsight", "Hindsight \\textsc{recall}  &"))
    out = []
    for system, anchor in rows:
        out += [
            Claim("Tab.growth", f"{system} $/turn at 100", f"{gp(system, 100):.5f}".lstrip("0"),
                  lambda s=system: gp(s, 100), 0.000005, near=anchor, window=30, after=T),
            Claim("Tab.growth", f"{system} $/turn at 3000", f"{gp(system, 3000):.5f}".lstrip("0"),
                  lambda s=system: gp(s, 3000), 0.000005, near=anchor, window=45, after=T),
            Claim("Tab.growth", f"{system} query p95 at 100", f"{q95(system, 100):.2f}",
                  lambda s=system: q95(s, 100), 0.005, near=anchor, window=60, after=T),
            Claim("Tab.growth", f"{system} query p95 at 3000", f"{q95(system, 3000):.2f}",
                  lambda s=system: q95(s, 3000), 0.005, near=anchor, window=75, after=T),
            Claim("Tab.growth", f"{system} current exact at 3000",
                  f"{growth_exact(system, 'retrieval', 3000, 'current'):.0f}",
                  lambda s=system: growth_exact(s, "retrieval", 3000, "current"), 0.5,
                  near=anchor, window=85, after=T),
            Claim("Tab.growth", f"{system} valid exact at 3000",
                  f"{growth_exact(system, 'retrieval', 3000, 'valid_time'):.0f}",
                  lambda s=system: growth_exact(s, "retrieval", 3000, "valid_time"), 0.5,
                  near=anchor, window=95, after=T),
        ]
    R = "Hindsight \\textsc{reflect} & (shared)"
    out += [
        Claim("Tab.growth", "reader p95 at 100", "10.78", lambda: q95("hindsight", 100, "reader"), 0.005,
              near=R, window=40, after=T),
        Claim("Tab.growth", "reader p95 at 3000", "36.91", lambda: q95("hindsight", 3000, "reader"), 0.005,
              near=R, window=50, after=T),
        Claim("Tab.growth", "reader current exact at 3000", "5",
              lambda: growth_exact("hindsight", "reader", 3000, "current"), 0.5, near=R, window=60, after=T),
        Claim("Tab.growth", "reader valid exact at 3000", "34",
              lambda: growth_exact("hindsight", "reader", 3000, "valid_time"), 0.5, near=R, window=70, after=T),
    ]
    A = "One seeded history of 3{,}000 turns"
    W = "Reading is where the designs part"
    S = "The split widens along this trajectory"
    conc = lambda k, f: res("scale-growth-hindsight-v1")["concurrency"][k][f]  # noqa: E731
    dep = lambda s, f: _growth().deployment_cost(res(f"scale-growth-{s}-v1"), 1000, 10)[f]  # noqa: E731
    out += [
        Claim("5.cost", "people in the history", "200",
              lambda: float(json.loads((RUNS / "scale-growth-mem0-v1" / "config.json").read_text())["workload"]["entities"]),
              0.5, near="turns (", after=A),
        Claim("5.cost", "probe questions per kind", "40",
              lambda: float(json.loads((RUNS / "scale-growth-mem0-v1" / "config.json").read_text())["probes_per_kind"]),
              0.5, near="Probe questions ask", after=A),
        Claim("5.cost", "Hindsight write cost rise, %", "20",
              lambda: 100 * (gp("hindsight", 3000) / gp("hindsight", 100) - 1), 1.0,
              near="Hindsight's rises by", after="Write cost per turn does not grow"),
        Claim("5.cost", "extract-on-write ingest p95, lowest", "7",
              lambda: min(c["ingest_latency"]["p95_s"] for s in ("mem0", "graphiti")
                          for c in res(f"scale-growth-{s}-v1")["checkpoints"]), 0.5,
              near="Ingest p95 stays near", after="Write cost per turn does not grow"),
        Claim("5.cost", "extract-on-write ingest p95, highest", "9",
              lambda: max(c["ingest_latency"]["p95_s"] for s in ("mem0", "graphiti")
                          for c in res(f"scale-growth-{s}-v1")["checkpoints"]), 0.5,
              near="stays near 7--", after="Write cost per turn does not grow"),
        Claim("5.cost", "Hindsight ingest p95", "3",
              lambda: max(c["ingest_latency"]["p95_s"] for c in res("scale-growth-hindsight-v1")["checkpoints"]),
              0.5, near="systems and", after="Write cost per turn does not grow"),
        Claim("5.cost", "Mem0/Graphiti retrieval p95 bound", "0.4",
              lambda: 0.4 if max(c["query_latency"]["retrieval"]["p95_s"] for s in ("mem0", "graphiti")
                                 for c in res(f"scale-growth-{s}-v1")["checkpoints"]) < 0.4 else -1.0,
              0.0, near="p95 of at most", after=W),
        Claim("5.cost", "H14c threshold", "2",
              lambda: 2.0 if "query p95\n  is under 2 s" in (ROOT / "docs" / "preregistration-h14.md").read_text() else -1.0,
              0.0, near="above the", after=W),
        Claim("5.cost", "Hindsight recall p95 at 3000 (text)", "2.3",
              lambda: q95("hindsight", 3000), 0.05, near="at every size, Hindsight's", after=W),
        Claim("5.cost", "reader p95 at 100 (text)", "10.8", lambda: q95("hindsight", 100, "reader"), 0.05,
              near="slows from", after=W),
        Claim("5.cost", "reader p95 at 3000 (text)", "36.9", lambda: q95("hindsight", 3000, "reader"), 0.05,
              near="slows from 10.8 to", after=W),
        Claim("5.cost", "reader $/q at 100", "0.0068", lambda: _growth().per_query(growth_cp("hindsight", 100)),
              0.00005, near="from \\$", after=W),
        Claim("5.cost", "reader $/q at 3000", "0.0199", lambda: _growth().per_query(growth_cp("hindsight", 3000)),
              0.00005, near="0.0068 to \\$", after=W),
        Claim("5.cost", "throughput, one client", "0.47", lambda: conc("1", "throughput_qps"), 0.005,
              near="saturates:", after=W),
        Claim("5.cost", "throughput, sixteen clients", "0.84", lambda: conc("16", "throughput_qps"), 0.005,
              near="one client,", after=W),
        Claim("5.cost", "p95 at sixteen clients", "19.9", lambda: conc("16", "latency")["p95_s"], 0.05,
              near="at a p95 of", after=W),
        Claim("5.cost", "Mem0 deployment cost", "0.57", lambda: dep("mem0", "total_usd"), 0.005,
              near="Mem0 costs \\$", after=W),
        Claim("5.cost", "Graphiti deployment cost", "1.11", lambda: dep("graphiti", "total_usd"), 0.005,
              near="Graphiti \\$", after=W),
        Claim("5.cost", "Hindsight deployment cost", "201", lambda: dep("hindsight", "total_usd"), 0.5,
              near="reader \\$", after=W),
        Claim("5.cost", "Neo4j resident GB", "2.5",
              lambda: growth_cp("graphiti", 3000)["server_rss_kb"]["neo4j"] / 1e6, 0.05, near="Neo4j's processes is about", after=W),
        Claim("5.cost", "Hindsight daemon GB", "2.8",
              lambda: growth_cp("hindsight", 3000)["server_rss_kb"]["hindsight_daemon"] / 1e6, 0.05,
              near="Hindsight's daemon", after=W),
        Claim("5.cost", "PostgreSQL GB", "1.5",
              lambda: growth_cp("hindsight", 3000)["server_rss_kb"]["postgres"] / 1e6, 0.05,
              near="its PostgreSQL", after=W),
        Claim("5.cost", "Graphiti current exact at 100", "38",
              lambda: growth_exact("graphiti", "retrieval", 100, "current"), 0.5, near="Hindsight answer", after=S),
        Claim("5.cost", "Hindsight recall current exact at 100", "39",
              lambda: growth_exact("hindsight", "retrieval", 100, "current"), 0.5, near="answer 38 and", after=S),
        Claim("5.cost", "Mem0 current exact at 3000 (text)", "38",
              lambda: growth_exact("mem0", "retrieval", 3000, "current"), 0.5, near="while Mem0\nkeeps", after=S),
        Claim("5.cost", "reader judged current at 3000", "38", lambda: growth_judged("reader", 3000, "current"),
              0.5, near="credits", after=S),
        Claim("5.cost", "reader judged valid at 3000", "40", lambda: growth_judged("reader", 3000, "valid_time"),
              0.5, near="current and", after=S),
    ]
    return out


CLAIMS = CLAIMS + _grid_claims() + _scale_claims() + _real_claims() + _bounds_claims() + _corrections_claims() + _audit_claims() + _read_path_claims() + _releases_claims() + _coverage_claims() + _stats_claims() + _h9_claims() + _h9_real_claims() + _h12_claims() + _h8_claims() + _census_claims() + _deletion_claims() + _abstract_claims_v2() + _growth_claims() + [Claim("Lim", "largest store run, turns", "3{,}000", lambda: float(max(c['turns'] for c in res('scale-growth-mem0-v1')['checkpoints'])), 0.5, near="one history up to")] + _final_store_claims() + _claims_table_claims() + _h13_claims() + _contribution_census_claims() + _h15_claims() + [Claim("7", "falsified preregistered predictions", "sixteen", falsified_predictions, 0.5, near="Within the thesis, \\textbf{")]


# Small counts the prose spells out; the printed word is still what is searched.
_WORDS = {"Three": 3, "nothing": 0, "Ten": 10, "no": 0, "none": 0, "One": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
          "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16}


def _number(printed: str) -> float:
    return float(_WORDS.get(printed, printed.replace("{,}", "")))


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
        if abs(actual - _number(claim.printed)) > claim.tol:
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
