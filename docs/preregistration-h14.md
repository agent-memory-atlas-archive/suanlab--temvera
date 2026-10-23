# Preregistration: what a store costs and how it answers as it grows (H14)

Committed and pushed before `scripts/scale_cost.py` has ingested anything.
Results are reported whatever they are. Responds to E5 of `IDEA_ICDE.md`: the
paper's scale sweep measured accuracy only, and cost only for Mem0.

## Design

One seeded history (200 people x 3 attributes x 3 revisions = 3,000 turns,
natural names and distinct values, no synthetic fallbacks) is ingested, in
order, into one store per system, with measurements after 100, 300, 1,000 and
3,000 turns: ingest latency (p50/p95/p99) and throughput per segment; tokens and
dollars per segment (Mem0 and Graphiti by metering the OpenAI client in-process,
Hindsight from its per-bank LLM-request log); store size read through the store;
resident memory of the database or daemon processes; and query latency and
exact accuracy on 40 current-value and, where people have been revised, 40
earlier-valid-time probe questions built from the oracle over the ingested
prefix. The first 600 turns are everyone's initial values, so valid-time probes
exist only at 1,000 and 3,000 turns. Systems: Mem0 0.1.118, Graphiti 0.29.2
(Neo4j), Hindsight 0.9.1 read two ways on one store (recall and its reflect
reader); all on `gpt-4o-mini`. At 3,000 turns Hindsight, which is served over
HTTP, is also queried by 1, 4 and 16 concurrent clients. Mem0 and Graphiti run
in-process and are not load-tested.

## Predictions

- **H14a -- Mem0's write cost does not grow with the store:** its ingest dollars
  per turn in the 1,000-3,000 segment are within 1.5x of the 100-turn segment.
- **H14b -- Graphiti's does:** its ingest tokens per turn in the 1,000-3,000
  segment are at least 1.3x those of the first 100 turns.
- **H14c -- retrieval stays fast:** at 3,000 turns the retrieval-layer query p95
  is under 2 s for all three systems, and Hindsight's reader p95 is at least 5 s.
- **H14d -- the design split holds at size:** at 1,000 and 3,000 turns, Mem0's
  valid-time exact rate on the probes is at most 0.40, Graphiti's and Hindsight
  recall's at most 0.10, and Hindsight's reader is above its recall.
- **H14e -- where cost sits:** at 3,000 turns, ingest dollars per turn exceed
  query dollars per question by at least 10x for Mem0 and Graphiti, and
  Hindsight's reader costs more per question than Hindsight's retain per turn.

## Addendum (2026-10-23, after a smoke run on a history the study does not use, before any study result)

The smoke run showed Hindsight's background consolidation, triggered by
retains, landing in the window in which questions were asked. Hindsight's cost
is therefore split by the operation its log records -- `reflect` is reading,
everything else (retain, consolidation, deduplication) writing -- rather than
by when the call happened (`scripts/analyze_scale_cost.py`). Mem0 and Graphiti
are split by time, as preregistered. No prediction changes.

Runs are sealed as `scale-growth-<system>-v1`: a first launch under
`scale-cost-*` was refused because `scale-cost-mem0-v1` already names the
earlier Mem0 cost run (E-071); the other two were stopped after a minute,
before writing anything, and all three restarted under the new name.

## Outcomes (recorded 2026-10-24; `scripts/analyze_scale_cost.py`)

| | Prediction | Observed | Verdict |
|---|---|---|---|
| H14a | Mem0 $/turn at 1,000-3,000 within 1.5x of 0-100 | $0.00059 -> $0.00056 | holds |
| H14b | Graphiti tokens/turn at 1,000-3,000 >= 1.3x of 0-100 | 8,335 -> 6,973 (falls) | **falsified** |
| H14c | retrieval p95 < 2 s at 3,000 for all three; Hindsight reader p95 >= 5 s | Mem0 0.25, Graphiti 0.38, Hindsight recall 2.33; reader 36.9 | **falsified** (Hindsight recall) |
| H14d | at 1,000 and 3,000: Mem0 valid <= 0.40, Graphiti and Hindsight recall <= 0.10, reader > recall | Mem0 0/40, 0/40; Graphiti 1/40, 0/40; recall 1/40, 1/40; reader 23/40, 34/40 | holds |
| H14e | at 3,000: write $/turn >= 10x read $/question for Mem0, Graphiti; Hindsight reader $/question > retain $/turn | yes; $0.0199 > $0.00176 | holds |

Not predicted, reported: once people have revisions the retaining retrieval
layers answer no current question exactly at 3,000 turns (Graphiti and Hindsight
recall 0/40, from 38 and 39 of 40 at 100), while Mem0 keeps 38. Hindsight's
reader slows (p95 10.8 -> 36.9 s) and costs more per question ($0.0068 ->
$0.0199) as the store grows; its exact counts fall with answer length, and the
asserted-value judge, applied after the runs (`h14-judge-gpt4o-scale-growth-hindsight-v1`),
credits 38/40 current and 40/40 earlier values at 3,000 turns.
