"""A blinded kit for independent human labels (paper audit I25/I26; MODIFY M01/M02).

H15's annotators are models checked on constructed answers; the audit asks for
people. This writes what a person needs and nothing that would bias them:

* ``answers.csv`` -- the 90 native-reader answers about what was known before a
  correction, mixed with 20 constructed answers of known verdict (two per H15
  template) that measure the annotator, all shuffled under opaque ids, with no
  system name and no score;
* ``timing.csv`` -- the 60 LongMemEval pairs: attribute, both values, the asked
  day and both sessions' user turns;
* ``INSTRUCTIONS.md`` -- the rubric, the same decisions H15 asked of its models;
* ``key.json`` -- what each id is. Keep it from the annotator.

``scripts/score_annotation_kit.py`` reads the filled sheets back. The kit carries
LongMemEval text, so it is written outside the repository.

    python scripts/make_annotation_kit.py <output-dir>
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import annotate_known_then  # noqa: E402
import classify_lme_timing as timing  # noqa: E402

from temvera.lme_bitemporal import as_of_day, load  # noqa: E402

SEED = 2027
CONTROLS_PER_TEMPLATE = 2

INSTRUCTIONS = """# Labelling instructions

You will label two sheets. Work alone, and do not look at `key.json`.

## answers.csv

Each row is a question about what a memory held, and an answer. The question
names a person, an attribute, a date V ("as of V") and a knowledge date T
("based only on what was known by T"). It asks for the value that, on the
information available by T, held on V. A correction recorded after T does not
change that answer, even when it says the earlier value was wrong.

Fill in:

- `asserted_value` -- the single value the answer gives as its answer to this
  question. If it gives one value as what was known by T and another as a later
  correction, write the one known by T. If it gives one value and says nothing
  about T, write that value. If it only denies a value, declines, or says it
  does not know, write `NONE`. If it gives two values without saying which one
  answers the question, write `AMBIGUOUS`.
- `span` -- the shortest words of the answer that state that value (empty for
  NONE).
- `notes` -- anything that made the row hard.

Use only the answer's text, never your own knowledge.

## timing.csv

Each row is one user's two conversations: in the EARLIER one they state a value
for an attribute, in the LATER one a different value. Decide what the
conversations themselves say about the asked `day`, which falls between them:

- `HELD` -- they show the earlier value still held on that day (for example the
  change is said to have happened after it);
- `CHANGED` -- they show the change had already happened by that day;
- `UNKNOWN` -- they do not say when the change happened relative to that day.

Do not assume a value lasts until it is next mentioned. A sentence in the LATER
conversation shows only what was true when that conversation took place, unless
it says when the change happened. Fill in `label`, and in `evidence` copy the
sentence(s) you rely on, verbatim.
"""


def _answers(rng: random.Random) -> tuple[list[dict], dict]:
    items = annotate_known_then.items()
    native = [i for i in items if i["set"] == "native"]
    constructed = [i for i in items if i["set"] == "constructed"]
    controls = []
    for template in annotate_known_then.TEMPLATES:
        pool = [i for i in constructed if i["template"] == template]
        controls += rng.sample(pool, CONTROLS_PER_TEMPLATE)
    chosen = native + controls
    rng.shuffle(chosen)
    rows, key = [], {}
    for n, item in enumerate(chosen, 1):
        item_id = f"A{n:03d}"
        rows.append({"item_id": item_id, "question": item["query"], "answer": item["answer"],
                     "asserted_value": "", "span": "", "notes": ""})
        key[item_id] = {k: item.get(k) for k in ("set", "source", "case_id", "template", "query",
                                                 "expected_values", "wrong_values", "should_credit",
                                                 "strict")}
    return rows, key


def _timing(rng: random.Random) -> tuple[list[dict], dict]:
    labels = json.loads(timing.LABELS.read_text(encoding="utf-8"))["labels"]
    pairs = {p.question_id: p for p in load(timing.SOURCE)}
    chosen = []
    for qid, label in sorted(labels.items()):
        pair = pairs[qid]
        day = as_of_day(pair.earlier.recorded_at, pair.later.recorded_at)
        if day is not None:
            chosen.append((qid, label, pair, day))
    rng.shuffle(chosen)
    rows, key = [], {}
    for n, (qid, label, pair, day) in enumerate(chosen, 1):
        item_id = f"T{n:03d}"
        rows.append({"item_id": item_id, "attribute": label["attribute"],
                     "earlier_value": label["earlier_value"], "later_value": label["later_value"],
                     "day": f"{day:%Y-%m-%d}",
                     "earlier_date": f"{pair.earlier.recorded_at:%Y-%m-%d}",
                     "earlier_user_turns": "\n".join(pair.earlier.user_turns),
                     "later_date": f"{pair.later.recorded_at:%Y-%m-%d}",
                     "later_user_turns": "\n".join(pair.later.user_turns),
                     "label": "", "evidence": ""})
        key[item_id] = {"question_id": qid}
    return rows, key


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build(rng_seed: int = SEED) -> tuple[list[dict], list[dict], dict]:
    rng = random.Random(rng_seed)
    answers, answer_key = _answers(rng)
    timing_rows, timing_key = _timing(rng)
    return answers, timing_rows, {"seed": rng_seed, "answers": answer_key, "timing": timing_key}


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    answers, timing_rows, key = build()
    out.mkdir(parents=True)
    _write(out / "answers.csv", answers)
    _write(out / "timing.csv", timing_rows)
    (out / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"answers": len(answers), "controls": sum(v["set"] == "constructed"
                                                                for v in key["answers"].values()),
                      "timing": len(timing_rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
