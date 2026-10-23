"""H10: does a deletion request reach every store, in five systems?

The first deletion measurement (``purge_residual``) used one seeded history,
one prose wording, two systems, and native API calls whose handles the harness
chose by matching the payload it knew. This study widens each of those, as
preregistered in ``docs/preregistration-h10.md``:

* ten histories with purges and with people who are never purged, so that a
  deletion that removes too much is visible as well as one that removes too
  little;
* three prose wordings of the request, none restating the value;
* two API callers: an *oracle* that deletes every unit whose stored text holds a
  value of the purged subject (the most any caller could do), and a *caller*
  that only asks the store about the subject and deletes what comes back;
* all five systems, each store read through its own library and marked by
  whether a query path reads it.

The primary measure is an answer leak: after deletion, does the store's answer
to "What is X's A?" still contain any value X's A ever had. Store residue is
reported beside it, never as a pass/fail verdict.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .external_experiment import _events_for
from .model import MemoryEvent, Operation
from .nl_workload import PURGE_WORDINGS, render_turns
from .purge_residual import scan_graphiti, scan_mem0, scan_temvera

CONDITIONS = ("prose-1", "prose-2", "prose-3", "api-oracle", "api-caller")
# H13 adds a caller that deletes only returned units naming the person.
ALL_CONDITIONS = CONDITIONS + ("api-verified",)

# Whether a query path reads the store. Audit logs, histories, raw input copies
# and request traces are kept by the system but never consulted to answer.
REACHABLE = {
    "mem0_exposed_memories": True, "mem0_vector_store": True,
    "mem0_history_sqlite": False,
    "neo4j_edge_facts": True, "neo4j_entity_nodes": True,
    "neo4j_episode_bodies": True,
    "cognee_vector_store": True, "cognee_graph_store": True,
    "cognee_relational_db": False, "cognee_cache_db": False,
    "cognee_raw_inputs": False,
    "langmem_store": True,
    "raw_ledger_jsonl": False, "markdown_projection": True,
    "lexical-index.json": True, "vector-index.json": True,
    "graph-index.json": True, "projection-manifest.json": True,
}
# Hindsight tables a recall or reflect reads; every other bank-scoped table is
# bookkeeping (documents keep the original input, audit and request logs keep
# what passed through).
HINDSIGHT_READ = {"memory_units", "entities", "memory_links", "chunks",
                  "mental_models", "knowledge_pages", "directives"}
HINDSIGHT_TABLES = (
    "async_operations", "audit_log", "chunks", "directives", "documents",
    "entities", "invalidated_memory_units", "knowledge_pages", "llm_requests",
    "memory_links", "memory_units", "mental_model_history", "mental_models",
    "observation_history",
)


@dataclass(frozen=True, slots=True)
class _Probe:
    """The fields of a query case the adapters read."""

    query_text: str
    valid_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Subject:
    subject: str
    attribute: str
    values: tuple[str, ...]
    purged: bool

    @property
    def query(self) -> str:
        return f"What is {self.subject}'s {self.attribute}?"


def subjects(events: tuple[MemoryEvent, ...]) -> list[Subject]:
    keys: dict[str, tuple[str, str]] = {}
    values: dict[tuple[str, str], list[str]] = {}
    for event in events:
        if event.operation is Operation.INGEST:
            key = (event.subject, event.attribute)
            keys[event.belief_id] = key
            values.setdefault(key, [])
            if event.value and event.value not in values[key]:
                values[key].append(event.value)
    purged = {keys[e.belief_id] for e in events
              if e.operation is Operation.PURGE and e.belief_id in keys}
    return [Subject(s, a, tuple(v), (s, a) in purged)
            for (s, a), v in sorted(values.items())]


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(n.casefold() in folded for n in needles)


class _Mem0ActionErrors(logging.Handler):
    """Actions Mem0 dropped behind its broad ``except`` (they are only logged)."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "Error processing memory action" in message:
            self.messages.append(message[:300])


# --------------------------------------------------------------------- drivers
class _Driver:
    name = ""

    def ingest(self, turn) -> None: ...
    def answer(self, query: str) -> str: ...
    def delete_oracle(self, needles: tuple[str, ...]) -> int: ...
    def delete_caller(self, query: str) -> int: ...
    def delete_verified(self, query: str, subject: str) -> int: ...
    def scan(self, needles: tuple[str, ...]) -> dict[str, int]: ...
    def extra(self) -> dict[str, Any]:
        return {}
    def errors(self) -> int:
        return 0
    def close(self) -> None: ...


class _Mem0(_Driver):
    name = "mem0"

    def __init__(self, config: dict, label: str, workdir: Path) -> None:
        from .mem0_adapter import Mem0System, default_mem0_config

        self._handler = _Mem0ActionErrors()
        logging.getLogger("mem0").addHandler(self._handler)
        self.system = Mem0System(
            config=default_mem0_config(
                model=config.get("model", "gpt-4o-mini"),
                embed_model=config.get("embed_model", "text-embedding-3-small"),
                history_db_path=str(workdir / f"mem0-history-{label}.db"),
            ),
            user_id=f"del-{label}",
        )
        self.system.reset()
        self._events: tuple[MemoryEvent, ...] = ()

    def ingest(self, turn) -> None:
        self.system.ingest(turn)

    def answer(self, query: str) -> str:
        return self.system.answer(_Probe(query))

    def delete_oracle(self, needles):
        return sum(self.system.delete_memories_mentioning(n) for n in needles)

    def delete_caller(self, query):
        return self.system.delete_ids(self.system.search_ids(query))

    def delete_verified(self, query, subject):
        return self.system.delete_ids(self.system.search_ids(query, must_mention=subject))

    def scan(self, needles):
        report = scan_mem0(self.system, self._events, needles)
        return {s.store: s.occurrences for s in report.stores}

    def extra(self):
        events = [row.get("event") for result in self.system.last_added
                  for row in (result.get("results") or []) if isinstance(row, dict)]
        return {"mem0_events": {e: events.count(e) for e in sorted(set(map(str, events)))},
                "mem0_dropped_actions": len(self._handler.messages),
                "mem0_dropped_messages": self._handler.messages[:5]}

    def close(self):
        logging.getLogger("mem0").removeHandler(self._handler)


class _Graphiti(_Driver):
    name = "graphiti"

    def __init__(self, config: dict, label: str, workdir: Path) -> None:
        from .graphiti_adapter import GraphitiSystem

        self._uri = config.get("neo4j_uri") or os.environ.get("NEO4J_URI")
        self._user = config.get("neo4j_user") or os.environ.get("NEO4J_USER", "neo4j")
        self._password = config.get("neo4j_password") or os.environ.get("NEO4J_PASSWORD")
        self._group = f"del-{label}"
        self.system = GraphitiSystem(
            model=config.get("model", "gpt-4o-mini"),
            embed_model=config.get("embed_model", "text-embedding-3-small"),
            group_id=self._group, neo4j_uri=self._uri, neo4j_user=self._user,
            neo4j_password=self._password,
        )
        self.system.reset()

    def ingest(self, turn):
        self.system.ingest(turn)

    def answer(self, query):
        return self.system.answer(_Probe(query))

    def delete_oracle(self, needles):
        return sum(self.system.delete_episodes_mentioning(n) for n in needles)

    def delete_caller(self, query):
        return self.system.delete_episodes_for_query(query)

    def delete_verified(self, query, subject):
        return self.system.delete_episodes_for_query(query, must_mention=subject)

    def scan(self, needles):
        report = scan_graphiti(self._group, (), uri=self._uri, user=self._user,
                               password=self._password, needles=needles)
        return {s.store: s.occurrences for s in report.stores}


class _Stdio(_Driver):
    """Shared by the two systems behind a worker in another interpreter."""

    system: Any

    def ingest(self, turn):
        self.system.ingest(turn)

    def answer(self, query):
        return self.system.answer(_Probe(query))

    def delete_oracle(self, needles):
        return int(self.system._call({"op": "delete_matching",
                                      "needles": list(needles)}).get("deleted", 0))

    def delete_caller(self, query):
        return int(self.system._call({"op": "delete_for_query",
                                      "query": query}).get("deleted", 0))

    def delete_verified(self, query, subject):
        return int(self.system._call({"op": "delete_for_query", "query": query,
                                      "must_mention": subject}).get("deleted", 0))

    def scan(self, needles):
        response = self.system._call({"op": "scan", "needles": list(needles)})
        return {k: int(v) for k, v in (response.get("stores") or {}).items()} or {
            "scan_failed": -1}

    def errors(self):
        return self.system.worker_errors

    def extra(self):
        return {"worker_error_messages": self.system.error_messages[:5]}

    def close(self):
        self.system.close()


class _Cognee(_Stdio):
    name = "cognee"

    def __init__(self, config: dict, label: str, workdir: Path) -> None:
        from .stdio_system import CogneeSystem

        key = os.environ.get("OPENAI_API_KEY", "")
        root = f"{config.get('cognee_root', '/tmp/temvera-cognee-deletion')}/{label}"
        self.system = CogneeSystem(
            search_limit=5,
            env={"SYSTEM_ROOT_DIRECTORY": root, "DATA_ROOT_DIRECTORY": f"{root}/data",
                 "CACHE_ROOT_DIRECTORY": f"{root}/cache", "LLM_API_KEY": key,
                 "LLM_PROVIDER": "openai",
                 "LLM_MODEL": config.get("model", "gpt-4o-mini"),
                 "EMBEDDING_PROVIDER": "openai",
                 "EMBEDDING_MODEL": config.get("embed_model", "text-embedding-3-small"),
                 "EMBEDDING_API_KEY": key},
            extra_config={"search_type": "CHUNKS", "system_root": root,
                          "data_root": f"{root}/data"},
        )
        self.system.reset()


class _LangMem(_Stdio):
    name = "langmem"

    def __init__(self, config: dict, label: str, workdir: Path) -> None:
        from .langmem_adapter import LangMemSystem

        self.system = LangMemSystem(
            model=config.get("model", "gpt-4o-mini"),
            embed_model=config.get("embed_model", "text-embedding-3-small"),
            enable_deletes=bool(config.get("langmem_enable_deletes", False)),
        )
        self.system.reset()


class _Hindsight(_Driver):
    name = "hindsight"

    def __init__(self, config: dict, label: str, workdir: Path) -> None:
        from .hindsight_adapter import HindsightSystem

        self._bank = f"del-{label}"
        # Machine-specific, so taken from the environment rather than the
        # sealed config: the daemon's psql and its pg0 instance file.
        self._pg = config.get("hindsight_pg") or {
            "psql": os.environ["HINDSIGHT_PSQL"],
            "instance": os.environ["HINDSIGHT_PG_INSTANCE"]}
        self.system = HindsightSystem(base_url=config.get("hindsight_url", "http://localhost:8893"),
                                      bank=self._bank,
                                      read_mode="recall")
        self.system.reset()
        # Deleting a bank that does not exist yet answers 404; that is not a
        # failure of the run.
        self.system._errors.clear()

    def ingest(self, turn):
        self.system.ingest(turn)

    def answer(self, query):
        return self.system.answer(_Probe(query))

    def delete_oracle(self, needles):
        return self.system.delete_documents_matching(list(needles))

    def delete_caller(self, query):
        return self.system.delete_documents_for_query(query)

    def delete_verified(self, query, subject):
        return self.system.delete_documents_for_query(query, must_mention=subject)

    def scan(self, needles):
        instance = json.loads(Path(self._pg["instance"]).read_text(encoding="utf-8"))
        env = {**os.environ, "PGPASSWORD": instance["password"]}
        out: dict[str, int] = {}
        for table in HINDSIGHT_TABLES:
            result = subprocess.run(
                [self._pg["psql"], "-h", "127.0.0.1", "-p", str(instance["port"]),
                 "-U", instance["username"], "-d", instance["database"], "-At", "-c",
                 f"SELECT row_to_json(t)::text FROM {table} t "
                 f"WHERE bank_id = '{self._bank}'"],
                capture_output=True, text=True, env=env,
            )
            if result.returncode:
                out[f"hindsight_{table}"] = -1
                continue
            text = result.stdout.casefold()
            out[f"hindsight_{table}"] = sum(text.count(n.casefold()) for n in needles)
        return out

    def errors(self):
        return self.system.worker_errors

    def extra(self):
        return {"worker_error_messages": self.system.error_messages[:5]}


DRIVERS = {d.name: d for d in (_Mem0, _Graphiti, _Cognee, _Hindsight, _LangMem)}


def reachable(store: str) -> bool:
    if store.startswith("hindsight_"):
        return store.removeprefix("hindsight_") in HINDSIGHT_READ
    return REACHABLE.get(store, True)


# ------------------------------------------------------------------------ run
def run_one(system: str, config: dict, seed: int, condition: str,
            workdir: Path) -> dict[str, Any]:
    profile = config["profile"]
    events = _events_for(seed, int(config["entities"]), int(config["revisions"]),
                         profile, True, 1, True, "standard")
    wording = int(condition.split("-")[1]) - 1 if condition.startswith("prose") else 0
    turns = sorted(render_turns(events, purge_wording=wording),
                   key=lambda t: (t.recorded_at, t.event_id))
    people = subjects(events)
    purged = [p for p in people if p.purged]
    needles = tuple(v for p in purged for v in p.values)
    label = f"{system}-{seed}-{condition}{config.get('label_suffix', '')}"
    driver = DRIVERS[system](config, label, workdir)
    try:
        for turn in turns:
            driver.ingest(turn)
        deleted = 0
        if condition == "api-oracle" and needles:
            deleted = driver.delete_oracle(needles)
        elif condition == "api-caller":
            deleted = sum(driver.delete_caller(p.query) for p in purged)
        elif condition == "api-verified":
            deleted = sum(driver.delete_verified(p.query, p.subject) for p in purged)
        answers = {p.query: driver.answer(p.query) for p in people}
        stores = driver.scan(needles) if needles else {}
        record = {
            "system": system, "seed": seed, "condition": condition,
            "purge_wording": PURGE_WORDINGS[wording] if condition.startswith("prose") else None,
            "units_deleted": deleted,
            "purged": [{"subject": p.subject, "attribute": p.attribute,
                        "values": list(p.values),
                        "leaked": _contains(answers[p.query], p.values),
                        # The typed purge removes only the latest belief; the
                        # request asks for everything. Both readings are kept.
                        "leaked_latest": _contains(answers[p.query], p.values[-1:]),
                        "answer": answers[p.query]} for p in purged],
            "kept": [{"subject": p.subject, "attribute": p.attribute,
                      "current": p.values[-1],
                      "present": _contains(answers[p.query], (p.values[-1],)),
                      "answer": answers[p.query]} for p in people if not p.purged],
            "stores": [{"store": k, "occurrences": v, "reachable": reachable(k)}
                       for k, v in sorted(stores.items())],
            "worker_errors": driver.errors(),
            **driver.extra(),
        }
    finally:
        driver.close()
    return record


def run_reference(config: dict, seed: int, workdir: Path) -> dict[str, Any]:
    events = _events_for(seed, int(config["entities"]), int(config["revisions"]),
                         config["profile"], True, 1, True, "standard")
    purged = [p for p in subjects(events) if p.purged]
    needles = tuple(v for p in purged for v in p.values)
    if not needles:
        return {"system": "temvera", "seed": seed, "condition": "typed-purge",
                "stores": []}
    report = scan_temvera(events, workdir / f"temvera-{seed}",
                          max(e.recorded_at for e in events), needles)
    return {"system": "temvera", "seed": seed, "condition": "typed-purge",
            "stores": [{"store": s.store, "occurrences": s.occurrences,
                        "reachable": reachable(s.store)} for s in report.stores]}


def run_deletion_study(config: dict[str, Any], workdir: str) -> dict[str, Any]:
    root = Path(workdir)
    records = []
    for system in config["systems"]:
        for seed in config["seeds"]:
            for condition in config.get("conditions", CONDITIONS):
                records.append(run_one(system, config, int(seed), condition, root))
    reference = [run_reference(config, int(seed), root) for seed in config["seeds"]]
    return {"records": records, "reference": reference,
            "summary": summarize(records)}


def summarize(records: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for record in records:
        key = f"{record['system']}:{record['condition']}"
        entry = out.setdefault(key, {"purged": 0, "leaked": 0, "kept_total": 0,
                                     "kept_present": 0, "histories_with_purge": 0,
                                     "offpath_residue_histories": 0,
                                     "reachable_residue_histories": 0,
                                     "worker_errors": 0})
        entry["purged"] += len(record["purged"])
        entry["leaked"] += sum(p["leaked"] for p in record["purged"])
        entry["kept_total"] += len(record["kept"])
        entry["kept_present"] += sum(k["present"] for k in record["kept"])
        entry["worker_errors"] += record["worker_errors"]
        if record["purged"]:
            entry["histories_with_purge"] += 1
            entry["offpath_residue_histories"] += any(
                s["occurrences"] > 0 and not s["reachable"] for s in record["stores"])
            entry["reachable_residue_histories"] += any(
                s["occurrences"] > 0 and s["reachable"] for s in record["stores"])
    return out
