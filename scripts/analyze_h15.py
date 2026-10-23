"""H15: the annotators' validity, their agreement, and the counts they give.

Reads the two sealed annotation runs (one per model) and the sealed timing
relabelling, prints per-template accuracy on the constructed answers, the
agreement on the sealed answers, consensus counts per source, the confusion of
the strict count against the consensus, and each H15 prediction.

    python scripts/analyze_h15.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
ANNOTATORS = ("h15-annotate-gpt4o-v1", "h15-annotate-gpt54-v1")
TIMING = "h15-lme-timing-quotes-v1"
NATIVE = {"cognee": "final-store-corrections-cognee-graph-v1",
          "hindsight": "final-store-corrections-hindsight-reflect-v1"}


def rows(run: str) -> list[dict]:
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _key(row: dict) -> tuple:
    return (row["set"], row["source"], row.get("template", ""), row["case_id"])


def paired() -> list[tuple[dict, dict]]:
    """Rows of the two annotators, matched on the item they read."""
    a, b = (rows(run) for run in ANNOTATORS)
    index = {_key(r): r for r in b}
    if len(index) != len(b) or {_key(r) for r in a} != set(index):
        raise ValueError("the two annotation runs did not read the same items")
    return [(r, index[_key(r)]) for r in a]


def template_accuracy(run: str) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for r in rows(run):
        if r["set"] == "constructed":
            entry = out.setdefault(r["template"], [0, 0])
            entry[0] += r["credited"] == r["should_credit"]
            entry[1] += 1
    return {k: (v[0], v[1]) for k, v in sorted(out.items())}


def agreement(set_name: str) -> tuple[int, int]:
    pairs = [(a, b) for a, b in paired() if a["set"] == set_name]
    return sum(a["credited"] == b["credited"] for a, b in pairs), len(pairs)


def consensus(source: str) -> dict[str, int]:
    pairs = [(a, b) for a, b in paired() if a["set"] != "constructed" and a["source"] == source]
    return {"n": len(pairs), "both": sum(a["credited"] and b["credited"] for a, b in pairs),
            "either": sum(a["credited"] or b["credited"] for a, b in pairs),
            "strict": sum(bool(a["strict"]) for a, _ in pairs),
            "strict_not_credited_by_either": sum(a["strict"] and not (a["credited"] or b["credited"])
                                                 for a, b in pairs),
            "not_strict_credited_by_both": sum(not a["strict"] and a["credited"] and b["credited"]
                                               for a, b in pairs)}


def timing() -> dict:
    return json.loads((RUNS / TIMING / "results.json").read_text(encoding="utf-8"))


def checks() -> dict[str, bool]:
    out = {}
    valid = []
    for run in ANNOTATORS:
        acc = template_accuracy(run)
        right, n = sum(v[0] for v in acc.values()), sum(v[1] for v in acc.values())
        valid.append(right >= 0.95 * n and all(r >= 0.90 * m for r, m in acc.values()))
    out["H15a"] = all(valid)
    native_agree, native_n = agreement("native")
    common_agree, common_n = agreement("common")
    out["H15b"] = native_agree >= 0.9 * native_n and common_agree >= 0.9 * common_n
    cognee, hindsight = consensus(NATIVE["cognee"]), consensus(NATIVE["hindsight"])
    out["H15c"] = cognee["both"] >= 35 and hindsight["both"] >= 20
    common = [consensus(s) for s in sorted({a["source"] for a, _ in paired() if a["set"] == "common"})]
    top = max(c["both"] for c in common)
    out["H15d"] = top <= 12 and cognee["both"] > top and hindsight["both"] > top
    out["H15e"] = sum(c["strict_not_credited_by_either"] for c in (cognee, hindsight)) <= 3 and \
        sum(c["not_strict_credited_by_both"] for c in (cognee, hindsight)) <= 12
    summary = timing()["summary"]
    out["H15f"] = summary["identified"] < 15 and summary["identified_held"] < 10
    return out


def main() -> int:
    for run in ANNOTATORS:
        print(run, template_accuracy(run))
    print("agreement native", agreement("native"), "common", agreement("common"))
    for source in sorted({a["source"] for a, _ in paired() if a["set"] != "constructed"}):
        print(f"{source:48s}", consensus(source))
    print("timing", timing()["summary"])
    print(checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
