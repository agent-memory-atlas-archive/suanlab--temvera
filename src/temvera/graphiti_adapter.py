"""Text-only Graphiti adapter for the external-comparison harness (E1).

Wraps Graphiti's temporal knowledge graph behind the harness ``MemorySystem``
contract, using the embedded **Kuzu** driver so no Neo4j/Docker server is
needed. Unlike Mem0, Graphiti stores explicit edge validity (`valid_at`,
`invalid_at`, `expired_at`, E-024/E-032), so this measures whether those fields
translate into correct bitemporal answers under identical histories.

Graphiti is async and uses OpenAI for extraction/embedding; calls are driven on
a private event loop. `reset()` allocates a fresh in-memory Kuzu graph. The LLM
is pinned to the same backbone as the Mem0 adapter for budget parity. The
`graphiti-core` and `kuzu` dependencies are imported lazily (E1 runner only).
"""

from __future__ import annotations

import os

# Third-party usage telemetry is off by default for research runs. Mem0 and
# Graphiti both ship PostHog clients; Mem0 builds one per Memory instance and
# flushes them all at interpreter exit, which held a 32-entity scale probe open
# for 2 h 13 min after its results were sealed. They also send events to a third
# party mid-experiment. Both libraries read these variables at import time, so
# they are set here, before either is imported; an explicit setting wins.
os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")

from typing import Any

from .nl_workload import NLQueryCase, WorkloadTurn


class GraphitiSystem:
    """Graphiti (Kuzu-backed) temporal graph as a harness memory system."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        embed_model: str = "text-embedding-3-small",
        search_limit: int = 5,
        group_id: str = "temvera-e1",
        search_recipe: str = "hybrid_rrf",
        neo4j_uri: str | None = None,
        neo4j_user: str = "neo4j",
        neo4j_password: str | None = None,
        temporal_filter: bool = False,
    ) -> None:
        import asyncio

        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._temporal_filter = temporal_filter

        from graphiti_core.embedder.openai import (
            OpenAIEmbedder,
            OpenAIEmbedderConfig,
        )
        from graphiti_core.llm_client import LLMConfig, OpenAIClient
        from graphiti_core.search.search_config import (
            EdgeReranker,
            EdgeSearchConfig,
            EdgeSearchMethod,
            SearchConfig,
        )

        # `cosine_only` exists because Kuzu's full-text index is broken in
        # graphiti-core 0.29.2. It must NOT be used on Neo4j, where BM25 works:
        # disabling lexical retrieval there removes the one channel suited to a
        # workload whose only discriminating token is the subject name.
        # `hybrid_rrf` mirrors the library's own default for `search()`.
        methods = (
            [EdgeSearchMethod.cosine_similarity]
            if search_recipe == "cosine_only"
            else [EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity]
        )
        self._search_recipe = search_recipe
        self._search_config = SearchConfig(
            edge_config=EdgeSearchConfig(
                search_methods=methods, reranker=EdgeReranker.rrf
            ),
            node_config=None,
            episode_config=None,
            community_config=None,
            limit=search_limit,
        )
        self._model = model
        self._embed_model = embed_model
        self._search_limit = search_limit
        self._group_id = group_id
        self._llm = OpenAIClient(
            config=LLMConfig(model=model, small_model=model, temperature=0.0)
        )
        self._embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(embedding_model=embed_model)
        )
        self._loop = asyncio.new_event_loop()
        self._graphiti: Any = None
        self._seq = 0

    @property
    def version(self) -> str:
        from importlib.metadata import version

        return version("graphiti-core")

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _wipe_group(self) -> None:
        """Delete every node/edge carrying this run's group_id."""
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            self._neo4j_uri, auth=(self._neo4j_user, self._neo4j_password)
        )
        try:
            with driver.session() as session:
                session.run(
                    "MATCH (n) WHERE n.group_id = $g DETACH DELETE n",
                    g=self._group_id,
                )
        finally:
            driver.close()

    def reset(self) -> None:
        from graphiti_core import Graphiti

        if self._graphiti is not None:
            try:
                self._run(self._graphiti.close())
            except Exception:
                pass
        if self._neo4j_uri:
            self._graphiti = Graphiti(
                uri=self._neo4j_uri,
                user=self._neo4j_user,
                password=self._neo4j_password,
                llm_client=self._llm,
                embedder=self._embedder,
            )
            # Neo4j is a persistent server, and cell labels repeat across runs,
            # so the group must be wiped or a later run would query a graph that
            # still holds an earlier run's episodes and edges.
            self._wipe_group()
        else:
            from graphiti_core.driver.kuzu_driver import KuzuDriver

            driver = KuzuDriver(db=":memory:")
            # graphiti-core 0.29.2 reads driver._database when resolving the
            # default group; KuzuDriver never sets it. NOTE: Kuzu's edge
            # full-text index is also broken in 0.29.2, so this path fails at
            # search time — use the Neo4j backend for real runs.
            driver._database = self._group_id
            self._graphiti = Graphiti(
                graph_driver=driver, llm_client=self._llm, embedder=self._embedder
            )
        self._run(self._graphiti.build_indices_and_constraints())
        self._seq = 0

    def ingest(self, turn: WorkloadTurn) -> None:
        from graphiti_core.nodes import EpisodeType

        self._seq += 1
        self._run(
            self._graphiti.add_episode(
                name=f"ep-{self._seq:04d}-{turn.event_id}",
                episode_body=turn.text,
                source_description="lifecycle history",
                reference_time=turn.recorded_at,
                source=EpisodeType.message,
                group_id=self._group_id,
            )
        )

    def _bitemporal_filter(self, case: NLQueryCase):
        """Graphiti-native valid-time filter for the queried event time.

        ``valid_at <= V AND (invalid_at IS NULL OR invalid_at > V)``; outer
        lists are OR groups, inner lists AND.

        Graphiti's ``created_at``/``expired_at`` record **wall-clock ingestion**
        time, not the simulated transaction time of the history, so they cannot
        express an `as-of` transaction bound here. That axis is instead enforced
        exactly by forward-checkpoint replay (only turns recorded by the query's
        transaction time have been ingested), which keeps the comparison fair.
        """
        from graphiti_core.search.search_filters import (
            ComparisonOperator,
            DateFilter,
            SearchFilters,
        )

        valid_at = case.valid_at
        return SearchFilters(
            valid_at=[
                [
                    DateFilter(
                        date=valid_at,
                        comparison_operator=ComparisonOperator.less_than_equal,
                    )
                ]
            ],
            invalid_at=[
                [DateFilter(comparison_operator=ComparisonOperator.is_null)],
                [
                    DateFilter(
                        date=valid_at,
                        comparison_operator=ComparisonOperator.greater_than,
                    )
                ],
            ],
        )

    def delete_episodes_mentioning(self, needle: str) -> int:
        """Call Graphiti's native `remove_episode` for episodes containing `needle`.

        Measuring deletion by feeding a natural-language "delete" sentence tests
        whether extraction infers deletion intent, not whether the system's
        deletion works. This exercises the documented API instead.
        """
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            self._neo4j_uri, auth=(self._neo4j_user, self._neo4j_password)
        )
        try:
            with driver.session() as session:
                uuids = [
                    record["uuid"]
                    for record in session.run(
                        "MATCH (n:Episodic) WHERE n.group_id = $g AND "
                        "toLower(n.content) CONTAINS toLower($needle) "
                        "RETURN n.uuid AS uuid",
                        g=self._group_id,
                        needle=needle,
                    )
                ]
        finally:
            driver.close()
        for uuid in uuids:
            self._run(self._graphiti.remove_episode(uuid))
        return len(uuids)

    def answer(self, case: NLQueryCase) -> str:
        search_filter = (
            self._bitemporal_filter(case) if self._temporal_filter else None
        )
        results = self._run(
            self._graphiti.search_(
                case.query_text,
                self._search_config,
                group_ids=[self._group_id],
                search_filter=search_filter,
            )
        )
        facts = [str(getattr(edge, "fact", "")) for edge in results.edges]
        return " | ".join(fact for fact in facts if fact)
