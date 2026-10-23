"""Regenerate paper figures from sealed run artifacts.

Every figure is derived from `experiments/runs/*/results.json` or
`transcript.jsonl` via `temvera.reanalysis`, so figures cannot drift from the
numbers in the evidence ledger. Run:

    python scripts/make_figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
# matplotlib defaults to Type 3 fonts, which are bitmapped: they render blurry,
# leave figure text unsearchable, and are what publisher format checkers reject.
# 42 is TrueType.
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
import matplotlib.pyplot as plt  # noqa: E402

from temvera.reanalysis import (  # noqa: E402
    category_counts,
    k_sweep,
    load_run,
    load_transcript,
    matched_cells,
)

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
OUT = ROOT / "paper" / "figures"
# matplotlib stamps a CreationDate into every PDF, so regenerating the
# figures changes their bytes even when the plot is identical. Pin it so a
# reviewer can diff a regenerated figure against the shipped one.
_PDF_METADATA = {"CreationDate": None, "Producer": "temvera", "Creator": "temvera"}
# Latest runs: matched grid by design, isolated Mem0 database, and Graphiti
# under the hybrid retrieval it actually ships.
MEM0 = RUNS / "external-mem0-grid-v2"
GRAPHITI = RUNS / "external-graphiti-hybrid-v1"
LANGMEM = RUNS / "external-langmem-v1"
COGNEE = RUNS / "external-cognee-chunks-grid-v3"  # retrieval layer, comparable
COGNEE_READER = RUNS / "external-cognee-grid-v1"  # LLM reader
HINDSIGHT = RUNS / "external-hindsight-recall-v1"  # retrieval layer
HINDSIGHT_READER = RUNS / "external-hindsight-reflect-v1"  # LLM reader
CATEGORIES = ("transaction_as_of", "valid_time", "expiry_boundary", "purge")
LABELS = {
    "transaction_as_of": "transaction\nas-of",
    "valid_time": "valid time\n(historical)",
    "expiry_boundary": "expiry\nboundary",
    "purge": "purge\n(deletion)",
}


def _cells():
    return matched_cells(
        load_run(MEM0), load_run(GRAPHITI), load_run(LANGMEM),
        load_run(COGNEE), load_run(COGNEE_READER),
        load_run(HINDSIGHT), load_run(HINDSIGHT_READER),
    )


def _request_scope(run: str, counts: dict, cells) -> dict:
    """Purge scored under the request's own scope (evidence ledger E-096)."""
    import sys

    from temvera.reanalysis import Proportion

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analyze_purge_scope

    scope = analyze_purge_scope.request_scope(run.name, cells)
    return {**counts, "purge": Proportion(scope["request_scope"], scope["questions"])}


def figure_categories(cells) -> None:
    """Per-category exact accuracy with Wilson intervals, matched cells; purge
    under the request's own scope."""
    rs = lambda run: _request_scope(  # noqa: E731
        run, category_counts(load_transcript(run), cells=cells), cells)
    series = (
        ("Mem0", rs(MEM0), "#3b6ea5"),
        ("LangMem", rs(LANGMEM), "#4f8f5b"),
        ("Graphiti", rs(GRAPHITI), "#c2703d"),
        ("Cognee (chunks)", rs(COGNEE), "#8a6bbf"),
        ("Hindsight (recall)", rs(HINDSIGHT), "#b08a3e"),
        ("Cognee (reader)", rs(COGNEE_READER), "#3f7f7f"),
        ("Hindsight (reader)", rs(HINDSIGHT_READER), "#7f5f9f"),
    )
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    width = 0.12
    for offset, (name, data, colour) in enumerate(series):
        xs, ys, lo, hi = [], [], [], []
        for index, category in enumerate(CATEGORIES):
            p = data.get(category)
            if p is None:
                continue
            low, high = p.wilson()
            xs.append(index + (offset - 3) * width)
            ys.append(p.rate)
            lo.append(p.rate - low)
            hi.append(high - p.rate)
        ax.bar(xs, ys, width, label=name, color=colour)
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor="black", capsize=3, lw=1)
    ax.axhline(1.0, ls="--", lw=1, color="grey")
    ax.text(3.45, 1.02, "oracle = 1.0 (by construction)", ha="right", fontsize=8, color="grey")
    ax.set_xticks(range(len(CATEGORIES)))
    ax.set_xticklabels([LABELS[c] for c in CATEGORIES], fontsize=9)
    ax.set_ylabel("exact accuracy")
    ax.set_ylim(0, 1.12)
    # Below the axes: inside, seven entries cover the oracle line and its label.
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2),
              fontsize=7, ncol=4)
    ax.set_title(
        "Per-category exact accuracy, 20 matched cells (Wilson 95% intervals)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(OUT / "categories.pdf", metadata=_PDF_METADATA, bbox_inches="tight")
    plt.close(fig)


def figure_budget(cells) -> None:
    """Exact accuracy versus retrieval budget k — the confound reviewers found."""
    budgets = (1, 2, 3, 5)
    mem0 = k_sweep(load_transcript(MEM0), budgets=budgets, cells=cells)
    graphiti = k_sweep(load_transcript(GRAPHITI), budgets=budgets, cells=cells)
    langmem = k_sweep(load_transcript(LANGMEM), budgets=budgets, cells=cells)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    for ax, metric, title in (
        (axes[0], "overall", "overall exact"),
        (axes[1], "valid_time", "valid-time exact"),
    ):
        for name, data, colour, marker in (
            ("Mem0", mem0, "#3b6ea5", "o"),
            ("LangMem", langmem, "#4f8f5b", "^"),
            ("Graphiti", graphiti, "#c2703d", "s"),
        ):
            ys = []
            for k in budgets:
                entry = data[k]
                ys.append(
                    entry["overall"]["rate"]
                    if metric == "overall"
                    else entry["by_category"].get(metric, {}).get("rate", float("nan"))
                )
            ax.plot(budgets, ys, marker=marker, color=colour, label=name)
        ax.set_xlabel("retrieval budget $k$")
        ax.set_title(title, fontsize=10)
        ax.set_xticks(budgets)
        ax.set_ylim(0, 1.0)
    axes[0].set_ylabel("exact accuracy")
    axes[0].legend(frameon=False)
    fig.suptitle(
        "Consolidating stores are budget-stable; Graphiti's deficit appears only as $k$ grows",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(OUT / "budget.pdf", metadata=_PDF_METADATA)
    plt.close(fig)


def figure_residual() -> None:
    """Where purged payloads survive, split by reachability class."""
    import json

    # The reference implementation is anonymised: the paper is submitted for
    # double-blind review and the project name would identify the authors.
    label = {"temvera": "Reference impl.", "mem0": "Mem0", "graphiti": "Graphiti"}
    # Append-only audit logs are not read by any query path; everything else is
    # reachable from retrieval.
    audit_stores = {"raw_ledger_jsonl", "mem0_history_sqlite"}
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    for ax, tag, title in (
        (axes[0], "nl", "natural-language instruction"),
        (axes[1], "api", "native deletion API"),
    ):
        data = json.loads(
            (RUNS / f"purge-residual-v3-{tag}" / "results.json").read_text("utf-8")
        )
        reach = {"Reference impl.": 0, "Mem0": 0, "Graphiti": 0}
        audit = {"Reference impl.": 0, "Mem0": 0, "Graphiti": 0}
        for report in data["reports"]:
            name = label[report["system"]]
            for store in report["stores"]:
                bucket = audit if store["store"] in audit_stores else reach
                bucket[name] += max(0, store["occurrences"])
        names = list(reach)
        ax.bar(names, [reach[n] for n in names], label="retrieval-reachable", color="#b3462f")
        ax.bar(
            names,
            [audit[n] for n in names],
            bottom=[reach[n] for n in names],
            label="append-only log (not queried)",
            color="#c9c9c9",
        )
        ax.set_title(title, fontsize=10)
    axes[0].set_ylabel("residual occurrences")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle(
        "Deletion works through the API; prose deletion intent does not survive extraction",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(OUT / "residual.pdf", metadata=_PDF_METADATA)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cells = _cells()
    figure_categories(cells)
    figure_budget(cells)
    figure_residual()
    print(f"wrote figures to {OUT} over {len(cells)} matched cells")


if __name__ == "__main__":
    main()
