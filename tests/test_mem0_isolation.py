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
