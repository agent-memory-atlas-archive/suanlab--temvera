"""The H17 harness measures what it claims on stores whose behaviour is known.

A document store deletes whole turns; a fact store splits each turn into its
statements and deletes statements. Under a caller that checks the name, the
document store must lose what shares a turn with a deleted fact and the fact
store must keep it; under a value-matching oracle, a shared value is lost in
both."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deletion_mixed  # noqa: E402


class _Store:
    split = False

    def __init__(self) -> None:
        self.units: list[str] = []

    def ingest(self, turn) -> None:
        body = turn.text.split("] ", 1)[1]
        self.units += re.split(r",? and ", body) if self.split else [body]

    def _hits(self, query: str) -> list[str]:
        subject = query.removeprefix("What is ").split("'s ")[0]
        return [u for u in self.units if subject in u]

    def answer(self, query: str) -> str:
        return " | ".join(self._hits(query))

    def delete_oracle(self, needles) -> int:
        doomed = [u for u in self.units if any(n in u for n in needles)]
        self.units = [u for u in self.units if u not in doomed]
        return len(doomed)

    def delete_verified(self, query: str, subject: str) -> int:
        attribute = query.split("'s ", 1)[1].rstrip("?")
        doomed = [u for u in self._hits(query) if f"{subject}'s {attribute}" in u]
        self.units = [u for u in self.units if u not in doomed]
        return len(doomed)

    def errors(self) -> int:
        return 0

    def extra(self) -> dict:
        return {}


class _Facts(_Store):
    split = True


def _run(store_cls, unit: str, caller: str) -> dict:
    turns, facts = deletion_mixed.history(11, unit)
    record = deletion_mixed.measure(store_cls(), unit, caller, turns, facts)
    return deletion_mixed.tally([record])[f"{unit}|{caller}"]


def test_document_store_loses_what_shares_a_unit() -> None:
    for unit in ("attributes", "people"):
        t = _run(_Store, unit, "api-verified")
        assert t["purge_left_after"] == 0
        assert t["colocated_before"] == 6 and t["colocated_kept"] == 0


def test_fact_store_keeps_what_shares_a_unit() -> None:
    for unit in ("attributes", "people"):
        t = _run(_Facts, unit, "api-verified")
        assert t["purge_left_after"] == 0
        assert t["colocated_kept"] == t["colocated_before"] == 6
    assert _run(_Facts, "attributes", "api-verified")["other_kept"] == 12


def test_value_matching_loses_a_shared_value_and_a_name_check_does_not() -> None:
    assert _run(_Facts, "shared", "api-oracle")["colocated_kept"] == 0
    assert _run(_Facts, "shared", "api-verified")["colocated_kept"] == 6
