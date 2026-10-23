"""H14: the scale-and-cost runs, as the paper reports them.

Reads the sealed `scale-cost-*-v1` runs and prints, per system and checkpoint,
ingest latency and dollars per turn, query latency and dollars per question,
probe accuracy, store size and server memory; then the cost of a deployment at
several read:write ratios, from the 3,000-turn rates; then each H14 prediction.

    python scripts/analyze_scale_cost.py [run-dir ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"
SYSTEMS = ("mem0", "graphiti", "hindsight")
RATIOS = (1, 10, 100)  # queries per write


def load(system: str, root: Path = RUNS) -> dict:
    path = root / f"scale-growth-{system}-v1" / "results.json"
    return json.loads(path.read_text(encoding="utf-8"))


PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00), "text-embedding-3-small": (0.02, 0.0)}


def _cost(entries: list[tuple[str, dict]]) -> float:
    total = 0.0
    for key, e in entries:
        rate_in, rate_out = PRICES.get(key.split("|")[-1], (0.0, 0.0))
        total += (e["prompt_tokens"] * rate_in + e["completion_tokens"] * rate_out) / 1e6
    return total


def _split(checkpoint: dict) -> tuple[list, list]:
    """(write-side, read-side) usage of a checkpoint. Hindsight logs each LLM
    request with its operation; its consolidation runs in the background after a
    retain and can land while questions are asked, so the split is by
    operation: ``reflect`` is reading, everything else is writing. In-process
    systems are split by when the call happened."""
    both = [*checkpoint["ingest_usage"].items(), *checkpoint["query_usage"].items()]
    if any(k.split("|")[0] not in ("inprocess",) for k, _ in both):
        return ([kv for kv in both if not kv[0].startswith("reflect")],
                [kv for kv in both if kv[0].startswith("reflect")])
    return list(checkpoint["ingest_usage"].items()), list(checkpoint["query_usage"].items())


def per_turn(checkpoint: dict) -> dict:
    write, _ = _split(checkpoint)
    turns = checkpoint["segment_turns"]
    tokens = sum(e["prompt_tokens"] + e["completion_tokens"] for _, e in write)
    return {"usd": _cost(write) / turns, "tokens": tokens / turns}


def per_query(checkpoint: dict, path: str | None = None) -> float:
    """Dollars per question. Retrieval layers make no LLM call beyond an
    embedding; for Hindsight the read-side cost is its reader's."""
    _, read = _split(checkpoint)
    asked = max(v["n"] for v in checkpoint["query_latency"].values())
    return _cost(read) / asked if asked else 0.0


def rate(checkpoint: dict, path: str, category: str) -> tuple[int, int]:
    entry = checkpoint["exact"].get(path, {}).get(category)
    return (entry["hits"], entry["n"]) if entry else (0, 0)


def deployment_cost(run: dict, writes: int, ratio: int) -> dict:
    last = run["checkpoints"][-1]
    write = per_turn(last)["usd"] * writes
    read = per_query(last) * writes * ratio
    return {"writes_usd": write, "reads_usd": read, "total_usd": write + read}


def checks(runs: dict[str, dict]) -> dict[str, bool]:
    m, g, h = runs.get("mem0"), runs.get("graphiti"), runs.get("hindsight")
    out = {}
    if m:
        out["H14a"] = per_turn(m["checkpoints"][-1])["usd"] <= 1.5 * per_turn(m["checkpoints"][0])["usd"]
    if g:
        out["H14b"] = per_turn(g["checkpoints"][-1])["tokens"] >= 1.3 * per_turn(g["checkpoints"][0])["tokens"]
    if m and g and h and all(any(c["turns"] == 3000 for c in r["checkpoints"]) for r in runs.values()):
        last = {s: r["checkpoints"][-1] for s, r in runs.items()}
        out["H14c"] = all(last[s]["query_latency"]["retrieval"]["p95_s"] < 2 for s in SYSTEMS) and \
            last["hindsight"]["query_latency"]["reader"]["p95_s"] >= 5
        ok = True
        for turns in (1000, 3000):
            def r(run, path):
                cp = next(c for c in run["checkpoints"] if c["turns"] == turns)
                hits, n = rate(cp, path, "valid_time")
                return hits / n if n else 0.0
            ok &= r(m, "retrieval") <= 0.40 and r(g, "retrieval") <= 0.10 and \
                r(h, "retrieval") <= 0.10 and r(h, "reader") > r(h, "retrieval")
        out["H14d"] = ok
        out["H14e"] = all(per_turn(last[s])["usd"] >= 10 * per_query(last[s]) for s in ("mem0", "graphiti")) \
            and per_query(last["hindsight"]) > per_turn(last["hindsight"])["usd"]
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else RUNS
    runs = {}
    for system in SYSTEMS:
        try:
            runs[system] = load(system, root)
        except FileNotFoundError:
            continue
    for system, run in runs.items():
        for cp in run["checkpoints"]:
            lat = cp["query_latency"]
            paths = " ".join(f"{p}: p95 {v['p95_s']:.2f}s cur {rate(cp, p, 'current')} vt {rate(cp, p, 'valid_time')}"
                             for p, v in lat.items())
            print(f"{system:9s} {cp['turns']:5d} turns | ingest p50 {cp['ingest_latency']['p50_s']:.2f}s "
                  f"p95 {cp['ingest_latency']['p95_s']:.2f}s {cp['ingest_throughput_turns_per_s']:.2f} t/s "
                  f"${per_turn(cp)['usd']:.5f}/turn {per_turn(cp)['tokens']:.0f} tok/turn | "
                  f"${per_query(cp):.5f}/q | {paths} | rss {cp['server_rss_kb']}")
        for ratio in RATIOS:
            print(f"   1,000 writes at {ratio}:1 reads -> {deployment_cost(run, 1000, ratio)}")
        if run.get("concurrency"):
            print("   concurrency", {k: (round(v["throughput_qps"], 2), round(v["latency"]["p95_s"], 2))
                                     for k, v in run["concurrency"].items()})
    print(checks(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
