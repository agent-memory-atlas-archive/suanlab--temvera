# Preregistration: Hindsight's past-knowledge advantage -- its reader or its context? (H18)

Committed and pushed before `scripts/native_context.py` has run. Its question
selection was checked offline: it picks the same 45 questions as the sealed
H11 final-store runs. Results are reported whatever they are. Responds to M08 of
the 2026-10-23 re-review (`MODIFY.md`).

## Why

Asked of the final store what was known before a correction, Hindsight's own
reader is credited on 29 of 45 questions by the H15 annotators and the common
reader over its recall's top five on 8 (E-105, E-110). The two paths differ in
both the context they read and the reader, so the paper calls the comparison a
pipeline comparison. Hindsight's reflect can return the memories it based its
answer on (`include: {facts: {}}`), which lets the common reader read exactly
that context.

## Design

The ten correction histories of the H11 final-store runs (seeds 7, 13, 17, 23,
42, 57, 99, 101, 131, 151; 8 people, three revisions, corrections) are each
ingested whole into a fresh bank of Hindsight 0.9.1 (`gpt-4o-mini`). For each of
the 45 questions about a corrected interval asked before its correction, three
answers: `own_reader` (reflect), `common_native` (the H9 common reader,
`gpt-4o-mini`, fixed prompt, over the memories and mental models reflect
reports using), `common_recall` (the same reader over recall's top five). Each
answer is scored by the strict count and read by the H15 annotator
(`gpt-4o-2024-08-06`, its fixed prompt, 450/450 on constructed answers); the
predictions use the annotator's credit.

Analysis: `scripts/analyze_h18.py`, committed with this file.

## Predictions

- **H18a -- the own reader replicates:** it is credited on at least 20 of 45
  (29 in H15; reflect runs at temperature 0.9, so some drift is expected).
- **H18b -- the advantage is mostly the context:** the common reader over
  reflect's own context is credited within 5 of the own reader, or above it.
- **H18c -- recall's top five still falls short:** the common reader over it is
  credited on at most 12.
- **H18d -- context matters:** the common reader over reflect's context is
  credited on at least 10 more questions than over recall's top five.

## What follows

If H18b and H18d hold, the paper attributes the advantage to the context
Hindsight's reflect assembles, not to its reader. If H18b fails while H18d
holds, both contribute. If H18d fails, the context explains nothing and the
reader does. Cognee's reader exposes no comparable context and stays a pipeline
comparison.
