"""Text-only Mem0 adapter for the external-comparison harness (E1).

Wraps the Mem0 OSS ``Memory`` store behind the harness ``MemorySystem``
contract so it is scored against the same bitemporal truth as the internal
oracle. Mem0 performs LLM-based extraction and consolidation on ingest, so it
answers from a single current-state view and has no transaction-time ``as-of``
concept — the divergence this experiment measures (E-025).

The ``mem0`` dependency is imported lazily; only the E1 runner needs it. LLM
backbone, embedder, and Mem0 version are recorded in the sealed run config for
reproducibility (D-010).
"""

from __future__ import annotations

import os

# Third-party usage telemetry is off by default for research runs. Mem0 and
# Graphiti both ship PostHog clients; Mem0 builds one per Memory instance and
# flushes them all at interpreter exit, which held a 32-entity scale probe open
# for 2 h 13 min after its results were sealed. They also send events to a third
# party mid-experiment. Both libraries read these variables at import time, so
# they are set here, before either is imported; an explicit setting wins.
os.environ.setdefault("MEM0_TELEMETRY", "False")

from typing import Any

from .nl_workload import NLQueryCase, WorkloadTurn


def default_mem0_config(
    *,
    model: str = "gpt-4o-mini",
    embed_model: str = "text-embedding-3-small",
    history_db_path: str | None = None,
    vector_path: str | None = None,
) -> dict[str, Any]:
    """Mem0 config pinned to the shared backbone.

    ``history_db_path`` isolates the SQLite history database per run; the
    default `~/.mem0/history.db` is global and would mix rows across runs,
    which matters for the purge residual scan (E3).

    ``vector_path`` isolates the vector store, and defaults to a fresh
    directory per call. Mem0 0.1.118's default is a local Qdrant at the fixed
    path ``/tmp/qdrant``, and with ``on_disk`` false it ``rmtree``s that path
    every time a ``Memory`` is constructed. Two Mem0 processes at once -- or one
    process and anything that builds a ``Memory``, including this adapter's
    ``version`` property -- therefore delete each other's stores mid-run,
    silently. An audit of the session record (2026-10-02) found every accepted
    Mem0 run executed alone; the two overlaps it found hit runs already
    discarded or superseded. This closes the channel rather than relying on it.
    """
    import tempfile
    config: dict[str, Any] = {
        "llm": {
            "provider": "openai",
            "config": {"model": model, "temperature": 0.0},
        },
        "embedder": {
            "provider": "openai",
            "config": {"model": embed_model},
        },
    }
    if history_db_path:
        config["history_db_path"] = history_db_path
    config["vector_store"] = {
        "provider": "qdrant",
        "config": {
            "path": vector_path or tempfile.mkdtemp(prefix="mem0-qdrant-"),
            "collection_name": "mem0",
            "on_disk": False,
        },
    }
    return config


class Mem0System:
    """Mem0 OSS store as a harness-compatible memory system."""

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        user_id: str = "temvera-e1",
        search_limit: int = 5,
    ) -> None:
        from mem0 import Memory

        self._config = config or default_mem0_config()
        self._user_id = user_id
        self._search_limit = search_limit
        self._memory = Memory.from_config(self._config)
        self.last_added: list[dict[str, Any]] = []

    @property
    def version(self) -> str:
        import mem0

        return getattr(mem0, "__version__", "unknown")

    def reset(self) -> None:
        try:
            self._memory.delete_all(user_id=self._user_id)
        except Exception:
            # A fresh store has nothing to delete; ignore.
            pass

    def ingest(self, turn: WorkloadTurn) -> None:
        self._memory.add(turn.text, user_id=self._user_id)

    def delete_memories_mentioning(self, needle: str) -> int:
        """Call Mem0's native `delete` for memories containing `needle`.

        Feeding a natural-language "delete" sentence tests whether extraction
        infers deletion intent; this exercises the documented deletion API.
        """
        result = self._memory.get_all(user_id=self._user_id)
        rows = result.get("results", result) if isinstance(result, dict) else result
        removed = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if needle.casefold() in str(row.get("memory", "")).casefold():
                try:
                    self._memory.delete(memory_id=row["id"])
                    removed += 1
                except Exception:
                    pass
        return removed

    def answer(self, case: NLQueryCase) -> str:
        result = self._memory.search(
            case.query_text, user_id=self._user_id, limit=self._search_limit
        )
        rows = result.get("results", result) if isinstance(result, dict) else result
        memories = [
            str(row.get("memory", "")) for row in rows if isinstance(row, dict)
        ]
        return " | ".join(memory for memory in memories if memory)
