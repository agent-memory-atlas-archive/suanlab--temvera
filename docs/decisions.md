# Decision log

## D-001 — Preserve raw events

- **Status:** accepted
- **Decision:** Raw observations and interactions are append-only. Summaries,
  beliefs, and indexes are derived artifacts.
- **Reason:** Enables reprocessing, audit, deletion propagation, and comparison
  of extraction policies.

## D-002 — Model two time axes

- **Status:** accepted
- **Decision:** Separate valid/event time from record/transaction time.
- **Reason:** Current-state overwrites cannot answer what was true versus what
  the agent knew at a past point.

## D-003 — Start with dual substrates

- **Status:** accepted
- **Decision:** Implement a Git-native research substrate and a relational
  bitemporal oracle.
- **Reason:** The relational implementation prevents the project from declaring
  Git superior without correctness and performance evidence.

## D-004 — Temvera working name

- **Status:** superseded by D-007
- **Decision:** Use Temvera as the working name, pending formal clearance.
- **Reason:** Preliminary web search found no direct same-category collision,
  but package, domain, and trademark clearance is incomplete.

## D-005 — Immutable metadata does not justify immutable sensitive payloads

- **Status:** accepted; narrows D-001
- **Decision:** Keep non-sensitive event metadata and deletion receipts
  append-only, but do not claim physical purge while private payload remains in
  the JSONL ledger. A release design must make payload erasure independently
  verifiable, for example through encrypted payload separation and key
  destruction.
- **Reason:** Audit history and deletion lineage are required, but retaining the
  content being deleted would violate the research program's security goal.

## D-006 — Keep encryption keys outside the Git substrate

- **Status:** accepted for the experimental protected profile
- **Decision:** Encrypt subject, attribute, value, and source references with a
  per-belief AES-256-GCM key. Commit metadata and ciphertext, never keys. A
  cryptographic purge destroys the key and records its hash in a non-sensitive
  receipt.
- **Reason:** Rewriting distributed Git history cannot prove removal from
  clones. If a key was never committed, key destruction makes retained
  ciphertext unusable without destroying the audit log.
- **Limit:** This is not proof of deletion from RAM, swap, upstream sources, or
  unauthorized key backups.

## D-007 — Retain Temvera as the project name

- **Status:** accepted 2026-07-16 by user decision
- **Decision:** Retain Temvera as the project name for repository metadata and
  future release preparation.
- **Reason:** The preliminary collision screen found no exact same-category
  use. This is a naming decision, not legal trademark clearance or reservation.

## D-008 — License repository-authored material under Apache-2.0

- **Status:** accepted 2026-07-16 by user decision
- **Decision:** Apply Apache-2.0 to repository-authored code, documentation,
  fully synthetic fixtures, and accepted locally generated experiment outputs.
- **Reason:** A permissive license with an explicit patent grant supports
  reproducible research and reuse. Third-party artifacts retain their own
  licenses and are not relicensed or redistributed.

## D-010 — Authorize external-system reproduction under API-only resources

- **Status:** accepted 2026-07-16 by user decision (systems-paper plan approval)
- **Decision:** Permit LLM-API use to reproduce external memory systems
  (Mem0, Zep/Graphiti) under identical budgets, and seal their API-response
  transcripts for reproducibility. Only fully synthetic Temvera histories are
  sent; no private or redistribution-restricted data. Third-party system source
  trees are run for comparison, not relicensed or redistributed.
- **Reason:** Identical-budget external comparison is the systems paper's
  largest gap; API-only resources make Mem0 and Zep/Graphiti feasible without
  GPUs. Narrows the "external systems unexecuted" bound of D-009.
- **Limit:** GPU-bound baselines (A-MemGuard, MemIncept, learned rerankers) stay
  out of scope; security remains a deterministic mechanism study.

## D-011 — Authorize learned dense-retrieval baseline model download

- **Status:** accepted 2026-07-16 by user decision (systems-paper plan approval)
- **Decision:** Permit downloading a public CPU/ONNX embedding model (e.g.
  `bge-small`) to restore the learned dense-retrieval baseline excluded in E-038.
- **Reason:** fastembed runs on CPU, so the learned-vector channel can be
  evaluated without GPUs. Lifts the learned-model portion of D-009's deferral.
- **Limit:** DOI/public-archive publication remains deferred under D-009 until
  separately authorized at camera-ready.

## D-009 — Bound the remaining evaluation scope

- **Status:** accepted 2026-07-16 by user decision
- **Decision:** Publish the human-audit protocol without recruiting
  participants; keep learned-model download and public archive/DOI publication
  deferred until separately authorized.
- **Reason:** These actions require ethics, external model, or publication
  authority beyond the local deterministic artifact.

## D-012 — No upstream bug filing; human audit study is future work

- **Status:** accepted 2026-08-12 by user decision
- **Decision:** Do not file the Mem0 defect upstream. Keep the analysis in
  `docs/upstream-bug-mem0-update-keyerror.md` as internal evidence for E-065,
  which explains why the reported Mem0 numbers are conservative. The human
  audit study (RQ4) is not run for this submission and is reported as future
  work; D-009's protocol-only scope therefore stands unchanged.
- **Reason:** The defect report is a routine, non-security OSS issue whose
  filing is optional, and the intermittent reproduction weakens it. Ethics
  review or a documented exemption plus a pilot and power analysis cannot
  responsibly fit before the ICLR deadline, and the protocol itself requires
  that sequence before recruitment.
- **Limit:** This is a scope decision for one submission, not a finding that
  the defect is unimportant or that the study is infeasible later.

## D-013 — Retarget the submission from ICLR to COLM

- **Status:** accepted 2026-08-13 by user decision
- **Decision:** Target COLM 2027 as the primary venue, with NeurIPS Datasets &
  Benchmarks as the fallback. Do not submit to ICLR 2027.
- **Reason:** A five-reviewer simulation was unanimous that the work has no
  learning contribution — nothing is trained, fine-tuned, or probed — and that
  ICLR's pool would score a measurement study of two libraries in the low 4s
  regardless of how well it was executed (predicted accept probability 8–10%,
  versus 40–50% at COLM). COLM explicitly welcomes empirical studies of LM
  systems, evaluation methodology, and negative results, which is exactly what
  this is. The venue objection survives every presentation fix, so retargeting
  is worth more than any amount of polishing for ICLR.
- **Consequence:** The September ICLR deadline no longer binds. That removes the
  pressure that would have forced shipping the protocol defects found in review
  (budget dependence, deletion asymmetry, unmatched grids) as-is.
- **Limit:** This is a venue decision, not a judgement that the corrected
  findings are weaker; several corrections made the surviving claims narrower
  and better supported.

## D-014 — Target VLDB Experiments, Analysis & Benchmark track

- **Status:** accepted 2026-08-14 by user decision; supersedes D-013 (COLM)
- **Decision:** Target the PVLDB **Experiments, Analysis & Benchmark (EA&B)**
  track, using its monthly rolling deadlines (VLDB 2027 closes 2027-03-01). No
  arXiv preprint will be posted.
- **Reason:** EA&B matches this work on the two dimensions where every other
  venue penalised it. It *requires* releasing all experimental data and software
  and submitting to the PVLDB Reproducibility Committee, which turns our sealed
  runs, checksums, and evidence ledger from a footnote into a scored criterion;
  and it exists specifically for rigorous comparison of existing systems, so
  "we claim no novelty" stops being a liability. The 12-page limit also leaves
  room for the depth reviewers asked for, against roughly 6.5 pages of current
  content.
- **Known gaps, accepted as work:** three systems where DB reviewers expect
  more; no scale, latency, or cost dimension; and no formal statement of which
  fragment of bitemporal query semantics each system implements.
- **Known risk:** several of our causal explanations bottom out in LLM
  extraction quality rather than data-management design, which a DB reviewer may
  read as off-topic. The mitigation is to frame the extraction layer as the weak
  link in the pipeline that populates a temporal store, and to say so explicitly
  rather than let a reviewer discover it.
- **Consequence:** our own substrate must be demoted from a compared system to a
  reference implementation, since an EA&B paper comparing systems where one is
  the authors' own invites a conflict-of-interest reading.

## D-015 — Submit to ICDE 2027 (EAB, round 2); keep PVLDB as the fallback

- **Status:** accepted 2026-10-02 by user decision; supersedes D-014 as the
  submission target. D-014's reasoning about fit still holds and is why PVLDB is
  the fallback rather than abandoned.
- **Decision:** Submit to the **ICDE 2027 research track as an Experimental,
  Analysis, and Benchmark (EAB) paper**, second round, due **2026-11-11
  17:00 Pacific**. Rebuttal 2027-01-08 to 01-15; notification 2027-02-10;
  accept/reject only, no revision.
- **Reason:** ICDE's EAB category is structurally the closest match to PVLDB
  EA&B on the list the author was choosing from: a dedicated EAB category,
  artifacts that are *mandatory* for EAB ("No exceptions"), single-blind review
  so the public repository can stay as it is, and the same 12-page limit
  excluding references. SIGMOD was rejected for double-blind review against an
  already-public repository whose README carries the paper's title; EDBT for a
  five-day deadline and a lower tier.
- **Why this order and not PVLDB first:** the two cannot run concurrently
  (PVLDB reviews return ~mid-December, after ICDE closes). Submitting to ICDE
  first keeps PVLDB available: an ICDE rejection on 2027-02-10 still leaves the
  PVLDB volume 20 final deadline of 2027-03-01 (abstract 2027-02-25). The
  reverse order would spend PVLDB, whose rejection carries a one-year embargo.
- **Cost accepted:** ICDE offers no revision, which PVLDB would have. The extra
  ten days over a 1 November PVLDB submission are spent on the experiments the
  August gap analysis asked for — the LongMemEval real-data workload and the
  order-of-magnitude scale sweep — now unblocked by a working API key.
- **Fallback:** the PVLDB-formatted manuscript is tagged `pvldb-manuscript`.
- **ICDE-specific obligations:** the title must *start* with
  `[Experiment, Analysis, and Benchmark]`; use of AI-generated content (text,
  figures, code) must be disclosed in the acknowledgments, which do not count
  toward the page limit; IEEE conference format; submission through CMT.
