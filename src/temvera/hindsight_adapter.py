"""Hindsight adapter for the external-comparison harness.

Hindsight runs a local daemon backed by an embedded PostgreSQL, so no Docker or
manual server setup is needed; ``hindsight-embed daemon start`` brings it up and
this adapter talks to its HTTP API directly rather than spawning the CLI per
operation.

It is the second system after Cognee whose store can be read two ways, which is
what makes it valuable here: ``recall`` returns retrieved memories, the layer
every other system is scored at, while ``reflect`` has an LLM answer over the
same store. Running both tests whether the retrieval-versus-reader separation we
measured on Cognee is a property of that system or of the design class.

Its recall payload also carries explicit validity intervals, so a system that
surfaces temporal metadata at retrieval time is represented in the comparison.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .nl_workload import NLQueryCase, WorkloadTurn
from .worker_errors import check_fatal


class HindsightUnavailable(RuntimeError):
    """Raised when the local daemon is not reachable."""


class HindsightSystem:
    """Hindsight behind its local daemon's HTTP API."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8888",
        bank: str = "temvera",
        search_limit: int = 5,
        read_mode: str = "recall",
        budget: str = "mid",
        timeout: float = 180.0,
    ) -> None:
        if read_mode not in {"recall", "reflect"}:
            raise ValueError("read_mode must be 'recall' or 'reflect'")
        self._base = base_url.rstrip("/")
        self._bank = bank
        self._limit = search_limit
        self._read_mode = read_mode
        # Hindsight's retrieval budget is qualitative ("low"/"mid"/"high"), not
        # a top-k, so it cannot be set to the k used for the other systems. Its
        # scores are therefore not directly comparable on the budget axis.
        if budget not in {"low", "mid", "high"}:
            raise ValueError("budget must be low, mid or high")
        self._budget = budget
        self._timeout = timeout
        self._errors: list[str] = []

    @property
    def read_mode(self) -> str:
        return self._read_mode

    @property
    def budget(self) -> str:
        return self._budget

    @property
    def worker_errors(self) -> int:
        return len(self._errors)

    @property
    def error_messages(self) -> list[str]:
        return list(self._errors)

    def _record(self, message: str) -> None:
        # The daemon reports an upstream LLM failure as a server error whose
        # body names the cause; a revoked key there must stop the run, not
        # turn every answer into an empty one.
        check_fatal(message)
        self._errors.append(message)

    @property
    def version(self) -> str:
        try:
            from importlib.metadata import version

            return version("hindsight-api")
        except Exception:
            return "unknown"

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base}/v1/default/banks/{self._bank}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:500]
            self._record(f"{path}: HTTP {error.code}: {body}")
            return {}
        except urllib.error.URLError as error:
            raise HindsightUnavailable(f"{self._base}: {error.reason}") from error

    def _delete(self, path: str) -> None:
        request = urllib.request.Request(
            f"{self._base}/v1/default/banks/{self._bank}{path}", method="DELETE"
        )
        try:
            urllib.request.urlopen(request, timeout=self._timeout).close()
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:500]
            self._record(f"DELETE {path}: HTTP {error.code}: {body}")
        except urllib.error.URLError as error:
            raise HindsightUnavailable(f"{self._base}: {error.reason}") from error

    def _get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base}/v1/default/banks/{self._bank}{path}", method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:500]
            self._record(f"GET {path}: HTTP {error.code}: {body}")
            return {}
        except urllib.error.URLError as error:
            raise HindsightUnavailable(f"{self._base}: {error.reason}") from error

    def delete_documents_matching(self, needles: list[str]) -> int:
        """Delete every ingested document whose text contains a needle.

        A document is one retained input; it is the finest unit Hindsight's API
        can delete, short of the whole bank.
        """
        folded = [n.casefold() for n in needles]
        listed = self._get("/documents?limit=1000").get("items", [])
        doomed = []
        for item in listed:
            text = str(self._get(f"/documents/{item['id']}").get("original_text", ""))
            if any(n in text.casefold() for n in folded):
                doomed.append(item["id"])
        for document_id in doomed:
            self._delete(f"/documents/{document_id}")
        return len(doomed)

    def delete_documents_for_query(self, query: str, must_mention: str | None = None) -> int:
        """Delete the documents behind the memories a recall returns."""
        response = self._post(
            "/memories/recall", {"query": query, "budget": self._budget}
        )
        items = response.get("results") or response.get("memories") or []
        doomed = sorted({str(item["document_id"]) for item in items[: self._limit]
                         if isinstance(item, dict) and item.get("document_id")
                         and (must_mention is None
                              or must_mention.casefold() in str(item.get("text", "")).casefold())})
        for document_id in doomed:
            self._delete(f"/documents/{document_id}")
        return len(doomed)

    def reset(self) -> None:
        """Drop the bank so each cell starts from an empty store."""
        self._delete("")

    def ingest(self, turn: WorkloadTurn) -> None:
        self._post(
            "/memories",
            {"items": [{"content": turn.text}], "async": False},
        )

    def _flatten(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(self._flatten(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return " ".join(self._flatten(v) for v in value)
        return str(value)

    def answer(self, case: NLQueryCase) -> str:
        if self._read_mode == "reflect":
            response = self._post("/reflect", {"query": case.query_text})
            for key in ("answer", "response", "text", "content"):
                if isinstance(response.get(key), str):
                    return response[key]
            return self._flatten(response)
        response = self._post(
            "/memories/recall", {"query": case.query_text, "budget": self._budget}
        )
        items = response.get("memories") or response.get("results") or response
        parts = [self._flatten(item) for item in items] if isinstance(items, list) else [
            self._flatten(items)
        ]
        return " | ".join(part for part in parts[: self._limit] if part)

    def close(self) -> None:  # symmetry with the stdio-backed adapters
        return None
