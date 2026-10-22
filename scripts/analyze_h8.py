"""H8: replicates and a gpt-4o backbone for LangMem, Cognee and Hindsight.

Recomputes, from sealed runs, every quantity docs/preregistration-h8.md predicts:
each replicate's overall and valid-time exact counts on the four seed-7 cells
against the cited run on the same cells, and the gpt-4o grid's valid-time and
transaction-scoped accuracy with the consolidation-ceiling check for LangMem.

    python scripts/analyze_h8.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_filtering_laws as laws  # noqa: E402

CITED = {
    "langmem": "external-langmem-v1",
    "cognee-chunks": "external-cognee-chunks-grid-v3",
    "cognee-graph": "external-cognee-grid-v1",
    "hindsight-recall": "external-hindsight-recall-v1",
    "hindsight-reflect": "external-hindsight-reflect-v1",
}
BACKBONE = {
    "langmem": ("external-langmem-v1", "external-langmem-gpt4o-v1"),
    "cognee-graph": ("external-cognee-grid-v1", "external-cognee-grid-gpt4o-v1"),
    "hindsight-recall": ("external-hindsight-recall-v1", "external-hindsight-recall-gpt4o-v1"),
    "hindsight-reflect": ("external-hindsight-reflect-v1", "external-hindsight-reflect-gpt4o-v1"),
}


def _rows(run: str, seed: int | None = None) -> list[dict]:
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines)
            if r.get("system") != "oracle" and (seed is None or r["seed"] == seed)]


def counts(run: str, seed: int | None = None) -> dict[str, int]:
    rows = _rows(run, seed)
    out = {"n": len(rows), "exact": sum(bool(r["exact"]) for r in rows)}
    for category in ("valid_time", "transaction_as_of"):
        mine = [r for r in rows if r["category"] == category]
        out[f"{category}_n"] = len(mine)
        out[category] = sum(bool(r["exact"]) for r in mine)
    return out


def replicates() -> dict[str, dict]:
    out = {}
    for name, cited in CITED.items():
        base = counts(cited, seed=7)
        runs = [f"variance-{name}-r{r}-v1" for r in (1, 2, 3)]
        reps = [counts(run) for run in runs if (RUNS / run).exists()]
        out[name] = {"cited": base, "replicates": reps,
                     "max_overall_move": max((abs(r["exact"] - base["exact"]) for r in reps),
                                             default=None)}
    return out


def backbone() -> dict[str, dict]:
    out = {}
    for name, (mini, big) in BACKBONE.items():
        if not (RUNS / big).exists():
            continue
        entry = {"gpt-4o-mini": counts(mini), "gpt-4o": counts(big)}
        if name == "langmem":
            answerable, total, inside, beyond, _ = laws.ceiling(big)
            entry["ceiling"] = {"answerable": answerable, "questions": total,
                                "inside": inside, "beyond": beyond}
        out[name] = entry
    return out


def main() -> int:
    print(json.dumps({"replicates": replicates(), "backbone": backbone()}, indent=2,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
