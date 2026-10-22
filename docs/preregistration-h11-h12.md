# Preregistration: after-the-fact transaction time, a store census, and a controlled policy swap (H11, H12)

Committed and pushed before any of the runs or scripts below have been run.
Results are reported whatever they are.

Why: a five-reviewer review (`REVIEW_ICDE.md`) judged three points decisive. (1)
Forward-checkpoint replay asks each question of a store that has seen only what
was known then, so it never tests whether a store that has seen everything can
say what it knew earlier. (2) Absence from a top-five retrieval is not proof
that a consolidating store destroyed a value, and the account of Graphiti's
`invalid_at` rests on an inspection of a withdrawn run. (3) The two designs
differ in extractor, retriever and reader as well as in what they keep, so the
taxonomy has no controlled test of the retention policy alone.

## H11a -- what did the final store know before a correction?

The retroactive-correction workload (§VI-I; 10 histories, 8 people, 3 revisions,
seeds 7, 13, 17, 23, 42, 57, 99, 101, 131, 151) contains 45 questions about an
interval later corrected, asked at a transaction time *before* the correction:
"What is X's home city as of V, based only on what was known by T?", whose
answer is the original value. Under forward-checkpoint replay they are trivial.
Here every configuration ingests the whole history first (`single_pass`) and is
then asked every question (`experiments/configs/final-store-corrections-*.json`):
Mem0, LangMem, Graphiti, Cognee chunks, Cognee graph-completion, Hindsight
recall, Hindsight reflect, on the measured versions and `gpt-4o-mini`.

- **H11a:** on those 45 pre-correction questions, no configuration answers more
  than 15 exactly, and no retrieval-layer configuration more than 5. The judge
  of H9 is also applied to the two reader configurations; prediction: neither is
  credited with more than 15.

## H11b -- a census of what the stores keep

On the ten revision-only histories of the main grid (2 scales x 5 seeds), each
store ingests the whole history and is then read in full through its own
library (`scripts/store_census.py`): Mem0's memories, LangMem's store, and
Graphiti's edges and episodes. For every superseded value we record whether it
appears anywhere in the store, and for Graphiti whether the edges stating it
carry an `invalid_at`, and whether that date is the successor's valid-from day.

- **H11b-1:** a superseded value appears anywhere in Mem0's store for at most 10%
  of superseded values, and in LangMem's for at most 25%.
- **H11b-2:** it appears in Graphiti's store for at least 90%.
- **H11b-3:** for fewer than half of the superseded values in Graphiti, some edge
  stating the value carries an `invalid_at` equal to the successor's valid-from
  day.

## H12 -- the same retriever and reader, only the retention policy changes

`scripts/controlled_policy.py` builds, for every question of the 20-cell main
grid (484 questions), a store from the rendered turns recorded by the question's
transaction time under one of two policies: **retain** keeps every rendered
turn; **consolidate** keeps, per person, only the statement of the latest value
that is neither superseded nor purged (expired values are kept). Both are
searched with the same BM25 over the same text (top five), and the result is
scored (a) as returned, with the grid's exact scorer, and (b) through the common
reader of H9 (same prompt, `gpt-4o-mini`, temperature 0). Nothing else differs.

- **H12a:** as returned, retain answers at most 0.05 of the 195 valid-time
  questions and consolidate at most 0.385 (its ceiling).
- **H12b:** read, retain answers at least 0.70 of them and consolidate at most
  0.385, with at most 2% of consolidate's correct answers beyond the ceiling.
- **H12c:** read, consolidate answers transaction-scoped questions at least as
  often as retain (both at least 0.90).

Analysis: case-weighted rates over the stated questions; the ceiling check uses
`analyze_filtering_laws`' answerability rule.

## Outcomes (recorded 2026-10-23)

| | Prediction | Observed | Verdict |
|---|---|---|---|
| H11b-1 | superseded values anywhere in Mem0 <= 10%, LangMem <= 25% | 0/75, 7/75 | holds |
| H11b-2 | Graphiti >= 90% | 75/75 | holds |
| H11b-3 | Graphiti `invalid_at` = successor's valid-from for fewer than half | 43/75 (set at all: 61/75) | **falsified** (Graphiti closes intervals more often than predicted) |
| H12a | retain <= 0.05, consolidate <= 0.385 valid time as returned | 0.159; 0.385 | **falsified** for retain |
| H12b | read: retain >= 0.70, consolidate <= 0.385 with <= 2% beyond the ceiling | 0.774; 0.379, 0 beyond | holds |
| H12c | read: consolidate transaction-scoped >= retain, both >= 0.90 | 1.000, 1.000 | holds |
