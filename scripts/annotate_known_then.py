"""H15: what do answers about "what was known before a correction" assert?

The strict scorer of H11a is a token count: it fails a right answer that also
names the later correction, and passes ``It was not X.``. This replaces it with
a structured reading by a model, checked first on answers whose verdict is fixed
by construction and only then applied to the sealed answers.

One model per run reads each answer, blind to the system that wrote it and to
every earlier score, and reports the value the answer gives as its answer, whether
it mentions a value learned after the knowledge date, and the words it relies
on. The verdict is computed from that report, not asked for: credited when the
asserted value names the original value and neither the correction nor any
other value known by then. The quoted words are checked against the answer.

Rows, in one run and under one prompt, with nothing tuned in between:

* ``constructed`` -- ten templates over each of the 45 questions, whose verdict
  is known (four right, six wrong, including the negation that passes the
  strict count);
* ``native`` -- the 90 answers of Cognee's and Hindsight's own readers;
* ``common`` -- the 225 answers of the common reader over the five retrieval
  layers' top five.

    python scripts/annotate_known_then.py openai:gpt-4o-2024-08-06 experiments/runs/h15-annotate-gpt4o-v1
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_corrections  # noqa: E402
import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402
from temvera.worker_errors import redact, summarize  # noqa: E402

RUNS = ROOT / "experiments" / "runs"
NATIVE = ("final-store-corrections-cognee-graph-v1", "final-store-corrections-hindsight-reflect-v1")
COMMON = {  # common-reader run -> the final-store run it read
    "h13-reader-final-store-mem0": "final-store-corrections-mem0-v1",
    "h13-reader-final-store-langmem": "final-store-corrections-langmem-v1",
    "h13-reader-final-store-graphiti": "final-store-corrections-graphiti-v1",
    "h13-reader-final-store-cognee-chunks": "final-store-corrections-cognee-chunks-v1",
    "h13-reader-final-store-hindsight-recall": "final-store-corrections-hindsight-recall-v1",
}
TEMPLATE_SOURCE = NATIVE[0]

# template -> (text, should be credited). {x}: the value known by {t};
# {y}: the correction recorded after {t}; {v}: the asked valid date.
TEMPLATES = {
    "value_only": ("{x}.", True),
    "history_stated": ("Based on what was known by {t}, it was {x}; a later correction says {y}.", True),
    "later_note": ("As of {v} it was {x}. A record added after {t} corrected this to {y}.", True),
    "negation_right": ("{x}, not {y}.", True),
    "corrected_value": ("It was {y}.", False),
    "corrected_dated": ("Based on what was known by {t}, it was {y}.", False),
    "negation_only": ("It was not {x}.", False),
    "negation_wrong": ("Not {x}; it was {y}.", False),
    "abstain": ("I do not have that information.", False),
    "unresolved": ("It was either {x} or {y}.", False),
}

SYSTEM = (
    "You read an answer to a question about what a memory held. The question names a "
    "person, an attribute, a date V the fact is about ('as of V') and a knowledge date T "
    "('based only on what was known by T'). The question asks for the value that, on the "
    "information available by T, held on V; information recorded after T does not change "
    "that answer, even when it corrects it.\n"
    "Report:\n"
    "- asserted_value: the single value the answer gives as its answer to this question. "
    "If the answer gives one value as what was known by T and another as a later change "
    "or correction, report the one known by T. If it gives one value and says nothing "
    "about T, report that value. If it only denies a value, declines, or says it does not "
    "know, report NONE. If it gives more than one value without making clear which one "
    "answers the question, report AMBIGUOUS.\n"
    "- mentions_later_value: true if the answer mentions a value it says was recorded, "
    "learned or corrected after T, else false.\n"
    "- span: the shortest exact quote from the answer that states the asserted value, or "
    "an empty string for NONE.\n"
    "Use only the answer's text, not your own knowledge."
)
USER = ('Question: {query}\nAnswer: {answer}\n\nReply with JSON only: '
        '{{"asserted_value": "...", "mentions_later_value": false, "span": "..."}}')
SPECIAL = {"NONE", "AMBIGUOUS", ""}


def prompt_hash() -> str:
    return hashlib.sha256(json.dumps({"system": SYSTEM, "user": USER}, sort_keys=True)
                          .encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def credited(asserted: str, expected: list[str], wrong: list[str]) -> bool:
    if asserted.strip().upper() in SPECIAL:
        return False
    return llm_rescore.exact(asserted, expected, wrong)


def _cell(row: dict) -> tuple:
    return (row["profile"], row["entities"], row["revisions"], row["seed"])


def items() -> list[dict]:
    out = []
    for row, fix in analyze_corrections.pre_correction_rows(TEMPLATE_SOURCE):
        x, query = row["expected_values"][0], row["query"]
        v = query.split(" as of ")[1].split(",")[0]
        t = query.split("known by ")[1].rstrip("?")
        for name, (text, ok) in TEMPLATES.items():
            out.append({"set": "constructed", "source": TEMPLATE_SOURCE, "template": name,
                        "case_id": row["case_id"], "query": query,
                        "answer": text.format(x=x, y=fix, t=t, v=v), "should_credit": ok,
                        "expected_values": [x], "wrong_values": sorted({fix, *row["stale_values"]})})
    for run in NATIVE:
        for row, fix in analyze_corrections.pre_correction_rows(run):
            out.append({"set": "native", "source": run, "case_id": row["case_id"],
                        "query": row["query"], "answer": row["answer"],
                        "expected_values": row["expected_values"],
                        "wrong_values": sorted({fix, *row["stale_values"]}),
                        "strict": bool(row["exact"]) and fix.casefold() not in row["answer"].casefold(),
                        "grid_exact": bool(row["exact"])})
    for reader, store in COMMON.items():
        fixes = {(_cell(r), r["case_id"]): fix for r, fix in analyze_corrections.pre_correction_rows(store)}
        for row in llm_rescore.rows(reader):
            fix = fixes.get((_cell(row), row["case_id"]))
            if fix is None:
                continue
            out.append({"set": "common", "source": reader, "case_id": row["case_id"],
                        "query": row["query"], "answer": row["output"],
                        "expected_values": row["expected_values"],
                        "wrong_values": sorted({fix, *row["stale_values"]}),
                        "strict": bool(row["exact"]) and fix.casefold() not in row["output"].casefold(),
                        "grid_exact": bool(row["exact"])})
    return out


def _complete(client, model: str, item: dict) -> str:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER.format(query=item["query"],
                                                       answer=item["answer"] or "(empty)")}]
    extra = ({"max_completion_tokens": 300, "reasoning_effort": "none"} if model.startswith("gpt-5")
             else {"max_tokens": 300})
    for attempt in range(6):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0, seed=7,
                response_format={"type": "json_object"}, **extra)
            return response.choices[0].message.content or ""
        except Exception as error:  # noqa: BLE001 - classified below
            llm_rescore.check_fatal(str(error))
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def main(backbone: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    provider, model = backbone.split(":", 1)
    client = llm_rescore._client(provider)
    work = items()
    errors: list[str] = []

    def one(item: dict) -> dict:
        try:
            text = _complete(client, model, item)
        except Exception as error:  # noqa: BLE001 - recorded; the run is then not sealed
            errors.append(redact(str(error)))
            text = ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        asserted = str(parsed.get("asserted_value", "")).strip()
        span = str(parsed.get("span", ""))
        return {**item, "output": text, "asserted_value": asserted,
                "mentions_later_value": bool(parsed.get("mentions_later_value", False)),
                "span": span, "span_verbatim": not span or _norm(span) in _norm(item["answer"]),
                "credited": credited(asserted, item["expected_values"], item["wrong_values"])}

    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = list(pool.map(one, work))
    if errors:
        raise SystemExit(f"{len(errors)} calls failed: {summarize(errors)}")
    summary: dict[str, dict] = {}
    for row in rows:
        key = (f"constructed:{row['template']}" if row["set"] == "constructed"
               else f"{row['set']}:{row['source']}")
        entry = summary.setdefault(key, {"n": 0, "credited": 0, "right": 0, "span_verbatim": 0})
        entry["n"] += 1
        entry["credited"] += row["credited"]
        entry["span_verbatim"] += row["span_verbatim"]
        if row["set"] == "constructed":
            entry["right"] += row["credited"] == row["should_credit"]
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary, "rows": len(rows)},
                                                 indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-h15-known-then-annotation-v1", "backbone": backbone,
                          "temperature": 0, "seed": 7, "prompt": {"system": SYSTEM, "user": USER},
                          "prompt_sha256": prompt_hash(), "templates": TEMPLATES,
                          "native": list(NATIVE), "common": COMMON},
             command=f"python scripts/annotate_known_then.py {backbone} {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
