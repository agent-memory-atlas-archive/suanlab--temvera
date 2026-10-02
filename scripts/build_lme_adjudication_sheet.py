"""Lay out the labels two models could not settle, for the author to decide.

Each item shows both models' answers beside the sentences in each session that
contain them, plus a *suggestion* -- which value the benchmark's own gold answer
corroborates, or which span is tighter -- clearly marked as one. The decision is
the author's; `apply_lme_decisions.py` records it. The sheet quotes the corpus,
so it is a local file and is not tracked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from temvera.lme_bitemporal import load

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "lme-disagreements.json"
SHEET = ROOT / "data" / "lme-review-sheet.md"
A, B = "gpt-4o-mini", "gpt-4o"


def _n(text: object) -> str:
    return " ".join(str(text).lower().split()) if text is not None else ""


def _sentences(turns: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for turn in turns:
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", turn) if s.strip()]
    return out


def _containing(sentences: list[str], values: list[object]) -> list[str]:
    keys = [_n(v) for v in values if v]
    return [s for s in sentences if any(k and k in _n(s) for k in keys)][:3]


def _suggest(item: dict) -> str:
    a, b, gold = item[A], item[B], _n(item["benchmark_answer"])
    if item["kind"] == "extraction rejected":
        return "none -- read the sessions"
    parts = []
    for side in ("earlier_value", "later_value"):
        va, vb = a[side], b[side]
        if _n(va) == _n(vb):
            parts.append(f"{side}={va!r}")
        elif _n(va) in gold and _n(vb) not in gold:
            parts.append(f"{side}={va!r} (in the benchmark answer)")
        elif _n(vb) in gold and _n(va) not in gold:
            parts.append(f"{side}={vb!r} (in the benchmark answer)")
        else:
            shorter = min((va, vb), key=lambda v: len(str(v)))
            parts.append(f"{side}={shorter!r} (tighter span)")
    if a["question_asks_for"] != b["question_asks_for"]:
        parts.append(f"asks_for: {a['question_asks_for']} vs {b['question_asks_for']}")
    return "; ".join(parts)


def main() -> int:
    items = json.loads(REVIEW.read_text(encoding="utf-8"))
    pairs = {p.question_id: p for p in load(ROOT / "data" / "raw" / "longmemeval_oracle.json")}
    lines = [
        "# LongMemEval supersession labels to decide",
        "",
        "For each item, reply with A (gpt-4o-mini), B (gpt-4o), S (the suggestion),",
        "X (exclude, with a reason), or the values yourself. Suggestions are not decisions.",
        "",
    ]
    for number, item in enumerate(items, 1):
        pair = pairs[item["question_id"]]
        a, b = item[A], item[B]
        lines += [
            f"## {number}. `{item['question_id']}` — {item['kind']}",
            "",
            f"**Q:** {item['question']}  ",
            f"**Benchmark answer:** {item['benchmark_answer']}",
            "",
            "| | earlier value | later value | asks for | rejected |",
            "|---|---|---|---|---|",
            f"| A | {a['earlier_value']!r} | {a['later_value']!r} | {a['question_asks_for']} | {a['rejected_because'] or '—'} |",
            f"| B | {b['earlier_value']!r} | {b['later_value']!r} | {b['question_asks_for']} | {b['rejected_because'] or '—'} |",
            "",
            f"*Earlier session ({pair.earlier.recorded_at:%Y-%m-%d}):*",
        ]
        for s in _containing(_sentences(pair.earlier.user_turns), [a["earlier_value"], b["earlier_value"]]) or ["(neither value appears)"]:
            lines.append(f"> {s}")
        lines += ["", f"*Later session ({pair.later.recorded_at:%Y-%m-%d}):*"]
        for s in _containing(_sentences(pair.later.user_turns), [a["later_value"], b["later_value"]]) or ["(neither value appears)"]:
            lines.append(f"> {s}")
        lines += ["", f"**Suggestion:** {_suggest(item)}", "", "**Decision:** ", ""]
    SHEET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {SHEET.relative_to(ROOT)}: {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
