# Preregistration: store size and revision load, separated; one question read three ways, at what cost (H16)

Committed and pushed before `scripts/scale_fixed.py` has ingested any study
history. Smoke runs used a history the study does not use (seed index 9, two
focal people, six questions per kind) and wrote outside `experiments/`; their
purpose was plumbing. Mem0's smoke output was seen before these predictions
were written, Hindsight's was not. Results are reported whatever they are. Responds to M04 and M05 of the
2026-10-23 re-review (`MODIFY.md`, Stage B rows 3 and 4).

## Why

H14 grew one store to 3,000 turns and asked new questions at each checkpoint:
the first 600 turns hold no revision, valid-time questions exist only from
1,000 turns, and the probe set is resampled each time (E-107). Its trajectory
therefore changed store size, revisions per person and the questions together,
and the paper now calls it one workload's trajectory. Its cost comparison also
set a retrieval layer, which returns memories, beside a reader, which returns
an answer.

## Design

`scripts/scale_fixed.py`. A focal history of 14 people x 3 attributes (42
keys), each with `r` values, is interleaved in recorded order with distractor
people (3 attributes, 3 values each, 15 turns a person) drawn from one seeded
history, nested across stores and spanning the same dates. Names and values
are natural, distinct and containment-free; each seed's relabelling is rotated
along the pools so seeds hold different people and values.

| Store | focal `r` | distractor people | turns |
|---|---|---|---|
| size-300 | 3 | 6 | 300 |
| size-1005 | 3 | 53 | 1,005 |
| size-3000 | 3 | 186 | 3,000 |
| rev-2 | 2 | 59 | 1,011 |
| rev-5 | 5 | 42 | 1,008 |

Questions, per store, 84: for each focal key the current value and the first
value at its valid-from date, both "based only on what was known by" the last
focal turn. On the size axis the 84 questions and their answers are identical
at every size (checked before the runs). Three seeds (focal/distractor 101/201,
102/202, 103/203). Each store is fresh.

Read paths, per question: the retrieval layer's top five (`retrieval`); the H9
common reader (`gpt-4o-mini`, its fixed prompt, temperature 0) over those five
(`common_reader`); for Hindsight its own reader, reflect (`own_reader`). Per
path and question: answer, exact score, whether a superseded value appears,
latency, API tokens and dollars at the list prices in `temvera.telemetry`.
Per store: ingest tokens and dollars, size, and the proportional set size
(PSS) and RSS of the serving processes. Three warm-up questions about
distractors are asked and discarded first; the 84 follow in a seeded order.

Systems: Mem0 0.1.118 (in-process, local Qdrant; one process per store, the
five stores of a seed in parallel) and Hindsight 0.9.1 (one daemon with its own
embedded PostgreSQL per seed, pinned to its own 12 CPU cores; a seed's stores
run one after another, the bank deleted once measured; questions start only
after the bank has logged no LLM request for 60 s). Graphiti is not run: its
stores would share one Neo4j database, so its latency would not be the store's.
Backbone `gpt-4o-mini` throughout.

Rates pool the three seeds (126 questions per category, path and store); each
seed is also reported. With three seeds no test of significance is made.

After the runs, the asserted-value judge of H9 (`gpt-4o`, valid for valid-time
questions: 279/280 constructed answers) is applied to the common-reader and
own-reader answers and reported beside the exact score; no prediction uses it.

## Predictions

- **H16a -- Mem0 does not lose current answers with size:** its retrieval
  layer's current exact rate is at least 0.80 at every size, the 300 and 3,000
  stores differ by at most 0.10, and its valid-time exact rate is at most 0.15
  at every size.
- **H16b -- a retaining store's failure comes with revisions, not size:**
  Hindsight recall's current exact rate is at most 0.25 already at 300 turns
  and at every size, and a superseded value appears in at least 60% of its
  current answers at every size.
- **H16c -- revision load at fixed size:** at about 1,000 turns, the share of
  Hindsight recall's current answers containing a superseded value is at least
  as high at `r` = 5 as at `r` = 2; Mem0's current exact rate differs by at most
  0.10 between them.
- **H16d -- the own reader along size:** Hindsight reflect's valid-time exact
  rate is at least 0.60 at every size, and its p95 latency at 3,000 turns is at
  least 1.5x its p95 at 300.
- **H16e -- a common reader over retrieval does most of that for a fraction of
  the cost:** over Hindsight recall, the common reader's valid-time exact rate
  is at least 0.50 at every size, at no more than 0.2x reflect's API dollars per
  question and no more than 0.5x its p95 latency; over Mem0 it is at most 0.15.
- **H16f -- write cost:** Mem0's ingest dollars per turn at 3,000 turns are
  within 1.25x of those at 300; Hindsight's are at least 1.10x.
- **H16g -- retrieval latency:** Hindsight recall's p95 at 3,000 turns is at
  least 1.2x its p95 at 300; Mem0's is at most 1.5x.

Analysis: `scripts/analyze_h16.py`, committed with this file.

## Addendum (2026-10-24 02:20 KST, during the runs, before any result was read)

Mem0 0.1.118 builds a telemetry vector store at a fixed path under `MEM0_DIR`
(default `~/.mem0/migrations_qdrant`) and deletes that directory on every
`Memory` construction and reset. With fifteen Mem0 processes starting at once,
one seed-1 store failed at construction (`FileNotFoundError: mem0migrations`)
and its driver stopped; the other seed-1 stores were then stopped by hand.
Seeds 2 and 3 had passed construction and continue unchanged: the store is
touched only there, and their questions had not yet been asked. The harness now
gives each Mem0 process its own `MEM0_DIR`, and seed 1 of Mem0 is re-run from
scratch with it. No output of the failed seed-1 attempt existed or was kept.
