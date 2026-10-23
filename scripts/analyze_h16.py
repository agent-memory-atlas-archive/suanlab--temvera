"""H16: size and revision load separated; three read paths and their cost.

Reads the sealed ``h16-fixed-{mem0,hindsight}-s{1,2,3}-v1`` runs, pools the three
seeds per store, path and category, prints rates, p95 latency, API dollars per
question and per ingested turn, memory, and each H16 prediction.

    python scripts/analyze_h16.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
SEEDS = (1, 2, 3)
STORES = ("size-300", "size-1005", "size-3000", "rev-2", "rev-5")


def run_name(system: str, seed: int) -> str:
    return f"h16-fixed-{system}-s{seed}-v1"


def rows(system: str) -> list[dict]:
    out = []
    for seed in SEEDS:
        path = RUNS / run_name(system, seed) / "transcript.jsonl"
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return out


def summaries(system: str) -> dict[tuple[int, str], dict]:
    out = {}
    for seed in SEEDS:
        res = json.loads((RUNS / run_name(system, seed) / "results.json").read_text(encoding="utf-8"))
        for c in res["conditions"]:
            out[(seed, c["condition"])] = c
    return out


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))] if ordered else 0.0


def cell(system: str, store: str, path: str, category: str | None = None, seed: int | None = None) -> dict:
    mine = [r for r in rows(system) if r["condition"] == store and r["path"] == path
            and (category is None or r["category"] == category) and (seed is None or r["seed_index"] == seed)]
    n = len(mine)
    return {"n": n, "exact": sum(r["exact"] for r in mine) / n if n else 0.0,
            "stale": sum(r["present_stale"] for r in mine) / n if n else 0.0,
            "p95_s": _p95([r["latency_s"] for r in mine]),
            "usd_per_q": sum(r["cost_usd"] for r in mine) / n if n else 0.0,
            "errors": sum(bool(r["error"]) for r in mine)}


def ingest_usd_per_turn(system: str, store: str) -> float:
    s = [v for (seed, c), v in summaries(system).items() if c == store]
    return sum(v["ingest_cost_usd"] for v in s) / sum(v["turns"] for v in s)


def checks() -> dict[str, bool]:
    m = lambda store, path, cat=None: cell("mem0", store, path, cat)  # noqa: E731
    h = lambda store, path, cat=None: cell("hindsight", store, path, cat)  # noqa: E731
    sizes = STORES[:3]
    out = {}
    out["H16a"] = all(m(s, "retrieval", "current")["exact"] >= 0.80 for s in sizes) and \
        abs(m("size-300", "retrieval", "current")["exact"] - m("size-3000", "retrieval", "current")["exact"]) <= 0.10 \
        and all(m(s, "retrieval", "valid_time")["exact"] <= 0.15 for s in sizes)
    out["H16b"] = all(h(s, "retrieval", "current")["exact"] <= 0.25 for s in sizes) and \
        all(h(s, "retrieval", "current")["stale"] >= 0.60 for s in sizes)
    out["H16c"] = h("rev-5", "retrieval", "current")["stale"] >= h("rev-2", "retrieval", "current")["stale"] and \
        abs(m("rev-5", "retrieval", "current")["exact"] - m("rev-2", "retrieval", "current")["exact"]) <= 0.10
    out["H16d"] = all(h(s, "own_reader", "valid_time")["exact"] >= 0.60 for s in sizes) and \
        h("size-3000", "own_reader")["p95_s"] >= 1.5 * h("size-300", "own_reader")["p95_s"]
    out["H16e"] = all(h(s, "common_reader", "valid_time")["exact"] >= 0.50 for s in sizes) and \
        all(h(s, "common_reader")["usd_per_q"] + h(s, "retrieval")["usd_per_q"]
            <= 0.2 * h(s, "own_reader")["usd_per_q"] for s in sizes) and \
        all(h(s, "common_reader")["p95_s"] + h(s, "retrieval")["p95_s"]
            <= 0.5 * h(s, "own_reader")["p95_s"] for s in sizes) and \
        all(m(s, "common_reader", "valid_time")["exact"] <= 0.15 for s in sizes)
    out["H16f"] = ingest_usd_per_turn("mem0", "size-3000") <= 1.25 * ingest_usd_per_turn("mem0", "size-300") and \
        ingest_usd_per_turn("hindsight", "size-3000") >= 1.10 * ingest_usd_per_turn("hindsight", "size-300")
    out["H16g"] = h("size-3000", "retrieval")["p95_s"] >= 1.2 * h("size-300", "retrieval")["p95_s"] and \
        m("size-3000", "retrieval")["p95_s"] <= 1.5 * m("size-300", "retrieval")["p95_s"]
    return out


def main() -> int:
    for system in ("mem0", "hindsight"):
        paths = ("retrieval", "common_reader") + (("own_reader",) if system == "hindsight" else ())
        for store in STORES:
            print(f"{system:9s} {store:9s} ingest ${ingest_usd_per_turn(system, store):.5f}/turn")
            for path in paths:
                cur, vt, both = (cell(system, store, path, c) for c in ("current", "valid_time", None))
                per_seed = [round(cell(system, store, path, "valid_time", s)["exact"], 2) for s in SEEDS]
                print(f"   {path:13s} current {cur['exact']:.3f} (stale {cur['stale']:.2f}) "
                      f"valid {vt['exact']:.3f} {per_seed} p95 {both['p95_s']:.2f}s "
                      f"${both['usd_per_q']:.5f}/q errors {both['errors']}")
        for (seed, store), s in sorted(summaries(system).items()):
            print(f"   s{seed} {store:9s} turns {s['turns']} memory {s['memory']} settle {s['settle']}")
    print(checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
