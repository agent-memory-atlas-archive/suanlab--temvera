# Preregistration: checking the judge, the real-data gold, the deletion caller and the final store's readings (H13)

Committed and pushed before any of the runs below. Results are reported
whatever they are. Responds to `IDEA_ICDE.md` (re-review of `cea272a`), E1-E4.
No person is available to judge answers independently (E1); these checks do
not replace that, and the paper will not claim they do.

## E3 -- does the judge credit what it should? (`scripts/judge_minimal_pairs.py`)

For 40 grid valid-time questions (seed 13 sample) answers are built from
templates with a known verdict -- right value alone; right value with another
value stated as history; a negated wrong value; a wrong value, bare and dated;
an abstention; an unresolved pair -- and for 40 of the 45 questions about what
was known before a correction: right value alone; what was known then with the
later correction stated; the correction, bare and dated; an abstention. The H9
judge (`gpt-4o`, same prompt) scores each.

- **H13a:** on every valid-time template the judge's verdict matches the
  constructed truth for at least 95% of questions, except "unresolved", for at
  least 90%.
- **H13b:** on every before-the-correction template it matches for at least 90%.

## E2 -- is the real-data valid-time gold identifiable? (`scripts/classify_lme_timing.py`)

Two models classify each of the 60 pairs with a valid-time question as HELD /
CHANGED / UNKNOWN from the conversations alone; a gold is identifiable only if
both say HELD. The common reader is also run with a persistence contract added
to its prompt ("a value stated in a record holds from that record's date until
a later record changes it"; `llm_rescore.py reader_persist`) on the five
retrieval-layer LongMemEval runs and on the grid's Cognee chunks and Hindsight
recall runs.

- **H13c:** at most half of the 60 golds are identifiable.
- **H13d:** with the contract, the common reader answers at least 20 of 60
  valid-time questions from Cognee's chunks on LongMemEval, and on the grid it
  stays at or above 0.70 for Cognee chunks and Hindsight recall.
- **H13e:** on the identifiable pairs alone, the retaining retrieval layers keep
  the superseded value in more than half of their valid-time answers and the
  consolidating ones in fewer than half.

## E4 -- is the over-deletion the caller's or the API's? (`deletion-verified-*`, `deletion-langmem-deletes`)

The H10 histories and seeds are run with one more condition: a *verified*
caller that searches for the person as before but deletes only the returned
units whose text names the person. LangMem is also run under the three prose
wordings with its manager's deletes enabled (`enable_deletes=True`).

- **H13f:** the verified caller leaves at most 1 purged person leaking per system
  and keeps at least 34 of 36 never-purged people in Mem0, Graphiti, LangMem and
  Hindsight, and at least 30 in Cognee.
- **H13g:** with deletes enabled, LangMem leaks fewer purged people than with
  them disabled under each wording (15, 3, 6 in H10).

## H11 under a semantic reading

The H9 common reader is run on the five retrieval-layer final-store correction
runs; an answer to a before-the-correction question counts if the value it gives
is the original one and not the correction.

- **H13h:** Cognee chunks at least 30 of 45 (its chunks are the dated turns);
  Mem0 and LangMem at most 5; Graphiti and Hindsight recall at most 15 each.

## Outcomes (recorded 2026-10-23)

| | Prediction | Observed | Verdict |
|---|---|---|---|
| H13a | judge right >= 95% on each valid-time template (unresolved >= 90%) | 39-40 of 40 on every template (279/280) | holds |
| H13b | judge right >= 90% on each before-the-correction template | 40/40 except "history stated" 3/40 (it takes the later correction as the answer) | **falsified** |
| H13c | at most half of 60 real-data golds identifiable (both models HELD) | 0 (gpt-4o: 5 HELD, 7 CHANGED, 48 UNKNOWN; gpt-4o-mini: 56 CHANGED; the models agree on 7) | holds |
| H13d | persistence contract: Cognee chunks >= 20/60 on LongMemEval; grid >= 0.70 for Cognee chunks and Hindsight recall | 7/60; 0.733, 0.851 | **falsified** on LongMemEval |
| H13e | on identifiable pairs, retaining keep the old value in > half, consolidating in < half | no identifiable pairs | not testable |
| H13f | verified caller: <= 1 leak per system; kept >= 34/36 (Mem0, Graphiti, LangMem, Hindsight), >= 30 (Cognee) | 0 leaks everywhere; kept 36, 36, 33, 36, 36 | **falsified** for LangMem (33; it keeps 30 under the oracle caller) |
| H13g | LangMem with deletes enabled leaks fewer than 15, 3, 6 | 0, 0, 0 -- but keeps only 6, 8, 2 of 36 never-purged people | holds |
| H13h | common reader on the final store, before-the-correction questions: Cognee chunks >= 30; Mem0, LangMem <= 5; Graphiti, Hindsight recall <= 15 | 8; 0, 0; 2, 8 | **falsified** for Cognee chunks |
