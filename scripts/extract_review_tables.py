"""Review tables for the two scorings the re-review questions (MODIFY.md, M01/M02).

Writes, from sealed runs only and with no model call:

* ``pre-correction.csv`` -- the 90 answers of the two systems' own readers to
  "what was known before the correction" (H11a, final store), with the original
  value, the later correction, the grid and strict verdicts, and empty columns
  for a structured review (asserted value, verdict, evidence span);
* ``realdata-valid-time.csv`` -- the 60 LongMemEval valid-time questions, with
  both values, the asked day, the two timing labels and their quoted evidence,
  and the readers' answers.

The second table carries LongMemEval text, so it is written to a path the caller
names and is not committed. Raw run outputs are read, never changed.

    python scripts/extract_review_tables.py <output-dir>
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_corrections  # noqa: E402

RUNS = ROOT / "experiments" / "runs"
READERS = ("final-store-corrections-hindsight-reflect-v1",
           "final-store-corrections-cognee-graph-v1")
LME_READERS = {
    "cognee-graph": ("lme-bitemporal-cognee-graph-agreement-v3",
                     "lme-bitemporal-cognee-graph-adjudicated-v1"),
    "hindsight-reflect": ("lme-bitemporal-hindsight-reflect-agreement-v2",
                          "lme-bitemporal-hindsight-reflect-adjudicated-v1"),
}
TIMING = "lme-timing-labels-v1"
REVIEW = ("asserted_value", "verdict", "evidence_span")


def pre_correction_table() -> list[dict]:
    out = []
    for run in READERS:
        for row, fix in analyze_corrections.pre_correction_rows(run):
            states_fix = fix.casefold() in row["answer"].casefold()
            out.append({"run": run, "case_id": row["case_id"], "query": row["query"],
                        "original": "|".join(row["expected_values"]), "correction": fix,
                        "answer": row["answer"], "grid_exact": bool(row["exact"]),
                        "strict": bool(row["exact"]) and not states_fix,
                        **{k: "" for k in REVIEW}})
    return out


def _rows(run: str) -> list[dict]:
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def realdata_table() -> list[dict]:
    timing: dict[str, dict[str, dict]] = {}
    for r in _rows(TIMING):
        timing.setdefault(r["question_id"], {})[r["model"]] = r
    answers: dict[str, dict[str, dict]] = {}
    for name, runs in LME_READERS.items():
        for run in runs:
            for r in _rows(run):
                if r["category"] == "valid_time":
                    answers.setdefault(r["question_id"], {})[name] = r
    out = []
    for qid in sorted(answers):
        first = next(iter(answers[qid].values()))
        labels = timing.get(qid, {})
        entry = {"question_id": qid, "query": first["query"],
                 "earlier_value": "|".join(first["expected_values"]),
                 "later_value": "|".join(first["stale_values"])}
        for model in ("gpt-4o", "gpt-4o-mini"):
            label = labels.get(model, {})
            entry[f"timing_{model}"] = label.get("answer", "")
            entry[f"timing_evidence_{model}"] = label.get("evidence", "")
        for name in LME_READERS:
            r = answers[qid].get(name, {})
            entry[f"answer_{name}"] = r.get("answer", "")
            entry[f"exact_{name}"] = r.get("exact", "")
        out.append({**entry, **{k: "" for k in REVIEW}})
    return out


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    pre, real = pre_correction_table(), realdata_table()
    out.mkdir(parents=True)
    _write(out / "pre-correction.csv", pre)
    _write(out / "realdata-valid-time.csv", real)
    print(json.dumps({"pre_correction": len(pre),
                      "pre_correction_strict": sum(r["strict"] for r in pre),
                      "realdata_valid_time": len(real)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
