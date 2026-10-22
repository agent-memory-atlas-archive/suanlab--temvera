# Preregistration: replication and a second backbone for LangMem, Cognee and Hindsight (H8)

Committed and pushed before any of the runs below exist. Until now only Mem0
and Graphiti were replicated and re-run on a second backbone (E-084, E-089); the
paper's Limitations say so. These runs extend both checks to the other three
systems, on the versions the paper measures (LangMem 0.0.30, Cognee 1.4.2,
Hindsight 0.9.1). Results are reported whatever they are.

## Runs

- **Replicates** (`experiments/configs/variance-{langmem,cognee-chunks,cognee-graph,hindsight-recall,hindsight-reflect}-r{1,2,3}.json`):
  each cited configuration (`external-langmem-v1`, `external-cognee-chunks-grid-v3`,
  `external-cognee-grid-v1`, `external-hindsight-recall-v1`,
  `external-hindsight-reflect-v1`) restricted to seed 7, i.e. the same four
  cells (two scales x two profiles, 97 cases) as the Mem0/Graphiti replicates,
  with only names, user ids and bank prefixes changed. Three runs each.
- **Second backbone** (`external-{langmem,cognee-grid,hindsight-recall,hindsight-reflect}-gpt4o.json`):
  the full 20-cell grid (484 cases) with `gpt-4o` in place of `gpt-4o-mini`.
  Hindsight's LLM is set by its daemon, so these two run against a separate
  0.9.1 daemon (own HOME and profile, port 8892) whose only change is
  `HINDSIGHT_API_LLM_MODEL=gpt-4o`. Cognee `CHUNKS` is not re-run: its read
  path returns stored chunks by embedding similarity and calls no LLM.

Baseline on the four replicate cells (cited runs, seed 7; exact of 97):
LangMem 57 (valid time 13/38), Cognee chunks 20 (0/38), Cognee graph 89 (38/38),
Hindsight recall 20 (0/38), Hindsight reflect 45 (19/38).

## Predictions

- **H8a -- retrieval layers do not filter in any replicate:** Cognee chunks and
  Hindsight recall answer 0 of 38 valid-time questions in each of their three
  replicates.
- **H8b -- the reader ordering holds in every replicate:** in each replicate
  index r, Cognee graph's valid-time exact count exceeds Hindsight reflect's.
- **H8c -- run-to-run variation stays below the effects:** for the four
  configurations whose answer is not synthesised by Hindsight's
  temperature-0.9 reader (LangMem, Cognee chunks, Cognee graph, Hindsight
  recall), each replicate's overall exact count is within 5 of the cited run's
  count on the same 97 cases. Hindsight reflect (reader at
  temperature 0.9) is predicted only to stay within 10.
- **H8d -- LangMem still consolidates under both checks:** in every replicate and
  under `gpt-4o`, at most 2% of LangMem's correct valid-time answers lie beyond
  the consolidation ceiling (`analyze_filtering_laws.ceiling`), and under
  `gpt-4o` its valid-time accuracy is at most 0.385 and its transaction-scoped
  accuracy at least 0.80.
- **H8e -- the retrieval layer still does not filter under gpt-4o:** Hindsight
  recall valid-time accuracy at most 0.03.
- **H8f -- the readers keep their order under gpt-4o:** Cognee graph valid-time
  accuracy at least 0.90, and Hindsight reflect's below it.

Analysis: the existing `micro` aggregation and `analyze_filtering_laws.ceiling`,
over the same cells as each cited run.
