"""H15f: can the real-data valid-time gold be identified from the conversations?

The first labelling (``classify_lme_timing.py``, H13-E2) let each model describe
its evidence in prose, so whether that evidence exists could not be checked, and
its two models agreed on 7 of 60 pairs. This asks the same question with the
same decision rules, but the model must copy the user sentences it relies on,
verbatim, into a list, and must say which conversation each comes from. A label
counts only if every quoted sentence is found in that conversation's user turns
-- checked here, not by the model. Two models of different generations label
independently; a pair's gold is identified only where both agree and both pass
the check.

    python scripts/classify_lme_timing_quotes.py experiments/runs/h15-lme-timing-quotes-v1
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import classify_lme_timing as v1  # noqa: E402
import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402
from temvera.lme_bitemporal import as_of_day, load  # noqa: E402

MODELS = ("gpt-4o-2024-08-06", "gpt-5.4-2026-03-05")
PROMPT = v1.PROMPT.replace(
    'Respond with JSON only: {"answer": "HELD" | "CHANGED" | "UNKNOWN", "evidence": "..."}',
    "Copy every user sentence you rely on, verbatim, and say which conversation it is "
    "from. A sentence from the LATER conversation shows only what was true when that "
    "conversation took place, unless it states when the change happened.\n\n"
    'Respond with JSON only: {"answer": "HELD" | "CHANGED" | "UNKNOWN", '
    '"quotes": [{"conversation": "EARLIER" | "LATER", "text": "..."}], "reason": "..."}')
assert PROMPT != v1.PROMPT


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip().strip(".")


def verified(quotes: list, pair) -> bool:
    """Every quote is found, whitespace- and case-folded, in the user turns of
    the conversation it names."""
    turns = {"EARLIER": _norm(" ".join(pair.earlier.user_turns)),
             "LATER": _norm(" ".join(pair.later.user_turns))}
    for quote in quotes:
        if not isinstance(quote, dict):
            return False
        text, where = _norm(str(quote.get("text", ""))), str(quote.get("conversation", "")).upper()
        if not text or where not in turns or text not in turns[where]:
            return False
    return True


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    labels = json.loads(v1.LABELS.read_text(encoding="utf-8"))["labels"]
    pairs = {p.question_id: p for p in load(v1.SOURCE)}
    work = []
    for qid, label in sorted(labels.items()):
        pair = pairs[qid]
        day = as_of_day(pair.earlier.recorded_at, pair.later.recorded_at)
        if day is None:
            continue
        messages = v1._messages(pair, label, day)
        messages[0]["content"] = PROMPT
        for model in MODELS:
            work.append((qid, model, messages, f"{day:%Y-%m-%d}"))
    client = llm_rescore._client("openai")

    def one(item):
        qid, model, messages, day = item
        extra = ({"max_completion_tokens": 800, "reasoning_effort": "none"} if model.startswith("gpt-5")
                 else {"max_tokens": 800})
        for attempt in range(6):
            try:
                response = client.chat.completions.create(
                    model=model, messages=messages, temperature=0, seed=7,
                    response_format={"type": "json_object"}, **extra)
                text = response.choices[0].message.content or "{}"
                break
            except Exception as error:  # noqa: BLE001
                llm_rescore.check_fatal(str(error))
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        answer = str(parsed.get("answer", "")).upper()
        answer = answer if answer in v1.CHOICES else "UNKNOWN"
        quotes = parsed.get("quotes", [])
        quotes = quotes if isinstance(quotes, list) else []
        return {"question_id": qid, "model": model, "day": day, "answer": answer,
                "quotes": quotes, "quotes_verified": verified(quotes, pairs[qid]),
                "reason": str(parsed.get("reason", ""))[:600]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, work))
    by_q: dict[str, dict] = {}
    for row in rows:
        by_q.setdefault(row["question_id"], {})[row["model"]] = row
    identified = {qid: m[MODELS[0]]["answer"] for qid, m in by_q.items()
                  if m[MODELS[0]]["answer"] == m[MODELS[1]]["answer"] != "UNKNOWN"
                  and all(r["quotes_verified"] and r["quotes"] for r in m.values())}
    summary = {
        "pairs": len(by_q),
        "by_model": {model: {c: sum(r["answer"] == c for r in rows if r["model"] == model)
                             for c in v1.CHOICES} for model in MODELS},
        "verified_quotes": {model: sum(r["quotes_verified"] and bool(r["quotes"])
                                       for r in rows if r["model"] == model) for model in MODELS},
        "agree": sum(m[MODELS[0]]["answer"] == m[MODELS[1]]["answer"] for m in by_q.values()),
        "identified": len(identified),
        "identified_held": sum(v == "HELD" for v in identified.values()),
        "identified_changed": sum(v == "CHANGED" for v in identified.values()),
    }
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary, "identified": identified},
                                                 indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-h15-lme-timing-quotes-v1", "models": list(MODELS),
                          "prompt": PROMPT, "temperature": 0, "seed": 7},
             command=f"python scripts/classify_lme_timing_quotes.py {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
