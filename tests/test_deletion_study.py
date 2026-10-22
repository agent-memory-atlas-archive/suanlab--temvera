"""The deletion study's bookkeeping, without running any memory system."""

from __future__ import annotations

from temvera.deletion_study import reachable, subjects, summarize
from temvera.external_experiment import _events_for
from temvera.nl_workload import PURGE_WORDINGS, render_turns

PROFILE = {"name": "p", "purge_probability": 0.5, "expire_probability": 0.0,
           "reconfirm_probability": 0.0}


def _events(seed: int):
    return _events_for(seed, 6, 2, PROFILE, True, 1, True, "standard")


def test_purged_and_kept_values_never_coincide() -> None:
    # A value shared by a purged and a kept person would read as a leak.
    for seed in (7, 13, 17, 23, 42, 1, 2, 3, 4, 5):
        people = subjects(_events(seed))
        gone = {v for p in people if p.purged for v in p.values}
        kept = {v for p in people if not p.purged for v in p.values}
        assert not gone & kept


def test_the_preregistered_workload_has_24_purged_and_36_kept() -> None:
    people = [p for seed in (7, 13, 17, 23, 42, 1, 2, 3, 4, 5) for p in subjects(_events(seed))]
    assert sum(p.purged for p in people) == 24
    assert sum(not p.purged for p in people) == 36


def test_no_wording_restates_the_value() -> None:
    events = _events(7)
    values = {v for p in subjects(events) for v in p.values}
    for wording in range(len(PURGE_WORDINGS)):
        for turn in render_turns(events, purge_wording=wording):
            if "delete" in turn.text or "forget" in turn.text or "erased" in turn.text:
                assert not any(v in turn.text for v in values)


def test_default_wording_is_the_sealed_one() -> None:
    texts = [t.text for t in render_turns(_events(17))]
    assert any(t.endswith("Permanently delete everything you recorded about "
                          f"{t.split('about ')[1]}") for t in texts if "delete" in t)


def test_reachability_marks_logs_and_sources_off_the_query_path() -> None:
    assert not reachable("mem0_history_sqlite")
    assert not reachable("cognee_relational_db")
    assert not reachable("hindsight_audit_log")
    assert reachable("hindsight_memory_units")
    assert reachable("langmem_store")


def test_summary_counts_leaks_and_offpath_residue() -> None:
    record = {"system": "x", "condition": "api-oracle", "worker_errors": 0,
              "purged": [{"leaked": True}, {"leaked": False}],
              "kept": [{"present": True}],
              "stores": [{"occurrences": 2, "reachable": False}]}
    entry = summarize([record])["x:api-oracle"]
    assert (entry["purged"], entry["leaked"], entry["offpath_residue_histories"]) == (2, 1, 1)
    assert entry["reachable_residue_histories"] == 0
