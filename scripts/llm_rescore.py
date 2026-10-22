"""Re-read sealed transcripts with one fixed LLM, into a new sealed run (H9).

Two modes, both over the answers a sealed run already recorded, so no memory
system is re-run:

* ``reader`` -- a common reader. For configurations read at the retrieval layer
  the recorded answer is the system's top-k memories. One fixed model, prompt
  and temperature turn them into a value, which the grid's own deterministic
  scorer then scores. Every store is read the same way, so differences are the
  stores', not their readers'.
* ``judge`` -- an asserted-value judge. For configurations whose own LLM reader
  wrote the answer, the exact scorer fails any answer that also names the
  superseded value, even when it says which value held when. The judge reports
  the one value the answer asserts held at the asked date (or NONE or
  AMBIGUOUS), and that value is scored instead.

    python scripts/llm_rescore.py reader openai:gpt-4o-mini external-mem0-grid-v2 common-reader-mem0-v1
    python scripts/llm_rescore.py judge openai:gpt-4o external-cognee-grid-v1 judge-gpt4o-cognee-grid-v1

Prompts are fixed in this file and recorded, with their hash, in the sealed
config. Temperature is 0 and requests carry a seed; LLM output is still not
bit-reproducible, which is why the result is sealed rather than recomputed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from temvera.experiment import seal_run
from temvera.worker_errors import check_fatal, redact, summarize

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"

READER_SYSTEM = (
    "You answer a question about a person using only the memory records given. "
    "Reply with the value only, in a few words, or UNKNOWN if the records do not "
    "determine it."
)
READER_USER = "Memory records:\n{records}\n\nQuestion: {query}\nValue:"

JUDGE_SYSTEM = (
    "You grade an answer to a question that asks for the value of a fact at a "
    "given date. Report the single value the answer asserts held at the date the "
    "question asks about. If the answer asserts no value for that date, report "
    "NONE. If it gives more than one value without making clear which one held at "
    "that date, report AMBIGUOUS. Do not use your own knowledge."
)
JUDGE_USER = (
    'Question: {query}\nAnswer: {answer}\n\nReply with JSON only: {{"value": "..."}}'
)

PROMPTS = {
    "reader": {"system": READER_SYSTEM, "user": READER_USER},
    "judge": {"system": JUDGE_SYSTEM, "user": JUDGE_USER},
}
SPECIAL = {"NONE", "AMBIGUOUS", "UNKNOWN", ""}


def prompt_hash(mode: str) -> str:
    text = json.dumps(PROMPTS[mode], sort_keys=True).encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def rows(run: str) -> list[dict]:
    lines = (RUNS / run / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if r.get("system") != "oracle"]


def exact(text: str, expected: list[str], stale: list[str]) -> bool:
    """The grid's scorer (external_harness.score_answer), on a reader's text."""
    folded = text.casefold()
    if any(value.casefold() in folded for value in stale):
        return False
    return all(value.casefold() in folded for value in expected)


def judged(value: str, expected: list[str], stale: list[str]) -> bool:
    """A judged value is correct when it names the expected value and no stale
    one; for a question whose answer is an abstention, when it asserts none."""
    stripped = value.strip()
    if not expected:
        return stripped.upper() in SPECIAL
    if stripped.upper() in SPECIAL:
        return False
    return exact(stripped, expected, stale)


def _client(provider: str):
    if provider != "openai":
        raise SystemExit(f"unsupported provider: {provider}")
    from openai import OpenAI

    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)


def _complete(client, model: str, mode: str, row: dict) -> str:
    if mode == "reader":
        user = READER_USER.format(records=row["answer"] or "(no records)", query=row["query"])
    else:
        user = JUDGE_USER.format(query=row["query"], answer=row["answer"] or "(empty)")
    messages = [{"role": "system", "content": PROMPTS[mode]["system"]},
                {"role": "user", "content": user}]
    for attempt in range(6):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0, seed=7, max_tokens=64,
                **({"response_format": {"type": "json_object"}} if mode == "judge" else {}),
            )
            return response.choices[0].message.content or ""
        except Exception as error:  # noqa: BLE001 - classified below
            check_fatal(str(error))
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _value(mode: str, text: str) -> str:
    if mode == "reader":
        return text.strip()
    try:
        return str(json.loads(text).get("value", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        match = re.search(r'"value"\s*:\s*"([^"]*)"', text)
        return match.group(1).strip() if match else ""


def main(mode: str, backbone: str, source: str, output: str) -> int:
    if mode not in PROMPTS:
        raise SystemExit("mode must be reader or judge")
    out = RUNS / output
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    provider, model = backbone.split(":", 1)
    client = _client(provider)
    source_rows = rows(source)
    errors: list[str] = []

    def one(row: dict) -> dict:
        try:
            text = _complete(client, model, mode, row)
        except Exception as error:  # noqa: BLE001 - recorded, never scored as correct
            errors.append(redact(str(error)))
            text = ""
        value = _value(mode, text)
        expected, stale = row["expected_values"], row["stale_values"]
        score = exact(value, expected, stale) if mode == "reader" else judged(
            value, expected, stale)
        keep = {k: row[k] for k in ("case_id", "category", "query", "expected_values",
                                    "stale_values", "profile", "entities", "revisions",
                                    "seed", "question_id") if k in row}
        return {**keep, "source_answer": row["answer"], "source_exact": row["exact"],
                "output": text, "value": value, "exact": score}

    with ThreadPoolExecutor(max_workers=16) as pool:
        scored = list(pool.map(one, source_rows))
    if errors:
        # A failed call scores as wrong, not as an abstention; still, a run with
        # failures is not one to cite, so stop rather than seal it.
        raise SystemExit(f"{len(errors)} calls failed: {summarize(errors)}")

    by_category: dict[str, list[int]] = {}
    for row in scored:
        tally = by_category.setdefault(row["category"], [0, 0])
        tally[0] += row["exact"]
        tally[1] += 1
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in scored:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({
        "by_category": {k: {"exact": v[0], "n": v[1]} for k, v in sorted(by_category.items())},
        "cases": len(scored),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={
        "mode": mode, "backbone": backbone, "source_run": source, "temperature": 0,
        "seed": 7, "max_tokens": 64, "prompts": PROMPTS[mode],
        "prompt_sha256": prompt_hash(mode),
    }, command=f"python scripts/llm_rescore.py {mode} {backbone} {source} {output}")
    print(json.dumps(json.loads((out / "results.json").read_text()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
