"""H11b: read whole stores, not top-five retrievals, for superseded values.

Absence from a retrieval is not proof that a store destroyed a value. For the
ten revision-only histories of the main grid, each store ingests the whole
history and is then read in full through its own library: every Mem0 memory,
every LangMem memory, every Graphiti edge and episode. A superseded value counts
as kept when one record names both the person and the value, so a value shared
with another person is not mistaken for it. For Graphiti we also record whether
an edge stating the superseded value carries ``invalid_at``, and whether that is
the successor's valid-from day.

    python scripts/store_census.py experiments/runs/store-census-v1
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from temvera.experiment import seal_run
from temvera.external_experiment import _events_for
from temvera.model import Operation
from temvera.nl_workload import render_turns

ROOT = Path(__file__).resolve().parents[1]
PROFILE = {"name": "revision_only", "purge_probability": 0.0, "expire_probability": 0.0,
           "reconfirm_probability": 0.0}
SCALES = ((3, 2), (6, 3))
SEEDS = (7, 13, 17, 23, 42)
SYSTEMS = ("mem0", "langmem", "graphiti")


def history(seed: int, entities: int, revisions: int):
    events = _events_for(seed, entities, revisions, PROFILE, True, 1, False, "standard")
    versions: dict[tuple[str, str], list] = {}
    for event in events:
        if event.operation is Operation.INGEST:
            versions.setdefault((event.subject, event.attribute), []).append(event)
    for chain in versions.values():
        chain.sort(key=lambda e: e.valid_from)
    return events, versions


def _names(record: str, subject: str, value: str) -> bool:
    folded = record.casefold()
    return subject.casefold() in folded and value.casefold() in folded


def census_records(system: str, label: str, turns, workdir: Path) -> dict:
    """All records in the store after the whole history is ingested."""
    if system == "mem0":
        from temvera.mem0_adapter import Mem0System, default_mem0_config

        store = Mem0System(config=default_mem0_config(
            history_db_path=str(workdir / f"{label}.db")), user_id=f"census-{label}")
        store.reset()
        for turn in turns:
            store.ingest(turn)
        result = store._memory.get_all(user_id=f"census-{label}")
        rows = result.get("results", result) if isinstance(result, dict) else result
        return {"records": [str(r.get("memory", "")) for r in rows]}
    if system == "langmem":
        from temvera.langmem_adapter import LangMemSystem

        store = LangMemSystem()
        try:
            store.reset()
            for turn in turns:
                store.ingest(turn)
            return {"records": store.memories(), "errors": store.worker_errors}
        finally:
            store.close()
    if system == "graphiti":
        from neo4j import GraphDatabase

        from temvera.graphiti_adapter import GraphitiSystem

        uri, user = os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ["NEO4J_PASSWORD"]
        group = f"census-{label}"
        store = GraphitiSystem(group_id=group, neo4j_uri=uri, neo4j_user=user,
                               neo4j_password=password)
        store.reset()
        for turn in turns:
            store.ingest(turn)
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            with driver.session() as session:
                edges = [dict(r) for r in session.run(
                    "MATCH ()-[e:RELATES_TO]->() WHERE e.group_id = $g RETURN e.fact AS fact, "
                    "toString(e.valid_at) AS valid_at, toString(e.invalid_at) AS invalid_at",
                    g=group)]
                episodes = [r["content"] for r in session.run(
                    "MATCH (n:Episodic) WHERE n.group_id = $g RETURN n.content AS content",
                    g=group)]
        finally:
            driver.close()
        return {"records": [e["fact"] or "" for e in edges], "edges": edges,
                "episodes": episodes}
    raise ValueError(system)


def analyse_cell(system: str, store: dict, versions) -> list[dict]:
    out = []
    for (subject, attribute), chain in sorted(versions.items()):
        for older, newer in zip(chain, chain[1:]):
            row = {"subject": subject, "value": older.value,
                   "kept": any(_names(r, subject, older.value) for r in store["records"])}
            if system == "graphiti":
                stating = [e for e in store["edges"] if _names(e["fact"] or "", subject, older.value)]
                successor_day = newer.valid_from.date().isoformat()
                row["edges"] = len(stating)
                row["invalid_at_set"] = any(e["invalid_at"] not in (None, "", "None")
                                            for e in stating)
                row["invalid_at_correct"] = any(
                    (e["invalid_at"] or "").startswith(successor_day) for e in stating)
                row["in_episodes"] = any(_names(t or "", subject, older.value)
                                         for t in store["episodes"])
            out.append(row)
    return out


def main(output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    rows = []
    with tempfile.TemporaryDirectory() as workdir:
        for system in SYSTEMS:
            for entities, revisions in SCALES:
                for seed in SEEDS:
                    events, versions = history(seed, entities, revisions)
                    turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
                    label = f"{system}-e{entities}-r{revisions}-s{seed}"
                    store = census_records(system, label, turns, Path(workdir))
                    for row in analyse_cell(system, store, versions):
                        rows.append({"system": system, "entities": entities,
                                     "revisions": revisions, "seed": seed, **row})
    summary = {}
    for system in SYSTEMS:
        mine = [r for r in rows if r["system"] == system]
        entry = {"superseded": len(mine), "kept": sum(r["kept"] for r in mine)}
        if system == "graphiti":
            for key in ("invalid_at_set", "invalid_at_correct", "in_episodes"):
                entry[key] = sum(r[key] for r in mine)
        summary[system] = entry
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps({"rows": rows, "summary": summary},
                                                 indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-store-census-v1", "profile": PROFILE,
                          "scales": [list(s) for s in SCALES], "seeds": list(SEEDS),
                          "systems": list(SYSTEMS), "model": "gpt-4o-mini",
                          "embed_model": "text-embedding-3-small", "replay": "single_pass"},
             command=f"python scripts/store_census.py {output}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
