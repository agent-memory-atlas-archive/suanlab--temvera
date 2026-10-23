"""H13-E2: is the valid-time gold of each LongMemEval pair identifiable?

The real-data valid-time question asks for the earlier value on a day between
the two sessions. That gold assumes the earlier value still held on that day;
LongMemEval does not say when a change took effect. Two models (independently,
quoting the words they rely on) classify each pair: HELD if the conversations
show the earlier value still held on the asked day, CHANGED if they show the
change had already happened, UNKNOWN if they do not say. A gold counts as
identifiable only if both say HELD. This is AI labelling, reported as such.

    python scripts/classify_lme_timing.py experiments/runs/lme-timing-labels-v1
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402
from temvera.lme_bitemporal import as_of_day, load  # noqa: E402

SOURCE = ROOT / "data" / "raw" / "longmemeval_oracle.json"
LABELS = ROOT / "data" / "lme-bitemporal-labels.json"
MODELS = ("gpt-4o", "gpt-4o-mini")
CHOICES = ("HELD", "CHANGED", "UNKNOWN")

PROMPT = """A user stated a fact in an EARLIER conversation and a different value
for the same thing in a LATER conversation. You are given both conversations'
user turns with their dates, the attribute, both values, and a DAY between the
two conversations.

Decide what the conversations themselves say about the DAY:
- "HELD": they show the earlier value still held on the DAY (for example the
  change is said to have happened after it);
- "CHANGED": they show the change had already happened by the DAY;
- "UNKNOWN": they do not say when the change happened relative to the DAY.

Do not assume a value persists until the next conversation; use only what the
text states. Quote the words you rely on.

Respond with JSON only: {"answer": "HELD" | "CHANGED" | "UNKNOWN", "evidence": "..."}"""


def _messages(pair, label: dict, day) -> list[dict]:
    earlier = "\n".join(f"- {t}" for t in pair.earlier.user_turns)
    later = "\n".join(f"- {t}" for t in pair.later.user_turns)
    user = (f"ATTRIBUTE: {label['attribute']}\nEARLIER VALUE: {label['earlier_value']}\n"
            f"LATER VALUE: {label['later_value']}\nDAY: {day:%Y-%m-%d}\n\n"
            f"EARLIER CONVERSATION ({pair.earlier.recorded_at:%Y-%m-%d}), user turns:\n{earlier}\n\n"
            f"LATER CONVERSATION ({pair.later.recorded_at:%Y-%m-%d}), user turns:\n{later}")
    return [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["labels"]
    pairs = {p.question_id: p for p in load(SOURCE)}
    work = []
    for qid, label in sorted(labels.items()):
        pair = pairs[qid]
        day = as_of_day(pair.earlier.recorded_at, pair.later.recorded_at)
        if day is None:
            continue
        for model in MODELS:
            work.append((qid, model, _messages(pair, label, day), f"{day:%Y-%m-%d}"))
    client = llm_rescore._client("openai")

    def one(item):
        qid, model, messages, day = item
        for attempt in range(6):
            try:
                response = client.chat.completions.create(
                    model=model, messages=messages, temperature=0, seed=7,
                    response_format={"type": "json_object"}, max_tokens=300)
                text = response.choices[0].message.content or "{}"
                break
            except Exception as error:  # noqa: BLE001
                llm_rescore.check_fatal(str(error))
                if attempt == 5:
                    raise
                import time

                time.sleep(2 ** attempt)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        answer = str(parsed.get("answer", "")).upper()
        return {"question_id": qid, "model": model, "day": day,
                "answer": answer if answer in CHOICES else "UNKNOWN",
                "evidence": str(parsed.get("evidence", ""))[:500], "raw": text[:800]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, work))
    by_q: dict[str, dict] = {}
    for row in rows:
        by_q.setdefault(row["question_id"], {})[row["model"]] = row["answer"]
    summary = {
        "pairs": len(by_q),
        "both_held": sum(all(v == "HELD" for v in m.values()) for m in by_q.values()),
        "any_changed": sum(any(v == "CHANGED" for v in m.values()) for m in by_q.values()),
        "agree": sum(len(set(m.values())) == 1 for m in by_q.values()),
        "by_model": {model: {c: sum(r["answer"] == c for r in rows if r["model"] == model)
                             for c in CHOICES} for model in MODELS},
    }
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary, "labels": by_q},
                                                 indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-lme-timing-labels-v1", "models": list(MODELS),
                          "prompt": PROMPT, "temperature": 0, "seed": 7},
             command=f"python scripts/classify_lme_timing.py {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
