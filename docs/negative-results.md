# Negative and contradictory results

## NR-001 — Procedural judge-free lifecycle novelty is unavailable

ForgetEval commit `b6053b7` already contains seeded template generation for
supersession, release/decay, amnesia, purge, and drift, scored with exact
substring conditions over top-k retrieval. Temvera must not claim that the
combination of procedural generation and judge-free lifecycle evaluation is
new. See evidence E-005 and E-013.

## NR-002 — State-level decay smoke test loses recall

The two-case mechanism smoke test (`temvera decay-smoke`) returned recall@1 of
1.0 for rank-only decay and 0.5 for state-level threshold decay; both selected
zero marked-stale items. State-level decay abstained on the old but still
relevant case. This does not estimate population performance, but it falsifies
the assumption that thresholding belief state is automatically better. The
full preregistered experiment must vary age, relevance, change rate, and
threshold, and report recall, stale use, and abstention separately.

The preregistered 384-cell mechanism sweep strengthened this warning. On the
96 changed-fact cells, rank-only selected relevant evidence 56 times and stale
evidence 40 times; state-level selected relevant evidence 41 times and stale
evidence 55 times. On stable-old facts, state-level abstained in 41 of 96 cells
while rank-only retained all 96. These are synthetic mechanism counts, not
population estimates.

## NR-003 — Initial channel ablation has no discriminative power

The fixed 48-case generated-history run produced Evidence Recall@5 = 1.0 for
all five channels and for every single-channel removal.

> **Correction (2026-10-22).** The sentence above is wrong in one cell: the
> sealed run `channel-ablation-v0`, recomputed with the current code, gives
> 0.792 when the temporal channel is removed. Four of the five removals stay at
> 1.0, so the fixture still cannot identify most channels; the original text is
> kept so the error remains visible. Found by the paper-claim coverage sweep.
 Entity identifiers and
attributes occur verbatim in queries, while several channels return the same
beliefs. The result cannot support a hybrid-retrieval contribution. The next
suite must separately include alias/entity mismatch, lexical paraphrase,
valid-time distractors, and provenance-only graph hops; each category needs a
named channel necessity oracle.

Follow-up: the five-category hard fixture now passes with all channels and each
category fails when its designated channel alone is removed. This establishes
mechanism identifiability for the harness, not external validity or superiority
of the chosen implementations.

## NR-004 — Calibrated fusion adds no held-out benefit

After removing two leakage bugs (temporal validity treated as a retriever and
graph ranking returning its input seeds), channel weights were calibrated on 16
development examples and frozen before evaluation on 16 disjoint surface-form
variants. Grid search selected equal `0.5` weights for exact, lexical, vector,
and graph. Fixed equal-weight RRF and calibrated fusion both achieved
evidence recall at the per-case budget of 1.0. This mechanism fixture provides
no evidence that learned fusion complexity is useful; larger naturalistic
feedback is required before revisiting it.

## NR-005 — Provenance cannot defend a compromised trust root

The adaptive governance probes reject cross-tenant replay, signed-claim
tampering, and expired-signature replay. A malicious claim freshly signed by a
configured trusted tool is accepted and can authorize the action. This is an
expected boundary, not a parser bug: provenance establishes origin and
integrity, not the honesty of the signer. Deployment requires key revocation,
tool compromise detection, least authority, and possibly multi-party approval
for high-impact actions.

## NR-006 — Lexical mutation matching fails most ForgetEval amnesia cases

The pinned ForgetEval generator (`b6053b7`, scale 20, seed 42, four
distractors) produced 100 cases. Temvera's deterministic lexical compatibility
adapter passed 85: 20/20 each for supersession, decay, purge, and drift, but
only 5/20 for amnesia. Best-match release cannot reliably remove all facts
about a subject when the request and stored facts share little vocabulary.
This result rules out presenting the lexical adapter as a general lifecycle
solution; semantic entity resolution or explicit subject identity is required.
See `experiments/runs/forgeteval-temvera-lexical-seed42/` and E-026.
