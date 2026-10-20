# Preregistration: retroactive corrections (H6)

Committed before any run of `experiments/configs/external-corrections-*.json`
exists. The analysis is `scripts/analyze_corrections.py`, committed with this
file; the runs will be `external-corrections-mem0-v1` and
`external-corrections-graphiti-v1`. Whatever the results, they are reported.

## Why

Every history so far was recorded in valid-time order. A retroactive correction
-- "her home city from 3 January until 5 February was actually Birchbury, not
Ashford", recorded weeks later -- is the case that separates valid time from
transaction time, and the one a data-management reviewer will ask about.

## Design

Mem0 and Graphiti (hybrid retrieval, as cited), `gpt-4o-mini`, k = 5,
forward-checkpoint replay. 8 subjects x 3 revisions x 10 seeds, revision-only
operations, distinct natural values (`natural_pools: large`). Each subject
receives a correction with probability 0.5, recorded 25 days after its last
revision, replacing one earlier, already superseded value over its whole
interval. Subjects without a correction are the within-run control.

Question groups (all asked after the correction was recorded):
`corrected` (valid time inside the corrected interval), `present_corrected`
and `present_uncorrected` (current value at the end of the history), and
`past_uncorrected` (an ordinary superseded interval, for contrast).

## Predictions

- **H6a -- consolidation applies a correction to the present.** Mem0's exact
  rate on `present_corrected` is lower than on `present_uncorrected` by at least
  0.10. Mechanism: an update-oriented extractor reads "was actually X" as a new
  current value. Falsified if the difference is below 0.10 or reversed.
- **H6b -- retention without filtering.** Graphiti's exact rate on `corrected`
  is at most 0.10: it keeps the replaced value and the correction and returns
  both. Falsified above 0.10.
- **H6c -- recency helps a consolidating store on the corrected interval.**
  Mem0's exact rate on `corrected` is higher than on `past_uncorrected`,
  because the correction is the most recent statement about that interval.
  Falsified if equal or lower.

Counts are small (about 40 corrected subjects), so each comparison is read with
Wilson intervals and stated as a direction, not a rate.

## Outcome (added 2026-10-20, after the runs; the text above is unchanged)

All three predictions held. Mem0, current value: 35/35 without a correction,
1/45 with one (drop 0.978; H6a). Graphiti, corrected interval: 1/78 = 0.013
(H6b). Mem0, corrected interval 69/78 against 0/70 for ordinary superseded
intervals (H6c). A check added only after reading these results, and so not
preregistered: for 41 of the 45 corrected subjects, Mem0's current value appears
in no later answer about that subject (Graphiti: 14 of 45).
