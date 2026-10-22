"""E3: cross-system purge residual scan of derived stores.

Answer-level scoring (E-053, E-054) shows whether a system *returns* a purged
value. This module asks the stronger, deletion-completeness question behind
contribution C-B: after a purge is ingested, does the value still physically
reside in each system's derived stores?

For every system the same seeded history is ingested, a purge is applied, and
the backing stores are scanned for the purged literal:

* **Temvera** — raw JSONL ledger, rebuilt Markdown projection, and the lexical /
  vector / graph indexes. The ledger is expected to retain the payload (a known,
  documented limitation, D-005); the projections must not.
* **Mem0** — the memories it still exposes for the user after deletion.
* **Graphiti** — a direct Cypher scan of edge facts, node summaries, and stored
  episode bodies in Neo4j.

A residual is reported as a count per store, never as a pass/fail verdict, so a
tombstone is never mistaken for erasure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .model import MemoryEvent, Operation
from .store import JsonlEventStore


@dataclass(frozen=True, slots=True)
class StoreResidual:
    store: str
    occurrences: int
    detail: str = ""


@dataclass(slots=True)
class SystemResidualReport:
    system: str
    purged_values: tuple[str, ...]
    stores: list[StoreResidual] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(store.occurrences for store in self.stores)

    def as_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "purged_values": list(self.purged_values),
            "total_residual": self.total,
            "stores": [
                {
                    "store": s.store,
                    "occurrences": s.occurrences,
                    "detail": s.detail,
                }
                for s in self.stores
            ],
        }


def purged_values(events: tuple[MemoryEvent, ...]) -> tuple[str, ...]:
    """Values whose belief was purged at some transaction time."""
    ingests = {
        event.belief_id: event
        for event in events
        if event.operation is Operation.INGEST
    }
    values = {
        ingests[event.belief_id].value
        for event in events
        if event.operation is Operation.PURGE and event.belief_id in ingests
    }
    return tuple(sorted(value for value in values if value))


def _count(text: str, needles: tuple[str, ...]) -> int:
    folded = text.casefold()
    return sum(folded.count(needle.casefold()) for needle in needles)


def scan_temvera(
    events: tuple[MemoryEvent, ...],
    root: Path,
    transaction_at: datetime,
    needles: tuple[str, ...] | None = None,
) -> SystemResidualReport:
    """Ingest into a JSONL store, rebuild projections, then scan every store."""
    needles = needles or purged_values(events)
    report = SystemResidualReport(system="temvera", purged_values=needles)
    store = JsonlEventStore(root)
    store.extend(events)
    store.rebuild(transaction_at)
    if not needles:
        return report

    ledger = store.ledger_path
    report.stores.append(
        StoreResidual(
            "raw_ledger_jsonl",
            _count(ledger.read_text(encoding="utf-8"), needles),
            "documented limitation: JSONL tombstones but does not erase (D-005)",
        )
    )
    markdown = sum(
        _count(path.read_text(encoding="utf-8"), needles)
        for path in sorted(store.projection_dir.glob("*.md"))
    )
    report.stores.append(StoreResidual("markdown_projection", markdown))
    for name in (
        "lexical-index.json",
        "vector-index.json",
        "graph-index.json",
        "projection-manifest.json",
    ):
        path = root / name
        occurrences = (
            _count(path.read_text(encoding="utf-8"), needles) if path.exists() else 0
        )
        report.stores.append(StoreResidual(name, occurrences))
    return report


def scan_mem0(
    system: Any,
    events: tuple[MemoryEvent, ...],
    needles: tuple[str, ...] | None = None,
) -> SystemResidualReport:
    """Scan Mem0's exposed memories *and* its underlying stores.

    Scanning only the API-exposed memories would understate residuals relative
    to the raw-database scan used for Graphiti, so the backing vector store and
    the SQLite history database (which records old/new values per E-025) are
    scanned as well.
    """
    needles = needles or purged_values(events)
    report = SystemResidualReport(system="mem0", purged_values=needles)
    if not needles:
        return report
    memory = system._memory  # adapter-internal store handle

    try:
        result = memory.get_all(user_id=system._user_id)
        rows = result.get("results", result) if isinstance(result, dict) else result
        report.stores.append(
            StoreResidual(
                "mem0_exposed_memories",
                _count(json.dumps(rows, default=str), needles),
                f"{len(rows)} rows",
            )
        )
    except Exception as error:  # pragma: no cover - depends on Mem0 internals
        report.stores.append(StoreResidual("mem0_exposed_memories", -1, str(error)))

    try:
        store = memory.vector_store
        listed = store.list()
        report.stores.append(
            StoreResidual(
                "mem0_vector_store",
                _count(json.dumps(listed, default=str), needles),
                type(store).__name__,
            )
        )
    except Exception as error:  # pragma: no cover
        report.stores.append(StoreResidual("mem0_vector_store", -1, str(error)))

    history = getattr(getattr(memory, "db", None), "db_path", None)
    if history and Path(history).exists():
        try:
            import sqlite3

            connection = sqlite3.connect(str(history))
            try:
                tables = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ]
                occurrences = 0
                for table in tables:
                    for row in connection.execute(f"SELECT * FROM {table}"):  # noqa: S608
                        occurrences += _count(json.dumps(row, default=str), needles)
            finally:
                connection.close()
            report.stores.append(
                StoreResidual(
                    "mem0_history_sqlite",
                    occurrences,
                    f"tables={','.join(tables)}",
                )
            )
        except Exception as error:  # pragma: no cover
            report.stores.append(StoreResidual("mem0_history_sqlite", -1, str(error)))
    return report


def scan_graphiti(
    group_id: str,
    events: tuple[MemoryEvent, ...],
    *,
    uri: str,
    user: str,
    password: str,
    needles: tuple[str, ...] | None = None,
) -> SystemResidualReport:
    """Cypher scan of Neo4j edge facts, node summaries, and episode bodies."""
    from neo4j import GraphDatabase

    needles = needles or purged_values(events)
    report = SystemResidualReport(system="graphiti", purged_values=needles)
    if not needles:
        return report
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            edges = session.run(
                "MATCH ()-[e:RELATES_TO]->() WHERE e.group_id = $g "
                "RETURN collect(e.fact) AS facts",
                g=group_id,
            ).single()["facts"]
            report.stores.append(
                StoreResidual(
                    "neo4j_edge_facts",
                    _count(json.dumps(edges, default=str), needles),
                    f"{len(edges)} edges",
                )
            )
            nodes = session.run(
                "MATCH (n:Entity) WHERE n.group_id = $g "
                "RETURN collect(n.name) + collect(n.summary) AS blobs",
                g=group_id,
            ).single()["blobs"]
            report.stores.append(
                StoreResidual(
                    "neo4j_entity_nodes",
                    _count(json.dumps(nodes, default=str), needles),
                    f"{len(nodes)} node fields",
                )
            )
            episodes = session.run(
                "MATCH (n:Episodic) WHERE n.group_id = $g "
                "RETURN collect(n.content) AS bodies",
                g=group_id,
            ).single()["bodies"]
            report.stores.append(
                StoreResidual(
                    "neo4j_episode_bodies",
                    _count(json.dumps(episodes, default=str), needles),
                    f"{len(episodes)} episodes (raw source text)",
                )
            )
    finally:
        driver.close()
    return report
