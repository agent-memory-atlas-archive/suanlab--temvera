"""Recompute every number the paper reports, offline, from sealed runs.

Experiments-track papers are judged on their artifacts. Regenerating the runs
needs an OpenAI key, a Neo4j server, and a second virtualenv for LangMem, so
this script provides the path that needs none of them: each run ships a sealed
per-case ``transcript.jsonl``, and every reported figure is an aggregation over
those transcripts. A committee can therefore verify the paper's arithmetic
without credentials, and separately decide whether to re-run generation.

    python scripts/recompute_paper_numbers.py            # print the table
    python scripts/recompute_paper_numbers.py --check    # also verify seals

Exit status is non-zero if a seal fails or an expected run is missing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from temvera.reanalysis import (
    abstention,
    category_counts,
    k_sweep,
    load_run,
    load_transcript,
    matched_cells,
    overall_counts,
)

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
SYSTEMS = {
    "Mem0": "external-mem0-grid-v2",
    "LangMem": "external-langmem-v1",
    "Graphiti": "external-graphiti-hybrid-v1",
    "Cognee-retr": "external-cognee-chunks-grid-v1",
    "Hindsight-retr": "external-hindsight-recall-v1",
    "Cognee-read": "external-cognee-grid-v1",
    "Hindsight-read": "external-hindsight-reflect-v1",
}
CATEGORIES = ("transaction_as_of", "valid_time", "expiry_boundary", "purge")
DELETION = {"natural-language": "purge-residual-v3-nl", "native API": "purge-residual-v3-api"}


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def verify_seals(names: list[str]) -> None:
    print("== seal verification ==")
    for name in names:
        result = subprocess.run(
            [sys.executable, "-m", "temvera.cli", "verify-run", str(RUNS / name)],
            capture_output=True,
            text=True,
        )
        ok = '"valid": true' in result.stdout
        print(f"  {name:<34} {'ok' if ok else 'FAILED'}")
        if not ok:
            _fail(f"seal verification failed for {name}")
    print()


def main() -> int:
    missing = [n for n in (*SYSTEMS.values(), *DELETION.values()) if not (RUNS / n).is_dir()]
    if missing:
        _fail(f"missing runs: {missing}")
    if "--check" in sys.argv:
        verify_seals([*SYSTEMS.values(), *DELETION.values()])

    runs = {name: load_run(RUNS / path) for name, path in SYSTEMS.items()}
    transcripts = {name: load_transcript(RUNS / path) for name, path in SYSTEMS.items()}
    cells = matched_cells(*runs.values())
    print(f"== Table 2: per-category exact accuracy, {len(cells)} matched cells ==")
    header = f"{'category':<18}" + "".join(f"{n:>17}" for n in SYSTEMS)
    print(header)
    for category in CATEGORIES:
        row = f"{category:<18}"
        for name in SYSTEMS:
            counts = category_counts(transcripts[name], cells=cells)
            p = counts.get(category)
            if p is None:
                row += f"{'--':>17}"
                continue
            low, high = p.wilson()
            cell = f"{p.rate:.3f} {p.successes}/{p.total}"
            row += cell.rjust(17)
        print(row)
    print()
    print(f"{'overall exact':<18}", end="")
    for name in SYSTEMS:
        o = overall_counts(transcripts[name], cells=cells)
        print(f"{o.rate:.3f} {o.successes}/{o.total}".rjust(17), end="")
    print()
    print(f"{'abstention':<18}", end="")
    for name in SYSTEMS:
        rows = [
            r for r in runs[name]["rows"]
            if r["system"] != "oracle"
            and (r["profile"], r["entities"], r["revisions"], r["seed"]) in cells
        ]
        a = abstention(rows)
        print(f"{a.rate:.3f} {a.successes}/{a.total}".rjust(17), end="")
    print("\n")

    print("== budget sweep (overall exact) ==")
    print(f"{'k':<6}" + "".join(f"{n:>17}" for n in SYSTEMS))
    sweeps = {n: k_sweep(transcripts[n], budgets=(1, 2, 3, 5), cells=cells) for n in SYSTEMS}
    for k in (1, 2, 3, 5):
        print(f"{k:<6}" + "".join(f"{sweeps[n][k]['overall']['rate']:>17.3f}" for n in SYSTEMS))
    print()

    print("== deletion residual by condition ==")
    for label, path in DELETION.items():
        data = json.loads((RUNS / path / "results.json").read_text(encoding="utf-8"))
        parts = []
        for report in data["reports"]:
            detail = ", ".join(
                f"{s['store'].replace('neo4j_', '').replace('mem0_', '')}={s['occurrences']}"
                for s in report["stores"]
                if s["occurrences"]
            )
            parts.append(f"{report['system']}={report['total_residual']} ({detail or 'none'})")
        print(f"  {label:<20} " + "; ".join(parts))
    print()
    print("All figures above are aggregations over sealed transcripts; no API access was used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
