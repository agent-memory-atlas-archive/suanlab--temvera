"""Would a one-rule read path recover what the retrieval layer leaves unfiltered?

For each retrieval-layer answer, keep only the statements about the queried
subject and attribute that carry a validity date -- "<subject>'s <attribute>
is [now] <value>, valid from <date>" or "... as of <date>" -- and answer with
the value whose date is the latest not after the question's valid time. Nothing
else is used: no oracle values, no LLM. The rule was fixed and committed before
it was run on any transcript.

It applies only where the store returns dated statements: Cognee (chunks)
returns the stored turns and Hindsight (recall) restates facts with their
validity. Graphiti's facts carry no dates in their text, so the rule cannot
apply, and that is reported rather than worked around. The result bounds what
the returned evidence supports; it is not a system we evaluate.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from temvera.reanalysis import Proportion

RUNS = Path(__file__).resolve().parents[1] / "experiments" / "runs"
CONFIGS = {
    "Cognee chunks": "external-cognee-chunks-grid-v3",
    "Hindsight recall": "external-hindsight-recall-v1",
    "Graphiti": "external-graphiti-hybrid-v1",
}
QUERY = re.compile(r"What is (?P<subj>.+?)'s (?P<attr>.+?) as of (?P<v>\d{4}-\d{2}-\d{2}),")
DATE = r"(?P<date>\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2}, \d{4})"


def _day(text: str) -> date:
    for fmt in ("%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def statements(answer: str, subj: str, attr: str) -> list[tuple[date, str]]:
    pattern = re.compile(
        re.escape(subj) + r"'s " + re.escape(attr)
        + r" is (?:now )?(?P<val>[^,|]+?),? (?:valid from|as of) " + DATE
    )
    return [(_day(m.group("date")), m.group("val").strip()) for m in pattern.finditer(answer)]


def filtered(answer: str, query: str) -> str | None:
    """The rule's answer, or None when the returned text has no dated statement."""
    m = QUERY.match(query)
    if not m:
        return None
    found = statements(answer, m.group("subj"), m.group("attr"))
    if not found:
        return None
    asked = _day(m.group("v"))
    eligible = [s for s in found if s[0] <= asked]
    return max(eligible)[1] if eligible else ""


def evaluate(run: str, category: str = "valid_time") -> dict[str, int]:
    rows = [json.loads(line) for line in (RUNS / run / "transcript.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r.get("system") != "oracle" and r["category"] == category
            and r["expected_values"]]
    out = {"questions": len(rows), "applicable": 0, "exact": 0, "exact_unfiltered": 0}
    for r in rows:
        out["exact_unfiltered"] += bool(r["exact"])
        answer = filtered(r["answer"], r["query"])
        if answer is None:
            continue
        out["applicable"] += 1
        expected, stale = r["expected_values"], r["stale_values"]
        out["exact"] += all(e in answer for e in expected) and not any(s in answer for s in stale)
    return out


def main() -> int:
    for name, run in CONFIGS.items():
        r = evaluate(run)
        p = Proportion(r["exact"], r["questions"])
        low, high = p.wilson()
        print(f"{name:17s} valid-time questions {r['questions']}, rule applicable {r['applicable']}, "
              f"exact unfiltered {r['exact_unfiltered']} -> with the rule {r['exact']} "
              f"({p.rate:.3f} [{low:.3f}, {high:.3f}])")
    return 0


if __name__ == "__main__":
    sys.exit(main())
