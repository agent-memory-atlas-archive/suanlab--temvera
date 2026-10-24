"""The human annotation kit round-trips: filled with a known annotator's
answers, the scorer reproduces that annotator's sealed H15 results."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_h15  # noqa: E402
import make_annotation_kit  # noqa: E402
import score_annotation_kit  # noqa: E402


def _fill(path: Path, values: dict[str, dict[str, str]]) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row.update(values.get(row["item_id"], {}))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_kit_is_blind_and_scores_a_known_annotator(tmp_path: Path) -> None:
    kit = tmp_path / "kit"
    assert make_annotation_kit.main(str(kit)) == 0
    header = (kit / "answers.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "item_id,question,answer,asserted_value,span,notes"
    key = json.loads((kit / "key.json").read_text(encoding="utf-8"))
    gpt4o = {(r["set"], r["source"], r.get("template", ""), r["case_id"], r["query"]): r
             for r in analyze_h15.rows("h15-annotate-gpt4o-v1")}
    fills = {}
    for item_id, k in key["answers"].items():
        row = gpt4o[(k["set"], k["source"], k.get("template") or "", k["case_id"], k["query"])]
        fills[item_id] = {"asserted_value": row["asserted_value"] or "NONE"}
    _fill(kit / "answers.csv", fills)
    labels = {r["question_id"]: r["answer"] for r in analyze_h15.rows("h15-lme-timing-quotes-v1")
              if r["model"] == "gpt-4o-2024-08-06"}
    _fill(kit / "timing.csv", {i: {"label": labels[k["question_id"]]} for i, k in key["timing"].items()})
    report = score_annotation_kit.score(kit)
    assert report["controls_right"] == report["controls"] == 20
    assert report["native_n"] == 90
    assert report["timing_agreement_with_models"]["gpt-4o-2024-08-06"] == 60
    assert report["timing"]["HELD"] + report["timing"]["CHANGED"] == 13
