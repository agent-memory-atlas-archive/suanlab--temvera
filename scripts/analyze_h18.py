"""H18: Hindsight's past-knowledge answers -- reader or context?

    python scripts/analyze_h18.py
"""

from __future__ import annotations

import json
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "experiments" / "runs" / "h18-native-context-hindsight-v1"


def summary() -> dict:
    return json.loads((RUN / "results.json").read_text(encoding="utf-8"))["summary"]


def checks() -> dict[str, bool]:
    s = summary()
    own, native, recall = (s[p]["credited"] for p in ("own_reader", "common_native", "common_recall"))
    return {"H18a": own >= 20, "H18b": native >= own - 5, "H18c": recall <= 12,
            "H18d": native >= recall + 10}


def main() -> int:
    print(json.dumps(summary(), indent=2, sort_keys=True))
    print(checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
