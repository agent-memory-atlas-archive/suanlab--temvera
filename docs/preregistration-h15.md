# Preregistration: what the answers about past knowledge assert, and whether the real-data gold is identifiable (H15)

Committed and pushed before any of the runs below has made a model call. Results
are reported whatever they are. Responds to M01 and M02 of the 2026-10-23
re-review (`MODIFY.md`, Stage B rows 1 and 2).

## Why

The paper counts the answers to "what was known before a correction" (H11a,
final store) with a strict token rule: exact under the grid's scorer and not
naming the later correction. That rule fails a right answer that also reports
the correction and passes `It was not X.` (E-107). The asserted-value judge of
H9 cannot replace it, because it credits answers that state the original value
and the later correction only 3 times in 40 (E-108). Separately, the real-data
valid-time gold assumes an earlier value held until it was next mentioned; the
first relabelling (H13-E2) let its models describe evidence in prose, and the
two agreed on 7 of 60 pairs, so how many golds the conversations identify is
unknown.

## Design

**Annotation (`scripts/annotate_known_then.py`).** A model reads each answer with
its question, blind to the system that wrote it and to every earlier score, and
reports in JSON the value the answer gives as its answer to the question as
asked (the value known by the knowledge date, not a correction recorded after
it), whether it mentions a later value, and the exact words it relies on. The
verdict is computed, not asked for: credited when the reported value names the
original value and neither the correction nor any other value known by then.
The quoted words are checked against the answer. The prompt is fixed in the
script and hashed into each sealed run; nothing is tuned between the
constructed and the sealed answers, which are read in the same run.

- *Constructed answers* (450): ten templates over each of the 45 questions, whose
  verdict is fixed by construction. Credited: the value alone; the value as
  known by T with the later correction stated; the value with a note that a
  record after T corrected it; `x, not y`. Not credited: the correction alone;
  the correction dated as known by T; `It was not x.` (the case the strict rule
  passes); `Not x; it was y.`; an abstention; `either x or y`.
- *Native answers* (90): Cognee's and Hindsight's own readers, 45 each, from the
  sealed final-store runs.
- *Common-reader answers* (225): the common reader over the five retrieval
  layers' top five (`h13-reader-final-store-*`).

Two annotators, of different model generations, each in its own sealed run:
`gpt-4o-2024-08-06` (`h15-annotate-gpt4o-v1`) and `gpt-5.4-2026-03-05` with
reasoning effort `none` (`h15-annotate-gpt54-v1`), both at temperature 0, seed 7.
An answer is credited by consensus when both credit it. No person judges
anything; the result is AI annotation checked against constructed answers, and
is not called human validation.

**Timing relabelling (`scripts/classify_lme_timing_quotes.py`).** The H13-E2
question and decision rules, with one change: the model must copy every user
sentence it relies on into a list, naming the conversation each comes from. A
label passes only if every quote is found (case- and whitespace-folded) in that
conversation's user turns, checked by the script. The same two models label all
60 pairs independently (`h15-lme-timing-quotes-v1`). A pair's gold is
*identified* when both give the same non-UNKNOWN label and both pass the check.

Analysis: `scripts/analyze_h15.py`, committed with this file.

## Predictions

- **H15a -- the annotators are valid on constructed answers:** each annotator's
  verdict matches construction on at least 95% of the 450 constructed answers
  and on at least 90% of every template.
- **H15b -- they agree on sealed answers:** their verdicts agree on at least 90%
  of the 90 native answers and at least 90% of the 225 common-reader answers.
- **H15c -- the native readers' advantage survives:** by consensus, Cognee's
  reader is credited on at least 35 of 45 and Hindsight's on at least 20.
- **H15d -- the common reader stays below:** by consensus every common-reader
  store is credited on at most 12 of 45, and both native readers exceed the
  highest.
- **H15e -- the strict count is close to the consensus:** of the 66 native
  answers the strict rule passes, at most 3 are credited by neither annotator;
  of the 24 it fails, at most 12 are credited by both.
- **H15f -- the real-data gold is rarely identifiable:** fewer than 15 of the 60
  pairs are identified, and fewer than 10 as HELD.

## What follows from each outcome

If H15a fails for an annotator, its verdicts are not used to count anything and
the paper says so; if it fails for both, the paper keeps the strict counts,
labelled as token counts, and reports the failed validation. Counts are
reported with both the consensus and the either-annotator reading. If H15f
holds, the real-data valid-time column stays an agreement with an assumed gold,
and scores on the identified pairs are reported as a diagnostic, not as
accuracy.

## Outcomes (recorded 2026-10-24 KST; `scripts/analyze_h15.py`)

The analysis script's pairing key first used `(set, source, template,
case_id)`; case ids repeat across history cells, so it now also keys on the
question text. Nothing else in the script changed, and no run was repeated.

| Prediction | Outcome |
|---|---|
| H15a: each annotator right on >= 95% of constructed answers, >= 90% per template | **holds** -- `gpt-4o` 450/450; `gpt-5.4` 448/450 (it reported no value for 2 of 45 `x, not y`); every other template 45/45 for both, including `It was not x.` |
| H15b: agreement >= 90% on native and common-reader answers | **holds** -- 89/90 native, 225/225 common |
| H15c: consensus credits Cognee's reader >= 35/45, Hindsight's >= 20/45 | **holds** -- 42 and 29 (strict count 41 and 25; either annotator 42 and 30) |
| H15d: every common-reader store <= 12/45, both native readers above the highest | **holds** -- 8 (Cognee chunks), 8 (Hindsight recall), 2 (Graphiti), 0 (Mem0), 0 (LangMem), identical to the strict count |
| H15e: <= 3 strict passes credited by neither; <= 12 strict failures credited by both | **holds** -- 0 and 5 (1 Cognee, 4 Hindsight: right answers that also state the correction or an earlier value) |
| H15f: fewer than 15 of 60 pairs identified, fewer than 10 as HELD | **holds** -- 0 identified. `gpt-5.4` labels all 60 UNKNOWN; `gpt-4o` labels 3 HELD and 10 CHANGED, with verified quotes for 59 of 60 labels, but no pair has two matching labels |

Reading: the strict count was not misleading on these answers -- no answer it
credits is rejected by either annotator, and the annotators credit 5 right
answers it failed. The comparison the paper draws (own readers far above any
retrieval layer or the common reader) holds under a validated reading. The
annotators are models checked on constructed answers, not people. The
real-data valid-time gold is identified for none of the 60 pairs, so that
column measures agreement with an assumed gold and nothing more.
