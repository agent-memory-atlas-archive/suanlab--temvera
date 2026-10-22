# Preregistration: a common reader and an asserted-value judge (H9)

Committed and pushed before `scripts/llm_rescore.py` has been run on any
transcript, including a smoke test. Results are reported whatever they are.

Why: two simulated EAB reviews of the 2026-10-22 draft raised the same threat.
The exact scorer fails any answer that also names a superseded value, so a
store or reader that states the history correctly scores like one that is
wrong; and only Cognee and Hindsight are read through an LLM, at different
temperatures, so the reader comparison is confounded. Both measurements below
re-read answers already sealed; no memory system is re-run.

## Measurements

- **Common reader** (`llm_rescore.py reader openai:gpt-4o-mini <run>`): one fixed
  prompt at temperature 0 turns each recorded top-5 retrieval into a value,
  scored by the grid's own exact scorer. Source runs (main grid, 484 cases):
  `external-mem0-grid-v2`, `external-langmem-v1`, `external-graphiti-hybrid-v1`,
  `external-cognee-chunks-grid-v3`, `external-hindsight-recall-v1`, and
  Mem0 2.2.1's `external-mem0-grid-latest-v1`.
- **Asserted-value judge** (`llm_rescore.py judge openai:gpt-4o <run>`, and a
  second judge `openai:gpt-4o-mini` for agreement): the value each answer
  asserts held at the asked date, or NONE/AMBIGUOUS. Source runs: the LLM-reader
  configurations `external-cognee-grid-v1`, `external-hindsight-reflect-v1`,
  `external-cognee-grid-latest-v1`, `external-hindsight-reflect-latest-v1`.

## Predictions (valid-time questions, 195 per run)

- **H9a -- retaining stores lose no information:** under the common reader,
  Cognee chunks and Hindsight recall answer at least 0.80 (their returned text
  carries the dates). Graphiti, whose returned facts mostly carry no dates,
  answers at most 0.20.
- **H9b -- consolidating stores lose it:** under the common reader, Mem0 0.1.118
  and LangMem answer at most 0.385 (the consolidation ceiling), and at most 2% of
  their correct answers lie beyond the ceiling.
- **H9c -- Mem0 2.2.1 now keeps it:** under the common reader it answers at least
  0.50 (its memories carry "valid from" dates).
- **H9d -- the judge credits stated history:** for each judged run, judged
  accuracy is at least exact accuracy; Hindsight reflect 1.1.0 rises above 0.50;
  Cognee graph-completion stays at or above 0.95.
- **H9e -- the judge is consistent:** on answers the exact scorer marks correct,
  the `gpt-4o` judge agrees in at least 95%; the two judges agree on at least 90%
  of all judged answers.

Transaction-scoped and other categories are reported without prediction. The
analysis is the per-category exact rate each sealed rescore run records; the
ceiling check uses `analyze_filtering_laws.ceiling` logic on the reader's
verdicts.
