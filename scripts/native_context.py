"""H18: is Hindsight's advantage on past knowledge its reader, or its context?

Asked of the final store what was known before a correction, Hindsight's own
reader is credited on 29 of 45 questions and the common reader over its recall's
top five on 8 (E-105, E-110). The two differ in context and in reader at once.
Hindsight's reflect can return the memories it based its answer on, so the same
common reader can be given exactly that context:

* ``own_reader``     -- reflect's answer;
* ``common_native``  -- the H9 common reader over the memories reflect used;
* ``common_recall``  -- the H9 common reader over recall's top five (as in H13).

Each correction history of the H11 final-store runs (10 seeds, 8 people, three
revisions, corrections) is ingested whole into a fresh bank; the questions about
a corrected interval before its correction are asked; every answer is scored by
the strict count and read by the H15 annotator (``gpt-4o-2024-08-06``, its
fixed prompt).

    python scripts/native_context.py experiments/runs/h18-native-context-hindsight-v1
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import annotate_known_then  # noqa: E402
import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402
from temvera.external_experiment import _events_for  # noqa: E402
from temvera.model import Operation  # noqa: E402
from temvera.nl_workload import build_nl_cases, render_turns  # noqa: E402

SOURCE = ROOT / "experiments" / "runs" / "final-store-corrections-hindsight-reflect-v1"
ANNOTATOR = "gpt-4o-2024-08-06"
READER = "gpt-4o-mini"
if os.environ.get("TEMVERA_H18_SMOKE"):
    SEEDS_OVERRIDE = (3,)  # a history the study does not use
else:
    SEEDS_OVERRIDE = None


def config() -> dict:
    return json.loads((SOURCE / "config.json").read_text(encoding="utf-8"))


def pre_correction_cases(events) -> list[tuple]:
    """(case, the correction's value) for questions about a corrected interval
    asked before the correction was recorded -- the H11a selection."""
    fixes = {(e.subject, e.attribute): e for e in events
             if e.operation is Operation.INGEST and e.valid_to is not None}
    out = []
    for case in build_nl_cases(events):
        fix = fixes.get((case.subject, case.attribute))
        if fix is not None and case.transaction_at < fix.recorded_at \
                and fix.valid_from <= case.valid_at < fix.valid_to:
            out.append((case, fix.value))
    return out


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values() if v is not None)
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def reflect_with_context(system, query: str) -> tuple[str, str, int]:
    response = system._post("/reflect", {"query": query, "include": {"facts": {}}})
    based = response.get("based_on") or {}
    units = list(based.get("memories") or []) + list(based.get("mental_models") or [])
    return str(response.get("text", "")), " | ".join(_flatten(u) for u in units), len(units)


def common_read(client, records: str, query: str) -> str:
    return llm_rescore._complete(client, READER, "reader", {"answer": records, "query": query}).strip()


def annotate(client, query: str, answer: str, expected: list[str], wrong: list[str]) -> dict:
    item = {"query": query, "answer": answer}
    text = annotate_known_then._complete(client, ANNOTATOR, item)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {}
    asserted = str(parsed.get("asserted_value", "")).strip()
    return {"asserted_value": asserted, "annotator_output": text,
            "credited": annotate_known_then.credited(asserted, expected, wrong)}


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    if SEEDS_OVERRIDE and "experiments" in out.resolve().parts:
        raise SystemExit("smoke runs are never written under experiments/")
    from temvera.hindsight_adapter import HindsightSystem

    cfg = config()
    profile, scale = cfg["profiles"][0], cfg["scales"][0]
    url = os.environ.get("HINDSIGHT_URL", "http://localhost:8888")
    client = llm_rescore._client("openai")
    rows = []
    for seed in SEEDS_OVERRIDE or cfg["seeds"]:
        events = _events_for(seed, scale["entities"], scale["revisions"], profile, True, 1,
                             bool(cfg["distinct_values"]), cfg["natural_pools"])
        turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
        bank = f"h18-s{seed}"
        recall = HindsightSystem(base_url=url, bank=bank, read_mode="recall")
        recall.reset()
        recall._errors.clear()
        for turn in turns:
            recall.ingest(turn)
        for case, fix in pre_correction_cases(events):
            expected = sorted(case.expected_values)
            wrong = sorted({fix, *case.stale_values})
            own, native, units = reflect_with_context(recall, case.query_text)
            top5 = recall.answer(case)
            answers = {"own_reader": own, "common_native": common_read(client, native, case.query_text),
                       "common_recall": common_read(client, top5, case.query_text)}
            for path, answer in answers.items():
                strict = llm_rescore.exact(answer, expected, sorted(case.stale_values)) \
                    and fix.casefold() not in answer.casefold()
                rows.append({"seed": seed, "case_id": case.case_id, "query": case.query_text,
                             "path": path, "answer": answer, "expected_values": expected,
                             "wrong_values": wrong, "strict": strict,
                             "context_units": units if path != "common_recall" else 5,
                             "context": native if path == "common_native" else
                             (top5 if path == "common_recall" else ""),
                             **annotate(client, case.query_text, answer, expected, wrong)})
        if recall.worker_errors:
            raise SystemExit(f"seed {seed}: {recall.worker_errors} worker errors: {recall.error_messages[:2]}")
        recall.reset()
    summary: dict[str, dict] = {}
    for row in rows:
        entry = summary.setdefault(row["path"], {"n": 0, "strict": 0, "credited": 0})
        entry["n"] += 1
        entry["strict"] += row["strict"]
        entry["credited"] += row["credited"]
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary}, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-h18-native-context-hindsight-v1", "source_config": cfg,
                          "annotator": ANNOTATOR, "annotator_prompt_sha256": annotate_known_then.prompt_hash(),
                          "reader": READER, "reader_prompt_sha256": llm_rescore.prompt_hash("reader"),
                          "hindsight_url": url},
             command=f"python scripts/native_context.py {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
