# Preregistration: do the findings survive the current releases? (H7)

Committed and pushed before any run of `experiments/configs/*-latest.json`
exists. The measured versions were Mem0 0.1.118 and Graphiti 0.29.2; the
current releases on 2026-10-22 are Mem0 2.2.1 and Graphiti 0.31.2. Configs are
the cited main-grid configs with only names, user ids and the Graphiti group
prefix changed; the runs use a separate environment so the pinned one is
untouched. Results are reported whatever they are.

What changed that could matter: Mem0 2.x adds `timestamp`, `expiration_date`
and `reference_date` parameters. In the open-source library `timestamp` and
`reference_date` raise "Platform-only ... not supported in OSS"
(`mem0/memory/main.py`, 2.2.1), and `expiration_date` hides a memory once the
wall-clock date passes it, so none expresses a historical valid time. We
therefore run both systems on their default paths, as before.

## Predictions

- **H7a -- Mem0 2.2.1 still consolidates.** On the main grid its valid-time
  accuracy is at most the consolidation ceiling (0.385, §VI-H) and at most 2% of
  its correct valid-time answers lie beyond it. Falsified otherwise.
- **H7b -- Mem0 2.2.1 still answers the present.** Its transaction-scoped
  accuracy is at least 0.85.
- **H7c -- Graphiti 0.31.2 still does not filter.** Its retrieval-layer
  valid-time accuracy is at most 0.03.

Analysis: the existing `micro` aggregation and `analyze_filtering_laws.ceiling`
applied to the new runs, over the same 20 matched cells.
