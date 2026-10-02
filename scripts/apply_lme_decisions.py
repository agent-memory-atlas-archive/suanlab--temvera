"""Record the author's decisions on the LongMemEval labels the models disputed.

Reads a decisions file mapping question ids to a choice -- "A" (gpt-4o-mini),
"B" (gpt-4o), "S" (the sheet's suggestion), "X" (exclude, with a reason) or
explicit values -- and writes accepted labels with method "adjudicated:author".
Exclusions are recorded too, with their reason, so the benchmark's composition
is auditable rather than silently shrunk.

    python scripts/apply_lme_decisions.py data/lme-decisions.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "lme-bitemporal-labels.json"
REVIEW = ROOT / "data" / "lme-disagreements.json"
A, B = "gpt-4o-mini", "gpt-4o"


def main(decisions_path: str) -> int:
    decisions = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
    review = {item["question_id"]: item for item in json.loads(REVIEW.read_text())}
    record = json.loads(LABELS.read_text(encoding="utf-8"))
    labels = record.setdefault("labels", {})
    excluded = record.setdefault("excluded", {})
    for qid, decision in decisions.items():
        if qid not in review:
            print(f"FAIL: {qid} is not an item awaiting review")
            return 1
        item = review[qid]
        choice = decision["choice"]
        if choice == "X":
            if not decision.get("reason"):
                print(f"FAIL: exclusion of {qid} needs a reason")
                return 1
            excluded[qid] = {"reason": decision["reason"], "method": "adjudicated:author"}
            labels.pop(qid, None)
            continue
        if choice in ("A", "B"):
            source = item[A if choice == "A" else B]
            values = {k: source[k] for k in ("earlier_value", "later_value", "question_asks_for")}
            values["attribute"] = decision.get("attribute") or source["attribute"]
        else:  # "S" or explicit: the values must be spelled out in the decision
            values = {k: decision[k] for k in ("earlier_value", "later_value", "question_asks_for")}
            values["attribute"] = decision.get("attribute") or item[B]["attribute"]
        labels[qid] = {**values, "method": "adjudicated:author", "choice": choice}
        excluded.pop(qid, None)
    LABELS.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"labels: {len(labels)} | excluded: {len(excluded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
