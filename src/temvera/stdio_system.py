"""Base for memory systems that must run in a separate interpreter.

Two of the systems under test cannot share our environment: LangMem requires
``openai>=3`` and Cognee ``openai>=2``, while the pinned Mem0 and Graphiti
versions require ``openai==1.x``. Installing either into the main environment
would change the dependency set the sealed runs were produced under, so each
runs in its own virtualenv behind a stdio worker and this class speaks JSON
lines to it.

Worker failures are counted and exposed rather than swallowed: a silent drop is
exactly the defect we report in one of the systems we measure, so the harness
must not commit the same one.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .nl_workload import NLQueryCase, WorkloadTurn
from .worker_errors import check_fatal, redact


class WorkerUnavailable(RuntimeError):
    """Raised when no isolated interpreter is configured or the worker dies."""


class StdioSystem:
    """A memory system driven through a worker in another interpreter."""

    #: Environment variable naming the interpreter for this system.
    interpreter_env: str = ""
    #: Worker script, relative to the repository root.
    worker_script: str = ""
    #: Distribution whose version identifies the system under test.
    distribution: str = ""

    def __init__(
        self,
        *,
        search_limit: int = 5,
        python: str | None = None,
        worker: str | None = None,
        extra_config: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        interpreter = python or os.environ.get(self.interpreter_env)
        if not interpreter or not Path(interpreter).exists():
            raise WorkerUnavailable(
                f"set {self.interpreter_env} to a virtualenv interpreter with "
                f"{self.distribution} installed"
            )
        self._interpreter = interpreter
        self._worker = worker or str(
            Path(__file__).resolve().parents[2] / self.worker_script
        )
        self._config: dict[str, Any] = {"search_limit": search_limit}
        self._config.update(extra_config or {})
        self._env = {**os.environ, **(env or {})}
        self._process: subprocess.Popen | None = None
        self._stderr: Any = None
        self._errors: list[str] = []

    @property
    def version(self) -> str:
        result = subprocess.run(
            [
                self._interpreter,
                "-c",
                "from importlib.metadata import version;"
                f"print(version('{self.distribution}'))",
            ],
            capture_output=True,
            text=True,
            env=self._env,
        )
        return result.stdout.strip() or "unknown"

    @property
    def worker_errors(self) -> int:
        return len(self._errors)

    @property
    def error_messages(self) -> list[str]:
        return list(self._errors)

    def _start(self) -> None:
        # Kept, not discarded, so a worker that dies can say why.
        self._stderr = tempfile.TemporaryFile("w+b")
        self._process = subprocess.Popen(
            [self._interpreter, self._worker, json.dumps(self._config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
            env=self._env,
        )
        handshake = self._read()
        if not handshake.get("ready"):
            raise WorkerUnavailable(f"{self.distribution} worker failed to start")
        self._check_handshake(handshake)

    def _check_handshake(self, handshake: dict[str, Any]) -> None:
        return None

    def _read(self) -> dict[str, Any]:
        assert self._process is not None and self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            raise WorkerUnavailable(
                f"{self.distribution} worker exited unexpectedly; stderr tail:\n"
                + self._stderr_tail()
            )
        return json.loads(line)

    def _stderr_tail(self, size: int = 4000) -> str:
        if self._stderr is None:
            return ""
        self._stderr.seek(0, os.SEEK_END)
        self._stderr.seek(max(0, self._stderr.tell() - size))
        return redact(self._stderr.read().decode(errors="replace"))

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
        self._call({"op": "reset"})

    def ingest(self, turn: WorkloadTurn) -> None:
        self._call({"op": "ingest", "text": turn.text})

    def answer(self, case: NLQueryCase) -> str:
        response = self._call({"op": "answer", "query": case.query_text})
        return str(response.get("answer", ""))

    def close(self) -> None:
        if self._process is not None:
            try:
                self._call({"op": "stop"})
                self._process.wait(timeout=15)
            except Exception:
                self._process.kill()
            self._process = None
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None


class CogneeSystem(StdioSystem):
    """Cognee: stages text with ``add``, builds a graph with ``cognify``.

    Cognee stores locally (SQLite plus an embedded vector and graph store), so
    unlike Graphiti it needs no database server. It is a third design point: a
    knowledge-graph pipeline with an explicit build step, rather than
    extract-on-write like Mem0 and LangMem or episode-ingest like Graphiti.
    """

    interpreter_env = "COGNEE_PYTHON"
    worker_script = "scripts/cognee_worker.py"
    distribution = "cognee"

    def _check_handshake(self, handshake: dict[str, Any]) -> None:
        # A store root that silently falls back to the shared default is how
        # concurrent runs once wrote into one database; refuse to start instead.
        wanted = self._config.get("system_root")
        if wanted and handshake.get("system_root") != wanted:
            raise WorkerUnavailable(
                f"cognee store root is {handshake.get('system_root')!r}, "
                f"not the requested {wanted!r}"
            )
