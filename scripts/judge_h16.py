"""H16, after the runs: the H9 asserted-value judge on the readers' answers.

The exact scorer fails an answer that names a superseded value even when it says
which value held when; the H9 judge (valid for valid-time questions, 279/280
constructed answers) reports the value the answer asserts instead. Applied, as
preregistered, to the common reader's and Hindsight's own reader's answers in
the six sealed H16 runs; no H16 prediction uses it.

    python scripts/judge_h16.py openai:gpt-4o experiments/runs/h16-judge-gpt4o-v1
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
from temvera.worker_errors import redact, summarize  # noqa: E402

RUNS = ROOT / "experiments" / "runs"
SOURCES = [f"h16-fixed-{system}-s{seed}-v1" for system in ("mem0", "hindsight") for seed in (1, 2, 3)]
PATHS = ("common_reader", "own_reader")


def main(backbone: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    provider, model = backbone.split(":", 1)
    client = llm_rescore._client(provider)
    work = []
    for source in SOURCES:
        lines = (RUNS / source / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
        work += [{**json.loads(line), "source": source} for line in lines
                 if json.loads(line)["path"] in PATHS]
    errors: list[str] = []

    def one(row: dict) -> dict:
        try:
            text = llm_rescore._complete(client, model, "judge", row)
        except Exception as error:  # noqa: BLE001 - recorded; the run is then not sealed
            errors.append(redact(str(error)))
            text = ""
        value = llm_rescore._value("judge", text)
        keep = {k: row[k] for k in ("source", "seed_index", "condition", "path", "case_id", "category",
                                    "query", "expected_values", "stale_values", "exact")}
        return {**keep, "answer": row["answer"], "judge_output": text, "value": value,
                "judged": llm_rescore.judged(value, row["expected_values"], row["stale_values"])}

    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(one, work))
    if errors:
        raise SystemExit(f"{len(errors)} calls failed: {summarize(errors)}")
    summary: dict[str, dict] = {}
    for row in rows:
        system = row["source"].split("-")[2]
        key = f"{system}|{row['condition']}|{row['path']}|{row['category']}"
        entry = summary.setdefault(key, {"n": 0, "exact": 0, "judged": 0})
        entry["n"] += 1
        entry["exact"] += row["exact"]
        entry["judged"] += row["judged"]
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary}, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-h16-judge-v1", "backbone": backbone, "sources": SOURCES,
                          "paths": list(PATHS), "judge_prompt_sha256": llm_rescore.prompt_hash("judge"),
                          "temperature": 0, "seed": 7},
             command=f"python scripts/judge_h16.py {backbone} {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
