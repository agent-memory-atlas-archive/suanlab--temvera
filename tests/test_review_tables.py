"""The review tables reproduce the counts the paper prints from the same rows.

A structured review of the 90 reader answers (MODIFY.md, M01) starts from
these tables; if they drifted from the strict counts in the paper (41 and 25),
the review would grade different answers than the ones reported.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_review_tables  # noqa: E402


def test_pre_correction_table_matches_printed_strict_counts() -> None:
    rows = extract_review_tables.pre_correction_table()
    strict = {run: sum(r["strict"] for r in rows if r["run"] == run)
              for run in extract_review_tables.READERS}
    assert len(rows) == 90
    assert strict == {"final-store-corrections-hindsight-reflect-v1": 25,
                      "final-store-corrections-cognee-graph-v1": 41}


def test_refuses_to_overwrite(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit):
        extract_review_tables.main(str(tmp_path))
