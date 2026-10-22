> **Superseded (2026-10-21).** This ICLR 2027 working draft is kept for the record only. The current
> manuscript is `paper/main.tex` (ICDE 2027 EAB); its wording and numbers take
> precedence over anything here, which may be stale (e.g. LongMemEval described as
> "human-written"; its sessions are LLM self-chat edited by annotators).

# Temporal Fields Are Not Temporal Correctness: Measuring Bitemporal and Deletion Semantics in Deployed Agent Memory

> Full working draft for ICLR 2027 (abstract 2026-09-19, paper 2026-09-24).
> Every result sentence carries an evidence-ledger ID; numbers come from sealed,
> checksum-verified runs under `experiments/runs/`. Sections still gated on work
> not yet done are marked **PENDING**. Positioning follows
> `docs/contribution-statement.md`, which was downgraded after the 2026
> prior-art sweep (E-059–E-061).

## Abstract

Long-running agents accumulate facts that change, expire, and must sometimes be
deleted. Answering *what was true then* and *what did the agent know then*
requires distinguishing valid time from transaction time, and honouring deletion
across every store a query can reach. Recent systems advertise exactly these
capabilities: temporal graphs expose validity fields, memory stores record
update history, and 2026 work formalises bitemporal operators for agent memory.
We ask whether those features deliver the semantics they name.

We build a deterministic lifecycle generator whose ground truth is computed by
an oracle cross-checked against an independent SQLite implementation, render the
same histories into natural language, and replay them into two deployed systems
under identical budgets with forward-checkpoint transaction-time replay. The
oracle is exact in all 90 conditions of a 10-seed grid, while non-temporal
baselines degrade with churn. Mem0 answers transaction-scoped current queries
well (0.949) but collapses on historical valid time (0.346), expiry (0.062), and
purge (0.121); Graphiti preserves temporal edges — evidence recall 0.944 — yet
its default retrieval ignores them, giving exact 0.223 with valid-time and
expiry at 0.000. Enabling Graphiti's own valid-time filter buys precision by
discarding evidence rather than fixing semantics, and a 15× costlier extractor
leaves the decisive categories unchanged. A residual scan shows purged payloads
persist inside both systems' retrieval-reachable stores, whereas our substrate's
rebuildable projections are clean and its only residual sits in an append-only
ledger no query path reads. The asymmetry reproduces on human-written
LongMemEval conversations.

We do not claim bitemporal modelling, deterministic supersession, or forgetting
evaluation as novel — all are prior art (E-059–E-061). The contribution is
measurement: a reproducible harness and the finding that temporal *fields* are
not temporal *correctness*.

## 1. Introduction

An agent that remembers must also revise, expire, and forget. Two questions
recur: *what was true at time t* (valid time) and *what did the system know at
time t* (transaction time). Current-state stores conflate them, and deletion is
harder still — a value removed from a serving index may survive in a history
table, a vector store, or a raw episode log, ready to resurface.

These needs are recognised. Graphiti attaches creation, validity, invalidity and
expiry timestamps to graph edges (E-024); Mem0 records add/update/delete history
beside a mutable vector store (E-025); Hindsight combines invalidation archives,
histories, audit logs and derived-record cleanup (E-032); and 2026 work makes
the temporal model explicit, from a graph-native bitemporal store to TOKI's
bitemporal operator algebra and MemStrata's bi-temporal ledger with
deterministic supersession (E-059, E-060).

Given that, the open question is not *whether to model time* but **whether the
modelling produces correct answers under the operations agents actually
perform**. We answer it by measurement:

1. a deterministic lifecycle generator with independently computed ground truth,
   cross-checked by a second oracle implementation;
2. a natural-language rendering of those histories so opaque systems can be
   scored against the same truth;
3. forward-checkpoint transaction-time replay, so an `as-of` query is answered
   from a store that has seen only what was known by then;
4. a residual scan that asks where a purged payload physically survives.

**Contributions.** (i) An identical-history comparison of two deployed memory
systems showing two distinct, previously unquantified failure modes. (ii) A
cross-store deletion-completeness measurement, which the closest prior systems
describe as a feature but do not measure. (iii) A reproducible, sealed harness,
including preserved negative results and two retracted measurements.

## 2. Related Work

**Temporal modelling is prior art.** A graph-native bitemporal memory store
(arXiv:2607.26520) keeps valid- and transaction-time intervals with
point-in-time retrieval, and TOKI (arXiv:2606.06240) defines bitemporal
operators over a dual-row schema with released code (E-059). MemStrata
(arXiv:2606.26511) pairs a bi-temporal ledger with a deterministic
(subject, relation, object) supersession rule and reports stale-fact rate as its
headline metric (E-060). We therefore claim none of these.

**Forgetting evaluation is prior art.** ForgetEval generates seeded lifecycle
cases with deterministic substring scoring across supersession, decay, amnesia,
purge and drift (E-005, E-013); MemoryAgentBench evaluates selective forgetting
among four competencies (E-061). Springdrift already combines append-only
memory, auditability and git-backed recovery (E-009), which retires any
"first git-native auditable memory" framing.

**Deployed systems.** Mem0, Zep/Graphiti, MemGPT/Letta, HippoRAG 2 and Hindsight
form the baseline landscape (E-018–E-021, E-027, E-032). **Security.** MINJA
shows query-only poisoning (E-008); MemLineage proposes lineage-based action
gating (E-010); A-MemGuard and MemIncept are current defence and adaptive-attack
baselines (E-030, E-031, E-034).

**What is left.** No prior work we found measures, under one controlled history,
both bitemporal answer correctness *and* where deleted content physically
survives across a system's derived stores. The literature review is
single-reviewer with a deterministic 10% rescreen; searches, exclusions and
rescreens are logged and frozen.

## 3. Design

Principles: raw events are immutable and interpretations derived; valid time is
distinct from transaction time; current truth is a view over history; retrieval
is scoped before ranking; every derived memory cites evidence; untrusted content
is data, never policy; indexes are rebuildable from the ledger.

- **Event ledger.** Typed `MemoryEvent`s (`ingest`, `reconfirm`, `supersede`,
  `expire`, `purge`), append-only, over JSONL or a git transaction adapter.
- **Bitemporal oracle.** `LifecycleOracle` folds events into beliefs;
  `SqliteBitemporalOracle` is an independent second implementation used purely
  as a correctness cross-check, not an operational baseline.
- **Disposable projections.** Exact, lexical, hashing-vector, learned-vector and
  graph indexes rebuilt from materialised beliefs; RRF fusion, then validity,
  authority and poisoning gates; evidence-backed memory packets.
- **Deletion.** Purge tombstones with receipts, plus an encrypted-payload
  profile whose per-belief key destruction is verified after a git clone
  (D-005, D-006, E-033).
- **Provenance gate.** Signed, tenant-scoped ingestion quarantine separating
  write acceptance from sensitive-action activation.

## 4. Experimental Setup

**Workload.** A seeded generator emits typed histories over entity/attribute
state machines with configurable reconfirm/expire/purge probabilities. Query
truth is computed by the oracle independently of any retrieval ranking.

**Rendering.** Histories are rendered to dated conversational turns. Because the
generator's synthetic tokens (`entity-000`, `place-38`) collapse under a
semantic embedder — leaving systems unable to tell entities apart — an injective
relabelling maps them to distinct natural names. The relabelling preserves
oracle semantics exactly (verified by test) and doubled Mem0's measured exact
accuracy, isolating tokenisation from temporal semantics (E-052).

**Replay.** Transaction time is monotonic, so turns are ingested in recorded
order and every query is answered at the checkpoint matching its transaction
time. This costs O(turns) per cell and, unlike single-pass ingestion, actually
tests whether a store can answer as of a past point.

**Scoring.** Deterministic: a returned answer must contain the expected value(s)
and no superseded value, mirroring ForgetEval's substring scoring (E-013). We
report exact-state accuracy, evidence recall, stale-use rate and abstention.

**Systems.** Internal baselines (append-only, full/recent context, BM25,
last-write-wins) and the oracle; external systems Mem0 `0.1.118` and Graphiti
`0.29.2` on Neo4j 5.26, both with `gpt-4o-mini` at temperature 0 and
`text-embedding-3-small`. Runs are sealed with canonical config, environment,
source hash and per-file checksums.

## 5. Results

### 5.1 The oracle is exact; non-temporal baselines are not
Across 3 profiles × 3 scales × 3 revision counts × 10 seeds (90 conditions), the
oracle held exact/recall/stale at 1/1/0 in every condition (E-049). Baseline
means over the same grid: last-write-wins 0.603 exact / 0.397 stale, recent
context and BM25@1 0.576 / 0.424, append-only and full context 0.272 / 0.624
(with 0.915 recall — they retrieve the evidence but cannot choose among
versions). Under the high-churn profile append-only falls to 0.255 exact with
0.662 stale. A separate operation suite isolates purge, expiry-boundary,
transaction-as-of and valid-time categories (E-043).

### 5.2 Deployed systems: two distinct failure modes
Under identical histories (Table 1), **Mem0** consolidates to a single current
value: it is strong on transaction-scoped current queries (0.949) but weak on
historical valid time (0.346) and near-total failures on expiry (0.062) and
purge (0.121); overall exact 0.607, degrading with scale from ≈0.70 to ≈0.52
across 48 cells (E-053). **Graphiti** does the opposite: it retains temporal
edges and reaches 0.944 evidence recall, but its default retrieval does not
filter by validity, so it returns superseded facts alongside current ones —
overall exact 0.223, stale-use 0.530, with valid_time and expiry at **0.000**
across 20 cells with narrow 5-seed intervals, replicated in an independent
`revision_only` profile (E-062).

| Category (exact) | Mem0 | Graphiti | Oracle |
|---|---|---|---|
| transaction_as_of | 0.949 | 0.470 | 1.000 |
| valid_time | 0.346 | 0.000 | 1.000 |
| expiry_boundary | 0.062 | 0.000 | 1.000 |
| purge | 0.121 | 0.036 | 1.000 |
| **overall exact** | 0.607 | 0.223 | 1.000 |
| evidence recall | 0.649 | 0.944 | 1.000 |
| stale-use | 0.379 | 0.530 | 0.000 |

Enabling Graphiti's own valid-time filter raises exact to 0.318 and cuts
stale-use to 0.360, but collapses recall from 0.873 to 0.318 — precision bought
by discarding evidence, with valid_time still 0.093 and expiry 0.067 (E-057).
Two structural limits cap it: `invalid_at` is frequently absent on superseded
edges and occasionally contradictory (`invalid_at <= valid_at`), and
`created_at`/`expired_at` record wall-clock ingestion rather than the history's
transaction time, so they cannot express an `as-of` bound at all. The ceiling is
architectural, not an extraction artifact: swapping `gpt-4o-mini` for `gpt-4o`
leaves valid_time (0.111 → 0.111) and expiry (0.000 → 0.000) unchanged (E-058).

### 5.3 Deletion completeness (headline)
After the same ingested purge, our substrate's rebuildable projections —
Markdown, lexical, vector, graph — contain **zero** occurrences of the purged
payload; its only residual (3) is the append-only audit ledger, a documented
limitation (D-005) addressed by the encrypted profile's key destruction (E-033).
Mem0 retains 14 occurrences (exposed memories 2, vector store 2, SQLite history
10) and Graphiti 27 (edge facts 5, entity nodes 13, raw episode bodies 9)
(E-056). The claim is *where* deleted content survives — an audit log no query
path reads, versus serving indexes a later query can resurface — not the integer
magnitudes, which are substring counts over differently shaped stores.

### 5.4 Retrieval channels
A hard fixture isolates one necessary channel per category (E-016). A learned
dense channel resolves held-out synonyms at recall@1 1.0 where the
dependency-free hashing channel scores 0.0, quantifying that channel's
alias-table-only design (E-050). Calibrated fusion gave no held-out gain over
fixed RRF (E-022), and state-level decay did not dominate rank-level decay
(E-014).

### 5.5 External validity
On human-written LongMemEval conversations the same asymmetry appears. Across
all six question types (60 instances, 10 each), mean gold-token recall was
knowledge-update 0.724, single-session-user 0.622, single-session-preference
0.314, multi-session 0.287, temporal-reasoning 0.221, single-session-assistant
0.151 (E-064) — replicating a smaller run that gave 0.809 vs 0.188 for the two
extreme types (E-063). Retrieval quality tracks how much temporal or
cross-session reasoning a question demands rather than recency alone: simple
within-session user recall is nearly as strong as current-value questions, while
multi-session and assistant-stated facts are poorly retained. Scoring is
deterministic substring/token presence over retrieved memories and is
deliberately **not** LongMemEval's GPT-4o-judged QA metric (E-036); n=10 per
type on the oracle split, which has no distractor sessions.

Distractor pressure lowers the absolute numbers without removing the pattern.
On the `_s` split, where each instance carries 42--52 sessions of which most are
distractors, knowledge-update recall falls 0.724 to 0.619 and temporal-reasoning
0.221 to 0.167, so the ratio between them is preserved (3.3x to 3.7x; E-066).
Only three instances per type were run at roughly 35--40 minutes each, so the
point estimates are weak and we rely on the preserved ordering rather than the
values.

These numbers are conservative for Mem0: during ingestion it silently dropped 15
memory `UPDATE`/`DELETE` actions across these 60 conversations, a defect we
traced to an unvalidated id lookup swallowed by a broad exception handler
(E-065). Dropped updates leave superseded values in place, so the true system
would score no worse than reported.

### 5.6 Provenance security
Signed, tenant-scoped gating admitted 3/4 attacks as inert data while activating
0/4, with benign utility preserved (E-017) — but it fails once a trusted signer
is compromised: provenance proves origin, not signer honesty (E-023). This is a
mechanism study; GPU-bound defences such as A-MemGuard were out of scope (E-034).

## 6. Negative Results, Corrections, and Limitations

We preserve results that did not go our way: state-level decay did not beat
rank-level decay (E-014), fusion calibration gave no held-out gain (E-022),
signed provenance failed under signer compromise (E-023), and an early channel
ablation could not separate four of its five channels (recall stayed 1.0;
removing the temporal channel gave 0.79) and had to be redesigned (E-015).

Two measurements were **retracted rather than quietly fixed**. Graphiti cell
group ids repeated across runs while the Neo4j reset did not wipe the group, so
later runs queried graphs still holding earlier episodes (36 per cell where one
run produces 12); the affected filtered and extractor runs are marked invalid
and re-run under verified isolation (E-055). A first purge scan reported Mem0 at
zero residual because it read Graphiti's raw database but only Mem0's
API-exposed memories; the corrected scan adds Mem0's vector store and history
database with a per-run database path (E-056).

**Limitations.** Histories are synthetic with hand-specified operation profiles;
"contradiction density" is approximated by operation mix and revision count.
Two external systems, one backbone, and LLM extraction that is not
bit-reproducible. The literature review is single-reviewer. Purge claims cover
declared stores and tested failure points, not backups, OS caches or
provider-side copies.

**Future work.** Whether provenance-linked diffs actually help human auditors
(RQ4) is the largest untested claim. A preregisterable protocol, a seeded
planted-fault generator, a crossover assignment, and a deterministic scorer are
included in the artifact, but no participants were recruited for this work, so
we make no human-effectiveness claim. Running it requires ethics review or a
documented exemption, a pilot for variance, and an a priori power analysis
(D-009, D-012). Also open: distractor-laden LongMemEval splits, more external
systems, and non-synthetic operation profiles.

## 7. Artifact and Reproducibility

Runs are sealed with canonical config, environment, source-tree hash and
per-file checksums, and verified by an aggregate checker (E-045, E-047). The
frozen synthetic fixture is byte-reproducible and split-disjoint (E-037). Tests
and lint pass on CPython 3.11. Third-party datasets are used locally and never
redistributed. A dropped-`UPDATE` defect found in Mem0 during evaluation is
documented with root-cause analysis and a reproduction script, since it biases
results against that system. Public archive/DOI is deferred (D-009); a flaky
artifact tamper check is logged for release hardening (E-051).
