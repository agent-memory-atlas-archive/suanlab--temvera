"""Seal the console logs of the three LongMemEval Mem0 runs, so the paper's
dropped-action counts recompute from an artifact rather than from memory.

Mem0 0.1.118 logs ``Error processing memory action: {...}, Error: '<id>'`` when
the model names a memory by an out-of-range positional id; the action is then
dropped while ``add()`` reports success (E-065). These lines went only to the
console, which the runs' seals do not cover. The console captures survived
outside the repository. Each is copied byte for byte, and accepted only if the
result JSON it ends with equals its run's sealed ``results.json`` (less the
per-instance list, which the console did not print) -- which ties
the log to the run -- and its count of store resets equals the run's number of
conversations.

    python scripts/seal_mem0_drop_logs.py <dir-with-logs> experiments/runs/mem0-dropped-actions-logs-v1
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from temvera.experiment import seal_run

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
LOGS = {"longmemeval-e7-v1": "e7b.log", "longmemeval-e7-v2": "e7full2.log",
        "longmemeval-s-v1": "e7s.log"}
DROPPED = re.compile(r"^Error processing memory action: \{.*'event': '(UPDATE|DELETE)'.*\}, Error: '\d+'$")


def count(text: str) -> dict:
    lines = text.splitlines()
    events = [DROPPED.match(line) for line in lines]
    return {"dropped": sum(1 for m in events if m),
            "dropped_update": sum(1 for m in events if m and m.group(1) == "UPDATE"),
            "dropped_delete": sum(1 for m in events if m and m.group(1) == "DELETE"),
            "conversations": sum(1 for line in lines if line.startswith("Resetting index"))}


def main(source: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    results = {}
    for run, name in LOGS.items():
        text = (Path(source) / name).read_text(encoding="utf-8")
        tail = json.loads(text.strip().splitlines()[-1])
        sealed = json.loads((RUNS / run / "results.json").read_text(encoding="utf-8"))
        # The console printed the summary without its per-instance list.
        if tail != {k: v for k, v in sealed.items() if k != "per_instance"}:
            raise SystemExit(f"{name} does not end with {run}'s sealed results")
        tally = count(text)
        if tally["conversations"] != sealed["instances"]:
            raise SystemExit(f"{name}: {tally['conversations']} resets, run has {sealed['instances']}")
        results[run] = {"log": f"{run}.console.log", **tally}
    out.mkdir(parents=True)
    for run, name in LOGS.items():
        shutil.copyfile(Path(source) / name, out / f"{run}.console.log")
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-mem0-dropped-actions-logs-v1", "runs": list(LOGS),
                          "pattern": DROPPED.pattern,
                          "check": "trailing result JSON equals the run's sealed results.json without per_instance; "
                                   "store resets equal its instance count"},
             command=f"python scripts/seal_mem0_drop_logs.py <console logs> {output}")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
