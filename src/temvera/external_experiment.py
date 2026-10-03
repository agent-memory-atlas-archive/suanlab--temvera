"""E1 runner: identical-history comparison of external systems vs the oracle.

Generates seeded lifecycle histories (over a seed × scale × profile grid),
naturalizes surface names so semantic systems can tell entities apart
(E-052), and scores each system's free-text answers against the bitemporal
oracle's ground truth with the deterministic value-substring scorer.

Transaction time is monotonic, so replay uses **forward checkpoints**: turns
are ingested in ``recorded_at`` order and, at each distinct ``transaction_at``,
every case known by then is answered. This costs O(turns) ingests per cell (not
O(cases x prefix)) and is the faithful transaction-time model — the store
accumulates knowledge and cannot un-learn. ``single_pass`` ingests everything
once (current-state answering) for a cheaper contrast.

The runner is adapter-agnostic: any object satisfying the harness
``MemorySystem`` contract (Mem0, Graphiti, ...) is supplied by a factory.
"""

from __future__ import annotations

import os
import random
from typing import Any, Callable

from .external_harness import MemorySystem, OracleMemorySystem, score_answer
from .generator import generate_histories
from .mem0_adapter import Mem0System, default_mem0_config
from .nl_workload import (
    build_nl_cases,
    fallback_tokens,
    naturalize_events,
    render_turns,
)
from .telemetry import Meter, measure_openai

_METRICS = ("exact_state_accuracy", "evidence_recall", "stale_use_rate")


def _cells(config: dict[str, Any]):
    seeds = [int(s) for s in config["seeds"]]
    if "scales" in config:
        scales = [
            (int(s["entities"]), int(s["revisions"])) for s in config["scales"]
        ]
    else:
        d = config["dataset"]
        scales = [(int(d["entities"]), int(d["revisions"]))]
    profiles = config.get("profiles") or [
        {"name": "as_configured", **config.get("profile", {})}
    ]
    for profile in profiles:
        for entities, revisions in scales:
            for seed in seeds:
                yield seed, entities, revisions, profile


def _events_for(
    seed: int,
    entities: int,
    revisions: int,
    profile: dict[str, Any],
    naturalize: bool,
    attributes: int = 1,
    distinct_values: bool = False,
    pools: str = "standard",
):
    events = generate_histories(
        seed=seed,
        entities=entities,
        revisions=revisions,
        attributes=attributes,
        distinct_values=distinct_values,
        reconfirm_probability=float(profile.get("reconfirm_probability", 0.0)),
        expire_probability=float(profile.get("expire_probability", 0.0)),
        purge_probability=float(profile.get("purge_probability", 0.0)),
    )
    return naturalize_events(events, pools=pools) if naturalize else events


def score_on_events(
    system: MemorySystem,
    events,
    *,
    replay: str = "transaction_checkpoint",
    transcript: list[dict[str, Any]] | None = None,
    cell: dict[str, Any] | None = None,
    system_name: str = "",
    meter: Meter | None = None,
) -> dict[str, Any]:
    cases = build_nl_cases(events)
    if not cases:
        raise ValueError("history produced no query cases")
    turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))

    system.reset()
    answers: dict[str, str] = {}
    if replay == "transaction_checkpoint":
        pending = 0
        for tx in sorted({c.transaction_at for c in cases}):
            while pending < len(turns) and turns[pending].recorded_at <= tx:
                if meter is not None:
                    with meter.time_ingest():
                        system.ingest(turns[pending])
                else:
                    system.ingest(turns[pending])
                pending += 1
            for case in (c for c in cases if c.transaction_at == tx):
                if meter is not None:
                    with meter.time_query():
                        answers[case.case_id] = system.answer(case)
                else:
                    answers[case.case_id] = system.answer(case)
    elif replay == "single_pass":
        for turn in turns:
            system.ingest(turn)
        for case in cases:
            answers[case.case_id] = system.answer(case)
    else:
        raise ValueError(f"unknown replay mode: {replay}")

    exact = recall_total = stale_selected = selected_total = 0.0
    abstain = abstain_correct = 0
    by_cat: dict[str, list[float]] = {}
    for case in cases:
        score = score_answer(answers[case.case_id], case)
        exact += score.exact
        recall_total += score.recall
        stale_selected += len(score.present_stale)
        selected_total += len(score.present_expected) + len(score.present_stale)
        by_cat.setdefault(case.category, []).append(float(score.exact))
        if not case.expected_values:
            abstain += 1
            abstain_correct += score.exact
        if transcript is not None:
            transcript.append(
                {
                    "system": system_name,
                    **(cell or {}),
                    "case_id": case.case_id,
                    "category": case.category,
                    "query": case.query_text,
                    "expected_values": sorted(case.expected_values),
                    "stale_values": sorted(case.stale_values),
                    "answer": answers[case.case_id],
                    "present_expected": sorted(score.present_expected),
                    "present_stale": sorted(score.present_stale),
                    "exact": score.exact,
                }
            )
    n = len(cases)
    return {
        "cases": n,
        "exact_state_accuracy": exact / n,
        "evidence_recall": recall_total / n,
        "stale_use_rate": stale_selected / selected_total if selected_total else 0.0,
        "abstention_cases": abstain,
        "abstention_accuracy": abstain_correct / abstain if abstain else 1.0,
        "by_category_exact": {c: sum(v) / len(v) for c, v in sorted(by_cat.items())},
    }


def run_external_comparison(
    config: dict[str, Any],
    system_factory: Callable[[str], MemorySystem],
    *,
    system_name: str,
) -> dict[str, Any]:
    # Every system's comparison runs through here, so this one branch is what
    # puts the real-data workload in front of all of them with the same factory,
    # credentials and backbone record as the synthetic grid.
    if config.get("workload") == "lme_bitemporal":
        from .lme_bitemporal import run_lme_bitemporal

        return run_lme_bitemporal(config, system_factory, system_name=system_name)
    replay = config.get("replay", "transaction_checkpoint")
    naturalize = bool(config.get("naturalize", True))
    rows: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []
    meter = Meter()
    for seed, entities, revisions, profile in _cells(config):
        events = _events_for(
            seed, entities, revisions, profile, naturalize,
            int(config.get("attributes", 1)),
            distinct_values=bool(config.get("distinct_values", False)),
            pools=str(config.get("natural_pools", "standard")),
        )
        cell = {
            "seed": seed,
            "entities": entities,
            "revisions": revisions,
            "profile": str(profile.get("name", "as_configured")),
        }
        fallbacks.append({**cell, **fallback_tokens(events)})
        label = f"{cell['profile']}-e{entities}-r{revisions}-s{seed}"
        with measure_openai(meter):
            target = score_on_events(
                system_factory(label),
                events,
                replay=replay,
                transcript=transcript,
                cell=cell,
                system_name=system_name,
                meter=meter,
            )
        oracle = score_on_events(OracleMemorySystem(events), events, replay=replay)
        rows.append({**cell, "system": system_name, **target})
        rows.append({**cell, "system": "oracle", **oracle})
    summary = _summarize(rows, samples=int(config.get("bootstrap_samples", 2000)))
    return {
        "replay": replay,
        "naturalized": naturalize,
        "rows": rows,
        "summary": summary,
        "telemetry": meter.as_dict(),
        # Synthetic tokens left after relabelling, per cell: zero is the claim
        # the workload makes, so it is recorded rather than assumed.
        "naturalization_fallbacks": fallbacks,
        "workload": {
            "distinct_values": bool(config.get("distinct_values", False)),
            "natural_pools": str(config.get("natural_pools", "standard")),
        },
        "transcript": transcript,
    }


def _summarize(rows: list[dict[str, Any]], *, samples: int) -> dict[str, Any]:
    rng = random.Random(1729)
    systems = sorted({r["system"] for r in rows})
    out: dict[str, Any] = {"overall": {}, "by_condition": {}, "by_category_exact": {}}
    for system in systems:
        sel = [r for r in rows if r["system"] == system]
        out["overall"][system] = {
            m: sum(r[m] for r in sel) / len(sel) for m in _METRICS
        }
        out["overall"][system]["abstention_accuracy"] = sum(
            r["abstention_accuracy"] for r in sel
        ) / len(sel)
        cats: dict[str, list[float]] = {}
        for r in sel:
            for c, v in r["by_category_exact"].items():
                cats.setdefault(c, []).append(v)
        out["by_category_exact"][system] = {
            c: sum(v) / len(v) for c, v in sorted(cats.items())
        }
    conditions = sorted({(r["profile"], r["entities"], r["revisions"]) for r in rows})
    for profile, entities, revisions in conditions:
        key = f"profile={profile},entities={entities},revisions={revisions}"
        out["by_condition"][key] = {}
        for system in systems:
            values = [
                r["exact_state_accuracy"]
                for r in rows
                if r["system"] == system
                and r["profile"] == profile
                and r["entities"] == entities
                and r["revisions"] == revisions
            ]
            boot = sorted(
                sum(rng.choice(values) for _ in values) / len(values)
                for _ in range(samples)
            )
            out["by_condition"][key][system] = {
                "exact_mean": sum(values) / len(values),
                "ci95_low": boot[int(0.025 * (len(boot) - 1))],
                "ci95_high": boot[int(0.975 * (len(boot) - 1))],
                "n_seeds": len(values),
            }
    return out


def run_mem0_comparison(config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("model", "gpt-4o-mini")
    embed_model = config.get("embed_model", "text-embedding-3-small")
    search_limit = int(config.get("search_limit", 5))
    base_user = config.get("user_id", "temvera-e1")

    # Mem0 defaults to one global ~/.mem0/history.db; a concurrent Mem0 process
    # contending for it raises "attempt to write a readonly database", which the
    # library swallows while silently dropping memory actions. Isolate per run.
    import tempfile
    from pathlib import Path as _Path

    history_db = str(_Path(tempfile.mkdtemp(prefix="mem0-grid-")) / "history.db")

    def factory(label: str) -> MemorySystem:
        return Mem0System(
            config=default_mem0_config(
                model=model, embed_model=embed_model, history_db_path=history_db
            ),
            user_id=f"{base_user}-{label}",
            search_limit=search_limit,
        )

    result = run_external_comparison(config, factory, system_name="mem0")
    result["backbone"] = {
        "system": "mem0",
        "mem0_version": Mem0System(
            config=default_mem0_config(
                model=model, embed_model=embed_model, history_db_path=history_db
            )
        ).version,
        "history_db_isolated": True,
        "vector_store_isolated": True,
        "mem0_telemetry": os.environ.get("MEM0_TELEMETRY"),
        "llm_model": model,
        "embed_model": embed_model,
        "replay": result["replay"],
        "naturalized": result["naturalized"],
    }
    return result


def run_graphiti_comparison(config: dict[str, Any]) -> dict[str, Any]:
    import os

    from .graphiti_adapter import GraphitiSystem

    model = config.get("model", "gpt-4o-mini")
    embed_model = config.get("embed_model", "text-embedding-3-small")
    search_limit = int(config.get("search_limit", 5))
    neo4j_uri = config.get("neo4j_uri") or os.environ.get("NEO4J_URI")
    neo4j_user = config.get("neo4j_user") or os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = config.get("neo4j_password") or os.environ.get("NEO4J_PASSWORD")
    temporal_filter = bool(config.get("temporal_filter", False))
    search_recipe = config.get("search_recipe", "hybrid_rrf")

    def factory(label: str) -> MemorySystem:
        return GraphitiSystem(
            model=model,
            embed_model=embed_model,
            search_limit=search_limit,
            # Prefix must differ per run: Neo4j persists between runs and cell
            # labels repeat, so a shared prefix would mix ingestions.
            group_id=f"{config.get('graphiti_group_prefix', 'e1')}-{label}",
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            temporal_filter=temporal_filter,
            search_recipe=search_recipe,
        )

    result = run_external_comparison(config, factory, system_name="graphiti")
    result["backbone"] = {
        "system": "graphiti",
        "graphiti_version": GraphitiSystem(
            neo4j_uri=neo4j_uri, neo4j_user=neo4j_user, neo4j_password=neo4j_password
        ).version,
        "backend": "neo4j" if neo4j_uri else "kuzu",
        "temporal_filter": temporal_filter,
        "search_recipe": search_recipe,
        "llm_model": model,
        "embed_model": embed_model,
        "replay": result["replay"],
        "naturalized": result["naturalized"],
    }
    return result


def run_purge_residual(config: dict[str, Any], workdir: Any) -> dict[str, Any]:
    """E3: ingest one history into each system, then scan derived stores."""
    import os
    from pathlib import Path

    from .purge_residual import (
        purged_values,
        scan_graphiti,
        scan_mem0,
        scan_temvera,
    )

    dataset = config["dataset"]
    profile = config.get("profile", {"purge_probability": 1.0})
    events = _events_for(
        int(dataset["seed"]),
        int(dataset["entities"]),
        int(dataset["revisions"]),
        profile,
        bool(config.get("naturalize", True)),
    )
    values = purged_values(events)
    if not values:
        raise ValueError("history contains no purge; raise purge_probability")
    transaction_at = max(event.recorded_at for event in events)
    turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
    reports = [
        scan_temvera(events, Path(workdir) / "temvera-store", transaction_at).as_dict()
    ]

    deletion_mode = config.get("deletion_mode", "nl_instruction")

    if config.get("include_mem0", True):
        model = config.get("model", "gpt-4o-mini")
        embed_model = config.get("embed_model", "text-embedding-3-small")
        mem0 = Mem0System(
            config=default_mem0_config(
                model=model,
                embed_model=embed_model,
                # Isolate history from the global ~/.mem0/history.db so the
                # residual scan cannot attribute other runs' rows to this one.
                history_db_path=str(Path(workdir) / "mem0-history.db"),
            ),
            user_id=config.get("user_id", "temvera-e3"),
        )
        mem0.reset()
        for turn in turns:
            mem0.ingest(turn)
        if deletion_mode == "native_api":
            for value in values:
                mem0.delete_memories_mentioning(value)
        report = scan_mem0(mem0, events).as_dict()
        report["deletion_mode"] = deletion_mode
        reports.append(report)

    if config.get("include_graphiti", True):
        from .graphiti_adapter import GraphitiSystem

        uri = config.get("neo4j_uri") or os.environ.get("NEO4J_URI")
        user = config.get("neo4j_user") or os.environ.get("NEO4J_USER", "neo4j")
        password = config.get("neo4j_password") or os.environ.get("NEO4J_PASSWORD")
        group = config.get("graphiti_group", "e3-purge")
        graphiti = GraphitiSystem(
            model=config.get("model", "gpt-4o-mini"),
            embed_model=config.get("embed_model", "text-embedding-3-small"),
            group_id=group,
            neo4j_uri=uri,
            neo4j_user=user,
            neo4j_password=password,
        )
        graphiti.reset()
        for turn in turns:
            graphiti.ingest(turn)
        if deletion_mode == "native_api":
            for value in values:
                graphiti.delete_episodes_mentioning(value)
        report = scan_graphiti(
            group, events, uri=uri, user=user, password=password
        ).as_dict()
        report["deletion_mode"] = deletion_mode
        reports.append(report)

    return {
        "purged_values": list(values),
        "events": len(events),
        "turns": len(turns),
        "reports": reports,
        "deletion_mode": deletion_mode,
        "backbone": {
            "deletion_mode": deletion_mode,
            "llm_model": config.get("model", "gpt-4o-mini"),
            "embed_model": config.get("embed_model", "text-embedding-3-small"),
            "naturalized": bool(config.get("naturalize", True)),
        },
    }


def run_langmem_comparison(config: dict[str, Any]) -> dict[str, Any]:
    """LangMem on the same grid, via the isolated-interpreter worker."""
    from .langmem_adapter import LangMemSystem

    model = config.get("model", "gpt-4o-mini")
    embed_model = config.get("embed_model", "text-embedding-3-small")
    search_limit = int(config.get("search_limit", 5))
    made: list[LangMemSystem] = []

    def factory(label: str) -> MemorySystem:
        system = LangMemSystem(
            model=model, embed_model=embed_model, search_limit=search_limit
        )
        made.append(system)
        return system

    try:
        result = run_external_comparison(config, factory, system_name="langmem")
    finally:
        for system in made:
            system.close()
    result["backbone"] = {
        "system": "langmem",
        "langmem_version": made[0].version if made else "unknown",
        "store": "langgraph InMemoryStore (no server)",
        "llm_model": model,
        "embed_model": embed_model,
        "replay": result["replay"],
        "naturalized": result["naturalized"],
        "worker_errors": sum(s.worker_errors for s in made),
    }
    return result


def run_cognee_comparison(config: dict[str, Any]) -> dict[str, Any]:
    """Cognee on the same grid, via the isolated-interpreter worker."""
    import os

    from .stdio_system import CogneeSystem

    search_limit = int(config.get("search_limit", 5))
    model = config.get("model", "gpt-4o-mini")
    embed_model = config.get("embed_model", "text-embedding-3-small")
    root = config.get("cognee_root") or os.environ.get(
        "COGNEE_ROOT", "/tmp/temvera-cognee"
    )
    key = os.environ.get("OPENAI_API_KEY", "")
    made: list[CogneeSystem] = []

    def factory(label: str) -> MemorySystem:
        # Each cell gets its own store root; Cognee persists locally, so sharing
        # one would let an earlier cell's graph leak into a later one.
        cell_env = {
            "COGNEE_SYSTEM_ROOT_DIRECTORY": f"{root}/{label}",
            "COGNEE_DATA_ROOT_DIRECTORY": f"{root}/{label}/data",
            "LLM_API_KEY": key,
            "LLM_PROVIDER": "openai",
            "LLM_MODEL": model,
            "EMBEDDING_PROVIDER": "openai",
            "EMBEDDING_MODEL": embed_model,
            "EMBEDDING_API_KEY": key,
        }
        system = CogneeSystem(
            search_limit=search_limit,
            env=cell_env,
            extra_config={"search_type": config.get("search_type", "GRAPH_COMPLETION")},
        )
        made.append(system)
        return system

    try:
        result = run_external_comparison(config, factory, system_name="cognee")
    finally:
        for system in made:
            system.close()
    result["backbone"] = {
        "system": "cognee",
        "cognee_version": made[0].version if made else "unknown",
        "store": "local (sqlite + embedded vector/graph, no server)",
        "search_type": config.get("search_type", "GRAPH_COMPLETION"),
        "llm_model": model,
        "embed_model": embed_model,
        "replay": result["replay"],
        "naturalized": result["naturalized"],
        "worker_errors": sum(s.worker_errors for s in made),
    }
    return result


def run_hindsight_comparison(config: dict[str, Any]) -> dict[str, Any]:
    """Hindsight on the same grid, via its local daemon's HTTP API."""
    from .hindsight_adapter import HindsightSystem

    read_mode = config.get("read_mode", "recall")
    budget = config.get("hindsight_budget", "mid")
    base_url = config.get("hindsight_url", "http://localhost:8888")
    made: list[HindsightSystem] = []

    def factory(label: str) -> MemorySystem:
        system = HindsightSystem(
            base_url=base_url,
            bank=f"{config.get('bank_prefix', 'temvera')}-{label}",
            search_limit=int(config.get("search_limit", 5)),
            read_mode=read_mode,
            budget=budget,
        )
        made.append(system)
        return system

    result = run_external_comparison(config, factory, system_name="hindsight")
    result["backbone"] = {
        "system": "hindsight",
        "hindsight_version": made[0].version if made else "unknown",
        "store": "local daemon with embedded PostgreSQL (no Docker)",
        "read_mode": read_mode,
        # Hindsight's budget is qualitative, so it is not the k used elsewhere.
        "budget": budget,
        "replay": result["replay"],
        "naturalized": result["naturalized"],
        "worker_errors": sum(s.worker_errors for s in made),
    }
    return result


def projected_ingests(config: dict[str, Any]) -> dict[str, int]:
    """Offline projection of ingest/query call volume (no API calls)."""
    naturalize = bool(config.get("naturalize", True))
    ingests = queries = cells = 0
    for seed, entities, revisions, profile in _cells(config):
        events = _events_for(seed, entities, revisions, profile, naturalize)
        ingests += len(events)
        queries += len(build_nl_cases(events))
        cells += 1
    return {"cells": cells, "ingest_calls": ingests, "search_calls": queries}
