"""H17: deletion over units that mix what must go with what must stay.

    python scripts/analyze_h17.py
"""

from __future__ import annotations

import json
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"
SYSTEMS = ("mem0", "hindsight")


def summary(system: str) -> dict:
    path = RUNS / f"h17-deletion-mixed-{system}-v1" / "results.json"
    return json.loads(path.read_text(encoding="utf-8"))["summary"]


def rate(kept: int, before: int) -> float:
    return kept / before if before else float("nan")


def checks() -> dict[str, bool]:
    s = {system: summary(system) for system in SYSTEMS}
    left = lambda sys_, unit, caller, field="purge_left_after": s[sys_][f"{unit}|{caller}"][field]  # noqa: E731
    colocated = lambda sys_, unit, caller: rate(s[sys_][f"{unit}|{caller}"]["colocated_kept"],  # noqa: E731
                                               s[sys_][f"{unit}|{caller}"]["colocated_before"])
    out = {}
    out["H17a"] = all(
        sum(left(x, u, "api-verified", "purge_left_after_named" if u == "shared" else "purge_left_after")
            for u in ("attributes", "people", "shared"))
        <= 0.10 * sum(s[x][f"{u}|api-verified"]["purge"] for u in ("attributes", "people", "shared"))
        for x in SYSTEMS)
    out["H17b"] = all(colocated("hindsight", u, "api-verified") <= 0.20 for u in ("attributes", "people"))
    out["H17c"] = all(colocated("mem0", u, "api-verified") >= 0.80 for u in ("attributes", "people"))
    out["H17d"] = all(colocated(x, "shared", "api-oracle") <= 0.20 for x in SYSTEMS)
    out["H17e"] = all(colocated(x, "shared", "api-verified") >= 0.80 for x in SYSTEMS)
    out["H17f"] = all(rate(s[x]["attributes|api-verified"]["other_kept"],
                           s[x]["attributes|api-verified"]["other_before"]) >= 0.90 for x in SYSTEMS)
    return out


def main() -> int:
    for system in SYSTEMS:
        for key, entry in sorted(summary(system).items()):
            print(f"{system:9s} {key:24s} {entry}")
    print(checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
