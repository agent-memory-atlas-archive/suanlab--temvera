"""H13-E3: does the asserted-value judge get answers right whose truth we fix?

The judge of H9 is checked only against the exact scorer and a second judge of
the same family. Here its verdicts are tested on answers built from templates
whose correct verdict is known by construction: the right value alone, the
right value with the later one stated as history, a wrong value, a negated
wrong value, an abstention, and an unresolved pair. Valid-time questions come
from the main grid; for the questions about what was known before a correction
(H11a), the history-aware template states what was known then and what was
corrected later. Nothing is fitted to these answers: the judge prompt and model
are the ones of H9.

    python scripts/judge_minimal_pairs.py openai:gpt-4o experiments/runs/judge-minimal-pairs-v1
"""

from __future__ import annotations

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_corrections  # noqa: E402
import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402

RUNS = ROOT / "experiments" / "runs"
GRID_SOURCE = "external-cognee-grid-v1"
CORRECTION_SOURCE = "final-store-corrections-cognee-graph-v1"
PER_SOURCE = 40
SEED = 13

# template -> (text, correct verdict). {x}: right value, {y}: other value,
# {v}: the asked valid date, {t}: the asked knowledge date.
VALID_TIME = {
    "value_only": ("{x}.", True),
    "history_stated": ("As of {v} it was {x}; at another time it was {y}.", True),
    "negated_wrong": ("Not {y}; on {v} it was {x}.", True),
    "wrong_value": ("It was {y}.", False),
    "wrong_dated": ("As of {v} it was {y}.", False),
    "abstain": ("I do not have that information.", False),
    "unresolved": ("It was either {x} or {y}.", False),
}
KNOWN_THEN = {
    "value_only": ("{x}.", True),
    "history_stated": ("Based on what was known by {t}, it was {x}; a later correction says {y}.", True),
    "corrected_value": ("It was {y}.", False),
    "corrected_dated": ("Based on what was known by {t}, it was {y}.", False),
    "abstain": ("I do not have that information.", False),
}


def _cases() -> list[dict]:
    rng = random.Random(SEED)
    grid = [r for r in llm_rescore.rows(GRID_SOURCE)
            if r["category"] == "valid_time" and r["expected_values"] and r["stale_values"]]
    picked = rng.sample(grid, PER_SOURCE)
    out = []
    for row in picked:
        x, y = row["expected_values"][0], row["stale_values"][0]
        v = row["query"].split(" as of ")[1].split(",")[0]
        for name, (text, ok) in VALID_TIME.items():
            out.append({"source": GRID_SOURCE, "case_id": row["case_id"], "kind": "valid_time",
                        "template": name, "query": row["query"],
                        "answer": text.format(x=x, y=y, v=v, t=""), "should_credit": ok,
                        "expected_values": [x], "stale_values": [y]})
    pre = analyze_corrections.pre_correction_rows(CORRECTION_SOURCE)
    for row, fix_value in rng.sample(pre, min(PER_SOURCE, len(pre))):
        x = row["expected_values"][0]
        t = row["query"].split("known by ")[1].rstrip("?")
        for name, (text, ok) in KNOWN_THEN.items():
            out.append({"source": CORRECTION_SOURCE, "case_id": row["case_id"], "kind": "known_then",
                        "template": name, "query": row["query"],
                        "answer": text.format(x=x, y=fix_value, v="", t=t), "should_credit": ok,
                        "expected_values": [x], "stale_values": [fix_value]})
    return out


def main(backbone: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    provider, model = backbone.split(":", 1)
    client = llm_rescore._client(provider)
    cases = _cases()

    def one(case: dict) -> dict:
        text = llm_rescore._complete(client, model, "judge", case)
        value = llm_rescore._value("judge", text)
        credited = llm_rescore.judged(value, case["expected_values"], case["stale_values"])
        exact = llm_rescore.exact(case["answer"], case["expected_values"], case["stale_values"])
        return {**case, "judge_output": text, "value": value, "credited": credited,
                "exact_scorer": exact, "judge_right": credited == case["should_credit"],
                "exact_right": exact == case["should_credit"]}

    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(one, cases))
    summary: dict[str, dict] = {}
    for row in rows:
        key = f"{row['kind']}:{row['template']}"
        entry = summary.setdefault(key, {"n": 0, "judge_right": 0, "exact_right": 0,
                                         "should_credit": row["should_credit"]})
        entry["n"] += 1
        entry["judge_right"] += row["judge_right"]
        entry["exact_right"] += row["exact_right"]
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary}, indent=2,
                                                 sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-judge-minimal-pairs-v1", "backbone": backbone,
                          "judge_prompt_sha256": llm_rescore.prompt_hash("judge"),
                          "sources": [GRID_SOURCE, CORRECTION_SOURCE], "per_source": PER_SOURCE,
                          "seed": SEED, "valid_time_templates": VALID_TIME,
                          "known_then_templates": KNOWN_THEN},
             command=f"python scripts/judge_minimal_pairs.py {backbone} {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
