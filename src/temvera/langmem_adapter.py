"""LangMem adapter for the external-comparison harness.

LangMem requires ``openai>=3``, which conflicts with the ``openai==1.x`` pinned
by the Mem0 and Graphiti versions under test. Rather than change the sealed
environment, the library runs in its own virtualenv behind
``scripts/langmem_worker.py`` and this adapter speaks JSON lines to it.

Point ``LANGMEM_PYTHON`` at that interpreter. LangMem is a third contrasting
design: like Mem0 it extracts memories with an LLM on write, but it stores them
in a LangGraph store with vector search and needs no database server.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .nl_workload import NLQueryCase, WorkloadTurn
from .worker_errors import check_fatal


class LangMemUnavailable(RuntimeError):
    """Raised when no isolated LangMem interpreter is configured."""


class LangMemSystem:
    """LangMem behind a stdio worker, satisfying the MemorySystem contract."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        embed_model: str = "text-embedding-3-small",
        search_limit: int = 5,
        python: str | None = None,
        worker: str | None = None,
        enable_deletes: bool = False,
    ) -> None:
        interpreter = python or os.environ.get("LANGMEM_PYTHON")
        if not interpreter or not Path(interpreter).exists():
            raise LangMemUnavailable(
                "set LANGMEM_PYTHON to a virtualenv interpreter with langmem installed"
            )
        self._interpreter = interpreter
        self._worker = worker or str(
            Path(__file__).resolve().parents[2] / "scripts" / "langmem_worker.py"
        )
        self._config = {
            "model": model,
            "embed_model": embed_model,
            "search_limit": search_limit,
            "enable_deletes": enable_deletes,
        }
        self._process: subprocess.Popen | None = None
        self._errors: list[str] = []

    @property
    def version(self) -> str:
        result = subprocess.run(
            [
                self._interpreter,
                "-c",
                "from importlib.metadata import version; print(version('langmem'))",
            ],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"

    @property
    def worker_errors(self) -> int:
        """Requests the worker reported as failed; surfaced, never swallowed."""
        return len(self._errors)

    @property
    def error_messages(self) -> list[str]:
        return list(self._errors)

    def _start(self) -> None:
        self._process = subprocess.Popen(
            [self._interpreter, self._worker, json.dumps(self._config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        handshake = self._read()
        if not handshake.get("ready"):
            raise LangMemUnavailable(f"worker failed to start: {handshake}")

    def _read(self) -> dict[str, Any]:
        assert self._process is not None and self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            raise LangMemUnavailable("langmem worker exited unexpectedly")
        return json.loads(line)

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        if self._process is None:
            self._start()
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(json.dumps(request) + "\n")
        self._process.stdin.flush()
        response = self._read()
        if not response.get("ok"):
            message = str(response.get("error", "unknown"))
            check_fatal(message)
            self._errors.append(message)
        return response

    def reset(self) -> None:
        if self._process is None:
            self._start()
        else:
            self._call({"op": "reset"})

    def ingest(self, turn: WorkloadTurn) -> None:
        self._call({"op": "ingest", "text": turn.text})

    def answer(self, case: NLQueryCase) -> str:
        return str(self._call({"op": "answer", "query": case.query_text}).get("answer", ""))

    def memories(self) -> list[str]:
        return list(self._call({"op": "dump"}).get("memories", []))

    def close(self) -> None:
        if self._process is not None:
            try:
                self._call({"op": "stop"})
                self._process.wait(timeout=10)
            except Exception:
                self._process.kill()
            self._process = None
