"""The scale workload must vary scale and nothing else.

A 2026-10 sweep found the standard relabelling falling back to synthetic tokens
("Person-102", "employer-95") at a rate that grew with entity count, and values
shared across subjects at a rate that also grew with it -- two confounds riding
on the variable under study. These tests hold the fixes in place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from temvera.external_experiment import _events_for
from temvera.generator import generate_histories
from temvera.nl_workload import _large_pools, fallback_tokens, naturalize_events

_PROFILE = {"reconfirm_probability": 0.5, "expire_probability": 0.35, "purge_probability": 0.25}
_KW = dict(seed=17, entities=8, revisions=4, attributes=3, **_PROFILE)


def _shape(events):
    return [(e.event_id, e.operation, e.valid_from, e.recorded_at, e.belief_id, e.target_id)
            for e in events]


def test_distinct_values_keeps_the_history_shape() -> None:
    """Same dates, operations and beliefs: only value identity changes."""
    assert _shape(generate_histories(**_KW)) == _shape(
        generate_histories(**_KW, distinct_values=True))


def test_distinct_values_never_repeats_a_value() -> None:
    values = [e.value for e in generate_histories(**_KW, distinct_values=True) if e.value]
    assert len(values) == len(set(values))


def test_default_mode_is_unchanged() -> None:
    """Sealed runs depend on it; this pins one value from a known seed."""
    first = next(e.value for e in generate_histories(**_KW) if e.value)
    again = next(e.value for e in generate_histories(**_KW) if e.value)
    assert first == again and not first.split("-")[-1].startswith("u")


def test_no_large_pool_entry_is_a_substring_of_another() -> None:
    """The scorer matches by substring, so containment would be a false hit."""
    persons, pools = _large_pools()
    entries = [x.casefold() for x in persons]
    for pool in pools.values():
        entries += [x.casefold() for x in pool]
    assert len(entries) == len(set(entries))
    every = set(entries)
    for entry in entries:  # check each entry's own substrings, not every pair
        size = len(entry)
        inner = {entry[i:j] for i in range(size) for j in range(i + 1, size)}
        clash = inner & every
        assert not clash, f"{sorted(clash)[0]!r} is inside {entry!r}"


@pytest.mark.parametrize("entities", [8, 32, 128])
def test_large_pools_leave_no_synthetic_tokens(entities: int) -> None:
    events = _events_for(17, entities, 4, _PROFILE, True, 3,
                         distinct_values=True, pools="large")
    counts = fallback_tokens(events)
    assert counts["names"] == 0 and counts["values"] == 0


def test_large_pools_refuse_to_fall_back() -> None:
    events = generate_histories(seed=3, entities=4, revisions=2, attributes=1)
    big = tuple(e for e in events)
    # exhaust a pool deliberately by relabelling more subjects than names exist
    many = generate_histories(seed=3, entities=len(_large_pools()[0]) + 1, revisions=1)
    with pytest.raises(ValueError, match="refusing to fall back"):
        naturalize_events(many, pools="large")
    assert naturalize_events(big, pools="large")


def test_standard_pools_still_report_their_fallbacks() -> None:
    events = _events_for(17, 128, 4, _PROFILE, True, 3)
    counts = fallback_tokens(events)
    assert counts["names"] > 0 and counts["values"] > 0


def test_sweep_v2_configs_use_the_controlled_workload() -> None:
    for path in Path("experiments/configs").glob("scale-sweep-*-v2.json"):
        config = json.loads(path.read_text())
        assert config["distinct_values"] is True, path
        assert config["natural_pools"] == "large", path
