"""Mem0 runs must not share a vector store path.

Mem0 0.1.118 defaults to a local Qdrant at /tmp/qdrant and deletes that
directory whenever a Memory is constructed, so a shared path lets one process
wipe another's store mid-run without any error. Each config gets its own.
"""

from __future__ import annotations

from temvera.mem0_adapter import default_mem0_config


def test_each_config_gets_its_own_vector_store_path() -> None:
    first = default_mem0_config()["vector_store"]["config"]["path"]
    second = default_mem0_config()["vector_store"]["config"]["path"]
    assert first != second


def test_the_shared_default_path_is_never_used() -> None:
    assert default_mem0_config()["vector_store"]["config"]["path"] != "/tmp/qdrant"


def test_an_explicit_path_is_respected() -> None:
    config = default_mem0_config(vector_path="/tmp/example-store")
    assert config["vector_store"]["config"]["path"] == "/tmp/example-store"


def test_third_party_telemetry_is_off_unless_asked_for() -> None:
    """Mem0 and Graphiti PostHog clients are disabled for research runs."""
    import os

    import temvera.graphiti_adapter  # noqa: F401
    import temvera.mem0_adapter  # noqa: F401

    assert os.environ["MEM0_TELEMETRY"].lower() in ("false", "0", "no")
    assert os.environ["GRAPHITI_TELEMETRY_ENABLED"].lower() in ("false", "0", "no")


def test_mem0_events_start_no_threads_when_telemetry_is_off() -> None:
    """mem0 built a PostHog client -- and a thread that never stopped -- per call."""
    import threading

    import pytest

    pytest.importorskip("mem0")
    from temvera.mem0_adapter import _silence_mem0_telemetry

    _silence_mem0_telemetry()
    import mem0.memory.main as main

    before = threading.active_count()
    for _ in range(5):
        main.capture_event("mem0.add", object())
    assert threading.active_count() == before


def test_transient_failures_are_retried_and_counted() -> None:
    from temvera.mem0_adapter import _with_retries

    class APIConnectionError(Exception):
        pass

    calls, seen = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise APIConnectionError("ssl eof")
        return "ok"

    assert _with_retries(flaky, sleep=lambda s: None, on_retry=seen.append) == "ok"
    assert len(calls) == 3 and len(seen) == 2


def test_non_transient_failures_are_not_retried() -> None:
    import pytest

    from temvera.mem0_adapter import _with_retries

    calls = []

    def broken():
        calls.append(1)
        raise ValueError("a bug, not the network")

    with pytest.raises(ValueError):
        _with_retries(broken, sleep=lambda s: None)
    assert len(calls) == 1
