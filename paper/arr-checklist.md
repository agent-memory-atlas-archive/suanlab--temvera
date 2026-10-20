> **Superseded (2026-10-21).** This ACL Rolling Review checklist draft is kept for the record only. The current
> manuscript is `paper/main.tex` (ICDE 2027 EAB); its wording and numbers take
> precedence over anything here, which may be stale (e.g. LongMemEval described as
> "human-written"; its sessions are LLM self-chat edited by annotators).

# Responsible NLP Research checklist — draft answers

> **Superseded (2026-09-06). Not required for this submission.** This was
> drafted when ARR was the target; decision D-014 moved the paper to PVLDB's
> Experiment, Analysis & Benchmark track, which asks for no such checklist. It
> is kept because its answers are an accurate description of the artifact and
> are reusable, not because anything here must be filed. The live requirements
> are in [../docs/submission-checklist.md](../docs/submission-checklist.md).

## A. Limitations and risks

**A1. Did you describe the limitations of your work?** Yes — unnumbered
`Limitations` section, as ARR requires. It states that histories are synthetic
with hand-specified operation profiles, that all runs use a single backbone with
non-bit-reproducible LLM extraction, that our one same-protocol replication
moved a small-denominator category by 0.125 (so no expiry conclusion is drawn),
and that the deletion result rests on a single seeded history.

**A2. Did you discuss any potential risks of your work?** Yes — `Ethics
Statement`. The load-bearing risk is user-facing: an assistant asked
conversationally to forget something may not do so, which matters for
deployments treating conversational deletion as effective.

**A3. Do the abstract and introduction summarise the paper's claims?** Yes. The
abstract states the budget dependence of the headline metric and that we claim
no novelty for bitemporal modelling, deterministic supersession, or forgetting
evaluation.

## B. Use of existing artifacts

**B1. Did you cite the creators?** Yes — Mem0, Graphiti/Zep, LangMem, MemGPT/Letta,
HippoRAG 2, Hindsight, LongMemEval, LoCoMo, ForgetEval, MemoryAgentBench, TOKI,
MemStrata, MINJA, MemLineage, A-MemGuard, MemIncept are cited.

**B2. Did you discuss the licence/terms?** Partially, and the honest answer is
that one is unresolved. Mem0 and Graphiti are Apache-2.0; ForgetEval is MIT;
LongMemEval's *code* is MIT but its *benchmark data* licence is unclear, which
we state in the Ethics Statement rather than assume permission. **Action before
submission:** decide whether to seek clarification from the LongMemEval authors
or to further hedge the external-validity section.

**B3. Is your use consistent with intended use?** Yes. All three systems are
used through their public APIs for evaluation, which is a normal research use.
The benchmark is used for evaluation, its stated purpose. We do not redistribute
any third-party dataset or source tree.

**B4. Did you discuss steps taken to protect personal information?** Yes. The
generated workloads are fully synthetic; person names are drawn from a fixed
list of common given names and refer to no real individual. LongMemEval
conversations are used locally and never committed — the one run directory whose
embedded database contained benchmark text is deliberately excluded from the
artifact.

**B5. Did you document the artifacts?** Yes — dataset card, model-applicability
card, architecture and evaluation-plan documents, and an evidence ledger linking
every claim to a sealed run.

**B6. Did you report dataset statistics?** Yes — grid dimensions (5 seeds × 2
scales × 2 profiles = 20 cells, 484 cases per system), per-category case counts
in the results table, and instance counts per LongMemEval question type.

## C. Computational experiments

**C1. Did you report the number of parameters and compute budget?** Partially.
No model is trained; all compute is API inference plus a CPU-only embedding
model for one ablation. Wall-clock is reported in the reproduction guide
(roughly 1–2 h for a 20-cell grid; 35–40 min per instance on the distractor
split). **Action:** add total token/cost accounting — the paper currently
describes one extractor as "stronger" without a cost measurement, and an earlier
draft's "15× costlier" claim was unsourced and has been removed.

**C2. Did you report experimental setup, including search over hyperparameters?**
Yes. Backbone `gpt-4o-mini` at temperature 0, embedder
`text-embedding-3-small`, retrieval budget k=5 with a reported sweep over
k ∈ {1,2,3,5}. No hyperparameter search was performed; where a configuration
choice could have driven a result — Graphiti's retrieval recipe, Mem0's history
database isolation — both settings were run and both are reported.

**C3. Did you report descriptive statistics, and are results from single or
multiple runs?** Yes. Case-weighted rates with denominators and Wilson 95%
intervals; macro means are also given where they differ. Each cell is run once,
which we state; the Mem0 and Graphiti reruns provide the only same-protocol
replication and its variance is reported.

**C4. Did you report the packages used?** Yes — Mem0 `0.1.118`, Graphiti
`0.29.2` on Neo4j 5.26, LangMem `0.0.30`, and the pinned Python environment. The
LangMem run uses a separate virtualenv because it requires `openai>=3` while the
other two require `openai==1.x`; this is documented rather than silently
resolved.

## D. Human annotators

Not applicable. No human annotators or participants were used. A preregisterable
human audit protocol ships with the artifact but was not run, and no
human-effectiveness claim is made.

## E. Use of AI assistants

**Disclose fully.** An AI coding assistant was used throughout: to implement the
harness and adapters, to run and analyse experiments, to draft prose, and to
simulate an adversarial review whose findings prompted the corrections and
retractions described in the paper. All reported numbers derive from sealed,
checksum-verified runs that can be recomputed from the artifact, and every claim
is traceable to an evidence-ledger row. **Action before submission:** confirm the
exact disclosure wording ARR expects for the submission cycle, and ensure the
author(s) have independently verified the claims they are signing for — assistant
involvement does not transfer responsibility for correctness.

## Remaining actions before submission

1. Download `acl.sty` and `acl_natbib.bst` from the ACL style-files repository,
   swap the two preamble lines flagged in `main.tex`, and set
   `\bibliographystyle{acl_natbib}`. Re-check the 8-page content limit
   (Limitations, Ethics and References do not count toward it).
2. Resolve or further hedge the LongMemEval data-licence question (B2).
3. Add token/cost accounting for the extractor comparison (C1).
4. Confirm the ARR anonymity period and whether an arXiv preprint is compatible
   with the intended commitment venue.
5. Re-read for anonymity: the coined system name has been replaced with a
   neutral phrase, but verify no repository URL, institution, or funding
   acknowledgement is reintroduced.
