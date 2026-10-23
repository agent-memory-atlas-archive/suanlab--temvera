"""Out-of-process LangMem worker driven over stdio.

LangMem pulls `openai>=3`, which is incompatible with the `openai==1.x` that the
pinned Mem0 and Graphiti versions require. Installing it into the main
environment would invalidate the sealed runs, so it lives in its own virtualenv
and the adapter talks to this worker instead.

Protocol: one JSON object per line on stdin, one per line on stdout.

    {"op": "reset"}                  -> {"ok": true}
    {"op": "ingest", "text": "..."}  -> {"ok": true}
    {"op": "answer", "query": "..."} -> {"ok": true, "answer": "..."}
    {"op": "dump"}                   -> {"ok": true, "memories": [...]}

Deletion study (H10), all through the store's own API:

    {"op": "delete_matching", "needles": [...]} -> {"ok": true, "deleted": n}
    {"op": "delete_for_query", "query": "..."}  -> {"ok": true, "deleted": n}
    {"op": "scan", "needles": [...]}            -> {"ok": true, "stores": {...}}
"""

from __future__ import annotations

import json
import sys


class _Worker:
    def __init__(self, model: str, embed_model: str, limit: int,
                 enable_deletes: bool = False) -> None:
        self._model = model
        self._embed_model = embed_model
        self._limit = limit
        # LangMem's default is False; the deletion study also runs it True.
        self._enable_deletes = enable_deletes
        self._namespace = ("memories", "agent")
        self._store = None
        self._manager = None
        self.reset()

    def reset(self) -> None:
        from langgraph.store.memory import InMemoryStore
        from langmem import create_memory_store_manager

        self._store = InMemoryStore(
            index={"dims": 1536, "embed": f"openai:{self._embed_model}"}
        )
        self._manager = create_memory_store_manager(
            f"openai:{self._model}", namespace=self._namespace, store=self._store,
            enable_deletes=self._enable_deletes,
        )

    def ingest(self, text: str) -> None:
        self._manager.invoke({"messages": [{"role": "user", "content": text}]})

    def _flatten(self, value) -> str:
        if isinstance(value, dict):
            return " ".join(self._flatten(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return " ".join(self._flatten(v) for v in value)
        return str(value)

    def answer(self, query: str) -> str:
        hits = self._store.search(self._namespace, query=query, limit=self._limit)
        return " | ".join(self._flatten(hit.value) for hit in hits)

    def dump(self) -> list[str]:
        hits = self._store.search(self._namespace, query="", limit=1000)
        return [self._flatten(hit.value) for hit in hits]

    def delete_matching(self, needles: list[str]) -> int:
        """Delete every memory whose text contains a needle (the oracle caller)."""
        folded = [n.casefold() for n in needles]
        hits = self._store.search(self._namespace, query="", limit=1000)
        doomed = [h.key for h in hits
                  if any(n in self._flatten(h.value).casefold() for n in folded)]
        for key in doomed:
            self._store.delete(self._namespace, key)
        return len(doomed)

    def delete_for_query(self, query: str, must_mention: str | None = None) -> int:
        """Delete what a query returns (only what names ``must_mention``, if given)."""
        hits = self._store.search(self._namespace, query=query, limit=self._limit)
        doomed = [h.key for h in hits if must_mention is None
                  or must_mention.casefold() in self._flatten(h.value).casefold()]
        for key in doomed:
            self._store.delete(self._namespace, key)
        return len(doomed)

    def scan(self, needles: list[str]) -> dict[str, int]:
        # The in-memory store is LangMem's only store, and the one it serves from.
        text = " ".join(self.dump()).casefold()
        return {"langmem_store": sum(text.count(n.casefold()) for n in needles)}


def main() -> int:
    config = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    worker = _Worker(
        config.get("model", "gpt-4o-mini"),
        config.get("embed_model", "text-embedding-3-small"),
        int(config.get("search_limit", 5)),
        bool(config.get("enable_deletes", False)),
    )
    print(json.dumps({"ok": True, "ready": True}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "reset":
                worker.reset()
                response = {"ok": True}
            elif op == "ingest":
                worker.ingest(request["text"])
                response = {"ok": True}
            elif op == "answer":
                response = {"ok": True, "answer": worker.answer(request["query"])}
            elif op == "dump":
                response = {"ok": True, "memories": worker.dump()}
            elif op == "delete_matching":
                response = {"ok": True,
                            "deleted": worker.delete_matching(request["needles"])}
            elif op == "delete_for_query":
                response = {"ok": True,
                            "deleted": worker.delete_for_query(
                                request["query"], request.get("must_mention"))}
            elif op == "scan":
                response = {"ok": True, "stores": worker.scan(request["needles"])}
            elif op == "stop":
                print(json.dumps({"ok": True}), flush=True)
                return 0
            else:
                response = {"ok": False, "error": f"unknown op: {op}"}
        except Exception as error:  # report, never die mid-run
            response = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
