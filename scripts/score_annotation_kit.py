"""Score the filled annotation kit of ``make_annotation_kit.py`` against its key.

Reports the annotator's accuracy on the constructed control answers, then the
human count of credited native answers per reader beside the strict count and
the H15 model consensus, the agreement with that consensus (and Cohen's kappa),
and the timing labels: how many pairs a person finds identifiable, and how
often the person agrees with each model of H15f.

    python scripts/score_annotation_kit.py <kit-dir> [<second-annotator-kit-dir>]

With two kits (same key), it also reports the agreement between the people.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_h15  # noqa: E402
import annotate_known_then  # noqa: E402

RUNS = ROOT / "experiments" / "runs"


def _rows(path: Path) -> dict[str, dict]:
    # utf-8-sig: sheets saved from Excel start with a byte-order mark.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {r["item_id"]: r for r in csv.DictReader(handle)}


def credited(row: dict, key: dict) -> bool:
    return annotate_known_then.credited(row["asserted_value"], key["expected_values"],
                                        key["wrong_values"])


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def model_consensus() -> dict[tuple, bool]:
    return {(a["source"], a["case_id"], a["query"]): a["credited"] and b["credited"]
            for a, b in analyze_h15.paired() if a["set"] == "native"}


def score(kit: Path) -> dict:
    key = json.loads((kit / "key.json").read_text(encoding="utf-8"))
    answers = _rows(kit / "answers.csv")
    unfilled = [i for i, r in answers.items() if not r["asserted_value"].strip()]
    if unfilled:
        raise SystemExit(f"{len(unfilled)} answer rows are not filled in, e.g. {unfilled[:3]}")
    controls = [(credited(answers[i], k), k["should_credit"])
                for i, k in key["answers"].items() if k["set"] == "constructed"]
    consensus = model_consensus()
    by_reader: dict[str, dict] = {}
    human, models = [], []
    for item_id, k in key["answers"].items():
        if k["set"] != "native":
            continue
        mine = credited(answers[item_id], k)
        theirs = consensus[(k["source"], k["case_id"], k["query"])]
        entry = by_reader.setdefault(k["source"], {"n": 0, "human": 0, "models": 0, "strict": 0})
        entry["n"] += 1
        entry["human"] += mine
        entry["models"] += theirs
        entry["strict"] += bool(k["strict"])
        human.append(mine)
        models.append(theirs)
    timing_rows = _rows(kit / "timing.csv")
    labels = {r["item_id"]: r["label"].strip().upper() for r in timing_rows.values()}
    model_rows = analyze_h15.rows("h15-lme-timing-quotes-v1")
    by_model: dict[str, dict] = {}
    for r in model_rows:
        by_model.setdefault(r["model"], {})[r["question_id"]] = r["answer"]
    agree = {m: sum(labels[i] == v.get(key["timing"][i]["question_id"]) for i in labels)
             for m, v in by_model.items()}
    return {
        "controls_right": sum(c == s for c, s in controls), "controls": len(controls),
        "native": by_reader,
        "agreement_with_model_consensus": sum(h == m for h, m in zip(human, models)),
        "kappa_with_model_consensus": round(kappa(human, models), 3), "native_n": len(human),
        "timing": {c: sum(v == c for v in labels.values()) for c in ("HELD", "CHANGED", "UNKNOWN")},
        "timing_unlabelled": sum(v not in ("HELD", "CHANGED", "UNKNOWN") for v in labels.values()),
        "timing_agreement_with_models": agree,
        "_credited": dict(zip([i for i, k in key["answers"].items() if k["set"] == "native"], human)),
        "_labels": labels,
    }


def main(argv: list[str]) -> int:
    first = score(Path(argv[0]))
    report = {k: v for k, v in first.items() if not k.startswith("_")}
    if len(argv) > 1:
        second = score(Path(argv[1]))
        ids = sorted(first["_credited"])
        a, b = [first["_credited"][i] for i in ids], [second["_credited"][i] for i in ids]
        report["between_annotators"] = {
            "answers_agree": sum(x == y for x, y in zip(a, b)), "answers_n": len(ids),
            "answers_kappa": round(kappa(a, b), 3),
            "timing_agree": sum(first["_labels"][i] == second["_labels"][i] for i in first["_labels"]),
            "timing_identified_by_both": sum(first["_labels"][i] == second["_labels"][i] != "UNKNOWN"
                                             for i in first["_labels"]),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
