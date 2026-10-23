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
