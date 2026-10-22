"""Out-of-process Cognee worker driven over stdio.

Cognee requires `openai>=2`, which conflicts with the `openai==1.x` pinned by
the Mem0 and Graphiti versions under test, so it runs in its own virtualenv
behind this worker — the same arrangement used for LangMem.

Cognee is a two-phase design: `add()` stages text, `cognify()` builds the
knowledge graph over everything staged. Under forward-checkpoint replay we stage
each turn as it arrives and cognify once per checkpoint, immediately before the
queries at that transaction time, so the graph reflects exactly what was known
then. `cognify()` is the expensive step, which is why it is batched per
checkpoint rather than per turn.

Protocol: one JSON object per line on stdin, one per line on stdout.

    {"op": "reset"}                  -> {"ok": true}
    {"op": "ingest", "text": "..."}  -> {"ok": true}
    {"op": "answer", "query": "..."} -> {"ok": true, "answer": "..."}

Deletion study (H10), through Cognee's documented `forget`:

    {"op": "delete_matching", "needles": [...]} -> {"ok": true, "deleted": n}
    {"op": "delete_for_query", "query": "..."}  -> {"ok": true, "deleted": n}
    {"op": "scan", "needles": [...]}            -> {"ok": true, "stores": {...}}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Cognee logs to stdout, which would corrupt the line protocol. Duplicate the
# real stdout to a private channel for protocol writes, then point sys.stdout at
# stderr so any library output is discarded by the parent rather than parsed.
_PROTOCOL = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
sys.stdout = sys.stderr


def _send(payload: dict) -> None:
    _PROTOCOL.write(json.dumps(payload) + "\n")
    _PROTOCOL.flush()


class _Worker:
    def __init__(self, limit: int, search_type: str = "GRAPH_COMPLETION") -> None:
        self._limit = limit
        # GRAPH_COMPLETION (Cognee's default) has an LLM synthesise an answer
        # over the graph, so it is scored on generated text. CHUNKS returns the
        # retrieved passages, which is the layer the other systems are scored
        # at. Both are reported; they measure different things.
        self._search_type = search_type
        self._loop = asyncio.new_event_loop()
        self._pending = 0

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def reset(self) -> None:
        import cognee

        async def _prune():
            await cognee.prune.prune_data()
            await cognee.prune.prune_system(metadata=True)

        self._run(_prune())
        self._pending = 0

    def ingest(self, text: str) -> None:
        import cognee

        self._run(cognee.add(text))
        self._pending += 1

    def _flatten(self, value) -> str:
        if isinstance(value, dict):
            # Cognee wraps hits in dataset envelopes; the payload is the part
            # that can contain a stored value.
            if "search_result" in value:
                return self._flatten(value["search_result"])
            return " ".join(self._flatten(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return " ".join(self._flatten(v) for v in value)
        return str(value)

    def answer(self, query: str) -> str:
        import cognee

        if self._pending:
            self._run(cognee.cognify())
            self._pending = 0
        from cognee.modules.search.types import SearchType

        results = self._run(
            cognee.search(
                query_text=query, query_type=SearchType[self._search_type]
            )
        )
        flattened = [self._flatten(item) for item in (results or [])]
        return " | ".join(part for part in flattened[: self._limit] if part)


    def _flush(self) -> None:
        import cognee

        if self._pending:
            self._run(cognee.cognify())
            self._pending = 0

    def _items(self):
        import cognee

        async def _list():
            out = []
            for dataset in await cognee.datasets.list_datasets():
                for data in await cognee.datasets.list_data(dataset.id):
                    out.append((dataset.id, data))
            return out

        return self._run(_list())

    def delete_matching(self, needles: list[str]) -> int:
        """`forget` every ingested item whose stored text contains a needle."""
        import cognee

        self._flush()
        folded = [n.casefold() for n in needles]
        doomed = []
        for dataset_id, data in self._items():
            path = str(data.raw_data_location).removeprefix("file://")
            try:
                text = open(path, encoding="utf-8", errors="replace").read().casefold()
            except OSError:
                continue
            if any(n in text for n in folded):
                doomed.append((dataset_id, data.id))
        for dataset_id, data_id in doomed:
            self._run(cognee.forget(data_id=data_id, dataset_id=dataset_id))
        return len(doomed)

    def delete_for_query(self, query: str) -> int:
        """`forget` the items behind the chunks a query returns."""
        import uuid

        import cognee
        from cognee.modules.search.types import SearchType

        self._flush()
        results = self._run(
            cognee.search(query_text=query, query_type=SearchType.CHUNKS)
        ) or []
        doomed = set()
        for envelope in results:
            hits = envelope.get("search_result", []) if isinstance(envelope, dict) else []
            for hit in hits[: self._limit]:
                if isinstance(hit, dict) and hit.get("document_id"):
                    doomed.add((envelope.get("dataset_id"), hit["document_id"]))
        for dataset_id, document_id in sorted(doomed):
            self._run(cognee.forget(data_id=uuid.UUID(str(document_id)),
                                    dataset_id=uuid.UUID(str(dataset_id))))
        return len(doomed)

    def scan(self, needles: list[str], system_root: str, data_root: str) -> dict:
        """Count needles in every store, each read through its own library."""
        import glob
        import sqlite3

        self._flush()
        folded = [n.casefold() for n in needles]

        def count(text: str) -> int:
            text = text.casefold()
            return sum(text.count(n) for n in folded)

        stores = {"cognee_vector_store": 0, "cognee_graph_store": 0,
                  "cognee_relational_db": 0, "cognee_cache_db": 0,
                  "cognee_raw_inputs": 0}
        import lancedb

        for path in glob.glob(f"{system_root}/databases/**/*.lance.db", recursive=True):
            db = lancedb.connect(path)
            for name in db.table_names():
                rows = db.open_table(name).to_arrow().to_pylist()
                stores["cognee_vector_store"] += count(json.dumps(
                    [{k: v for k, v in r.items() if k != "vector"} for r in rows],
                    default=str))
        import ladybug

        for path in glob.glob(f"{system_root}/databases/**/*.lbug", recursive=True):
            conn = ladybug.Connection(ladybug.Database(path, read_only=True))
            for query in ("MATCH (n) RETURN n", "MATCH ()-[e]->() RETURN e"):
                result = conn.execute(query)
                while result.has_next():
                    stores["cognee_graph_store"] += count(
                        json.dumps(result.get_next(), default=str))
        for name, key in (("cognee_db", "cognee_relational_db"),
                          ("cache.db", "cognee_cache_db")):
            for path in glob.glob(f"{system_root}/databases/**/{name}", recursive=True):
                connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    tables = [r[0] for r in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")]
                    for table in tables:
                        for row in connection.execute(f'SELECT * FROM "{table}"'):
                            stores[key] += count(json.dumps(row, default=str))
                finally:
                    connection.close()
        for path in glob.glob(f"{data_root}/**/*", recursive=True):
            if os.path.isfile(path):
                stores["cognee_raw_inputs"] += count(
                    open(path, encoding="utf-8", errors="replace").read())
        return stores


def _set_roots(system_root: str, data_root: str) -> str:
    # Cognee 1.4.2 reads SYSTEM_ROOT_DIRECTORY, not a COGNEE_-prefixed name, and
    # otherwise keeps its metadata database inside the installed package, where
    # every run on the machine shares it. Concurrent runs corrupted that file
    # ("database disk image is malformed"). Setting the roots through the API
    # also re-derives the relational, graph and vector paths from them.
    import cognee
    from cognee.base_config import get_base_config

    if system_root:
        cognee.config.system_root_directory(system_root)
    if data_root:
        cognee.config.data_root_directory(data_root)
    return get_base_config().system_root_directory


def main() -> int:
    config = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    root = _set_roots(
        str(config.get("system_root", "")), str(config.get("data_root", ""))
    )
    worker = _Worker(
        int(config.get("search_limit", 5)),
        str(config.get("search_type", "GRAPH_COMPLETION")),
    )
    _send({"ok": True, "ready": True, "system_root": root})
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
            elif op == "delete_matching":
                response = {"ok": True,
                            "deleted": worker.delete_matching(request["needles"])}
            elif op == "delete_for_query":
                response = {"ok": True,
                            "deleted": worker.delete_for_query(request["query"])}
            elif op == "scan":
                response = {"ok": True, "stores": worker.scan(
                    request["needles"], str(config.get("system_root", "")),
                    str(config.get("data_root", "")))}
            elif op == "stop":
                _send({"ok": True})
                return 0
            else:
                response = {"ok": False, "error": f"unknown op: {op}"}
        except Exception as error:
            response = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        _send(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
