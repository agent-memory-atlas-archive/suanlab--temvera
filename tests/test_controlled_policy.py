"""The controlled-policy store builder and retriever, on a toy history."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from temvera.model import MemoryEvent, Operation
from temvera.nl_workload import render_turns

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "controlled_policy", ROOT / "scripts" / "controlled_policy.py")
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)


def _day(d: int) -> datetime:
    return datetime(2025, 1, d, tzinfo=timezone.utc)


def _history():
    return (
        MemoryEvent(event_id="e1", operation=Operation.INGEST, belief_id="b1", subject="Zed",
                    attribute="home city", value="Teal", valid_from=_day(1), recorded_at=_day(2)),
        MemoryEvent(event_id="e2", operation=Operation.INGEST, belief_id="b2", subject="Zed",
                    attribute="home city", value="Mauve", valid_from=_day(5), recorded_at=_day(6)),
        MemoryEvent(event_id="e3", operation=Operation.SUPERSEDE, belief_id="b2",
                    target_id="b1", recorded_at=_day(6)),
    )


def test_retain_keeps_everything_and_consolidate_only_the_latest() -> None:
    events = _history()
    turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
    built = policy.stores(events, turns, _day(7))
    assert any("Teal" in r for r in built["retain"]) and any("Mauve" in r for r in built["retain"])
    assert not any("Teal" in r for r in built["consolidate"])
    assert any("Mauve" in r for r in built["consolidate"])
    early = policy.stores(events, turns, _day(3))
    assert early["consolidate"] and "Teal" in early["consolidate"][0]


def test_bm25_is_deterministic_and_ranks_the_matching_record_first() -> None:
    records = ["Quinn likes tea.", "Zed's home city is Teal.", "Zed's dog is Rex."]
    assert policy.bm25(records, "What is Zed's home city?", k=1) == ["Zed's home city is Teal."]
    assert policy.bm25(records, "nothing matches", k=2) == records[:2]
