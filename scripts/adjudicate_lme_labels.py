"""Accept supersession labels two models agree on; route the rest to a person.

A label is accepted automatically only when both extractions pass the verbatim
check and agree exactly after whitespace and case normalisation. Everything
else -- a disagreement, a span-boundary difference, a rejected extraction, or a
"no prior value" answer -- goes to the author, because each of those is a
judgement about ground truth, and the systems being scored are LLM-backed too.

    python scripts/adjudicate_lme_labels.py gpt-4o-mini gpt-4o
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from temvera.lme_bitemporal import load

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "raw" / "longmemeval_oracle.json"
LABELS = ROOT / "data" / "lme-bitemporal-labels.json"
REVIEW = ROOT / "data" / "lme-disagreements.json"


def _norm(value: object) -> str:
    return " ".join(str(value).lower().split()) if value is not None else ""


def main(model_a: str, model_b: str) -> int:
    a = json.loads((ROOT / "data" / f"lme-proposals-v2-{model_a}.json").read_text())
    b = json.loads((ROOT / "data" / f"lme-proposals-v2-{model_b}.json").read_text())
    by_a = {item["question_id"]: item for item in a["items"]}
    by_b = {item["question_id"]: item for item in b["items"]}
    pairs = {pair.question_id: pair for pair in load(SOURCE)}

    record = json.loads(LABELS.read_text(encoding="utf-8"))
    labels: dict = record.setdefault("labels", {})
    review = []
    tally = {"accepted": 0, "already_labelled": 0, "to_review": 0}
    for qid, pair in pairs.items():
        if qid in labels:
            tally["already_labelled"] += 1
            continue
        x, y = by_a[qid], by_b[qid]
        both_valid = not x["rejected_because"] and not y["rejected_because"]
        agree = (
            _norm(x["earlier_value"]) == _norm(y["earlier_value"])
            and _norm(x["later_value"]) == _norm(y["later_value"])
        )
        if both_valid and agree and x["question_asks_for"] == y["question_asks_for"]:
            gold = _norm(pair.new_value)
            labels[qid] = {
                "earlier_value": x["earlier_value"],
                "later_value": x["later_value"],
                "question_asks_for": x["question_asks_for"],
                "gold_mentions": [
                    side for side, value in (("earlier", x["earlier_value"]),
                                             ("later", x["later_value"]))
                    if _norm(value) in gold
                ],
                "method": f"agreement:{model_a}+{model_b}",
            }
            tally["accepted"] += 1
            continue
        kind = (
            "values agree, direction differs" if both_valid and agree
            else "disagree" if both_valid
            else "extraction rejected"
        )
        fields = ("attribute", "earlier_value", "later_value",
                  "question_asks_for", "rejected_because")
        review.append({
            "question_id": qid,
            "kind": kind,
            "question": pair.question,
            "benchmark_answer": pair.new_value,
            model_a: {k: x[k] for k in fields},
            model_b: {k: y[k] for k in fields},
            # the author fills these, or sets "exclude": true with a reason
            "decision": {"earlier_value": "", "later_value": "",
                         "question_asks_for": "", "exclude": False, "reason": ""},
        })
        tally["to_review"] += 1

    record["labelling"] = {
        "models": [model_a, model_b],
        "prompt_sha256": a["prompt_sha256"],
        "rule": ("accept iff both pass the per-session verbatim check and agree, after "
                 "normalisation, on both values and on the question's direction"),
    }
    LABELS.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    REVIEW.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(tally, indent=2))
    kinds: dict[str, int] = {}
    for item in review:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    print("to review, by kind:", kinds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
