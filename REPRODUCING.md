# Reproducing the Local Artifact

Everything below runs from the public artifact at
<https://github.com/suanlab/temvera>.

The accepted artifact is dependency-free except for development checks and the
optional cryptographic tests. **It requires CPython 3.11 or newer, and this is
worth checking first**: on an older interpreter pip backtracks through hundreds
of dependency versions for many minutes before finally reporting `requires a
different Python`. Many systems still ship 3.10 as `python3`.

```bash
python3 -V                    # must be >= 3.11
python3.11 -m venv .venv      # name the interpreter explicitly if it is not
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
temvera verify-dataset data/fixtures/lifecycle-v0
temvera verify-artifacts experiments/accepted-runs.json experiments/runs
```

Regenerate the primary local lifecycle studies into new immutable directories:

```bash
temvera run-experiment experiments/configs/lifecycle-smoke.json /tmp/runs
temvera lifecycle-grid experiments/configs/lifecycle-grid.json /tmp/runs/grid
temvera lifecycle-operation-suite \
  experiments/configs/lifecycle-operation-suite.json /tmp/runs/operations
temvera security-experiment \
  experiments/configs/security-evaluation.json /tmp/runs/security
```

Outputs refuse overwrite and contain canonical configuration, environment,
source-tree hash, and per-file checksums. Compare regenerated metrics rather
than expecting byte-identical `environment.json`, which records creation time
and platform.

## Verifying the paper's numbers without credentials

The main-grid table and retrieval-budget sweep can be reaggregated from sealed
per-case transcripts with no API key, Neo4j server or dataset download:

```bash
python scripts/recompute_paper_numbers.py --check
```

This verifies the nine runs used by this command, then prints the request-scope
per-category table with denominators, the list-retrieval budget sweep, and the
explicitly historical single-history deletion inventory. Wilson intervals are
computed by the paper's claim checker and figure script, and
`scripts/verify_paper_claims.py` checks every number the paper prints. Regenerating the runs is a separate, credentialed
step described below; the two are deliberately decoupled so a reviewer can
confirm what we computed before deciding whether to re-run generation.

To check the *paper* rather than the tables, run:

```bash
python scripts/verify_paper_claims.py     # --list to see every claim
```

This holds 594 claims, each pairing the value as printed in `paper/main.tex` with
a function that recomputes it from a sealed run, and fails if either half moves
--- if the computation stops matching, or if the number stops appearing where
the paper prints it. Prose claims are anchored to their own sentence, because
document-wide presence is not enough: the drift this guard exists to catch left
every number still present somewhere, with correct tables and wrong prose beside
them. Each claim also declares whether it is case-weighted or cell-averaged,
since the paper uses both and confusing them makes correct numbers look wrong.
`tests/test_paper_claims.py` runs it, so `pytest` fails on drift.
Claims that print one quantity under one scoring contract share a `metric`
id, and the verifier fails if such a metric is printed as two different values
anywhere in the paper. `python scripts/verify_paper_claims.py --manifest
<file>` writes every claim -- where it is printed, its printed and recomputed
value, its metric id, anchor and aggregation -- as JSON.

`python scripts/extract_review_tables.py <dir>` writes, with no model call,
review tables of the 90 reader answers about what was known before a correction
and of the 60 LongMemEval valid-time questions (the latter carries benchmark
text, so it is written outside the repository).

`python scripts/make_annotation_kit.py <dir>` writes a blinded kit for
independent human labels -- the 90 reader answers mixed with 20 constructed
controls, and the 60 timing pairs, under opaque ids, with instructions and a
separate key -- and `python scripts/score_annotation_kit.py <dir> [<dir2>]`
scores the filled sheets against the controls, the strict count and the H15
model consensus.

Figures are regenerated from the same sealed runs with
`python scripts/make_figures.py`, and are byte-reproducible: a regenerated
figure should be identical to the shipped one.

The two bounds of §VI-H are recomputed by
`python scripts/analyze_filtering_laws.py`, which rebuilds each history from
its run's seeds and exits non-zero if a rebuilt question disagrees with the
sealed one; the claim checker calls the same functions.

The retroactive-correction result of §VI-I is recomputed by
`python scripts/analyze_corrections.py`. Its predictions and analysis were
committed before the runs existed (`docs/preregistration-h6.md`, commit
`5272ced`); the one check added afterwards is labelled post hoc in the script,
the paper and the evidence ledger (E-090).

The read-path rule of §VI-D is recomputed by
`python scripts/analyze_read_path_filter.py`. The rule and the script were
committed (`3b594bc`) before they were applied to the current releases of
§VI-J, which are therefore out of sample for it (E-092).

The October 2026 revision added five preregistered studies (H8-H12), each with
its predictions committed and pushed before its runs (`docs/preregistration-h*.md`,
outcome tables at the end of each). Offline, from sealed runs:

| What | Script |
|---|---|
| Cluster bootstrap, paired McNemar with Holm, TOST equivalence | `python scripts/analyze_statistics.py` |
| Replicates and the `gpt-4o` backbone for LangMem, Cognee, Hindsight (H8) | `python scripts/analyze_h8.py` |
| Purge category under the request's own scope (E-096) | `python scripts/analyze_purge_scope.py` |
| What the final store knew before a correction (H11a) | `analyze_corrections.pre_correction` |

These need an API key and are sealed into new runs:

| What | Command |
|---|---|
| Common reader and asserted-value judge (H9) | `python scripts/llm_rescore.py {reader,judge} openai:<model> <source-run> <new-run>` |
| Whole-store census (H11b) | `python scripts/store_census.py <new-run>` |
| Retention policy swap, fixed retriever and reader (H12) | `python scripts/controlled_policy.py <new-run>` |
| Deletion across five systems (H10) | `temvera deletion-study experiments/configs/deletion-study-<system>.json <new-run>`; Hindsight needs its own daemon and `HINDSIGHT_PSQL`, `HINDSIGHT_PG_INSTANCE` naming its psql and pg0 instance file |
| Judge on answers of known verdict (H13-E3) | `python scripts/judge_minimal_pairs.py openai:gpt-4o <new-run>` |
| Is the real-data valid-time gold identifiable? (H13-E2) | `python scripts/classify_lme_timing.py <new-run>` |
| Reader told the persistence contract (H13-E2) | `python scripts/llm_rescore.py reader_persist openai:gpt-4o-mini <source-run> <new-run>` |
| Verified deletion caller; LangMem with deletes enabled (H13-E4) | `temvera deletion-study experiments/configs/deletion-verified-<system>.json <new-run>`, `.../deletion-langmem-deletes.json` |
| One store growing to 3,000 turns: cost, latency, size, memory, load (H14) | `python scripts/scale_cost.py {mem0,graphiti,hindsight} <new-run>`; offline analysis `python scripts/analyze_scale_cost.py` |
| Final-store correction runs (H11a) | `temvera external-<system> experiments/configs/final-store-corrections-<config>.json <new-run>` |

## External-system experiments (require credentials)

Sections of the paper that compare deployed systems need resources the local
artifact deliberately does not bundle. Everything else above runs offline.

| Experiment | Command | Requires |
|---|---|---|
| Mem0 comparison | `temvera external-mem0 <config> <out>` | `OPENAI_API_KEY` |
| Graphiti comparison | `temvera external-graphiti <config> <out>` | `OPENAI_API_KEY`, Neo4j 5.26 at `NEO4J_URI` |
| Purge residual | `temvera purge-residual <config> <out>` | both of the above |
| LangMem comparison | `temvera external-langmem <config> <out>` | `OPENAI_API_KEY`, `LANGMEM_PYTHON` |
| Cognee comparison | `temvera external-cognee <config> <out>` | `OPENAI_API_KEY`, `COGNEE_PYTHON` |
| Hindsight comparison | `temvera external-hindsight <config> <out>` | `OPENAI_API_KEY`, a local Hindsight daemon |
| Scale sweep and cost | `temvera external-mem0` / `external-graphiti` with `experiments/configs/scale-*.json` | as for Mem0 / Graphiti |
| Real conversations | the command for each system with `experiments/configs/lme-bitemporal-*.json` | as for that system, plus the dataset in `data/raw/` |
| LongMemEval validity | `temvera longmemeval-eval <config> <out>` | `OPENAI_API_KEY`, dataset downloaded to `data/raw/` |
| Learned dense channel | `temvera vector-synonym-compare <out>` | model download (CPU only) |

Set `OPENAI_API_KEY`, and for Graphiti `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_PASSWORD`. LangMem and Cognee need `openai` versions that conflict with
the pinned Mem0 and Graphiti, so each runs in its own virtualenv named by
`LANGMEM_PYTHON` / `COGNEE_PYTHON`. Hindsight runs as a local daemon
(`hindsight-embed daemon start`, port 8888) whose profile must hold a valid key:
the harness stops a run on an authentication or exhausted-quota error rather
than scoring the empty answers it would otherwise produce. Each Cognee cell gets
its own store root, which the worker confirms at start-up, so Cognee runs may
run concurrently; before that fix they shared one database (E-081). A rootless Neo4j (JDK 21 + the community tarball) is
sufficient; Docker is not required. Wall-clock is dominated by per-turn LLM
extraction: roughly 1-2 h for a 20-cell grid and 35-40 min per instance on the
distractor-laden LongMemEval split.

**Current releases (§VI-J).** The `*-latest.json` configs re-run the grid on
Mem0 2.2.1, Graphiti 0.31.2, Cognee 1.6.5 and Hindsight 1.1.0. These need their
own interpreters, separate from the pinned versions above: one virtualenv with
`mem0ai==2.2.1 graphiti-core==0.31.2`, one with `cognee==1.6.5` (named by
`COGNEE_PYTHON`), and a second Hindsight daemon from `hindsight-api==1.1.0`
under its own `HOME` and profile, on port 8890 so it does not collide with the
pinned daemon on 8888; the configs name that URL and record the server version
the daemon reports. Mem0 2.x rejects the `timestamp` and `reference_date`
arguments in its open-source build, so the adapter ingests without them; the
predictions for these runs were committed beforehand
(`docs/preregistration-h7.md`).

The LongMemEval corpus is **not redistributed here**; download it from the
official release. Its code and data are MIT-licensed (verified against the
dataset metadata; evidence ledger E-001). Some sealed runs do carry its text,
which that licence permits: `longmemeval-e7-v2` ships a history database of
memories extracted from it, and the `lme-bitemporal-*` transcripts record
retrieved passages verbatim. The real-data labels are in
`data/lme-bitemporal-labels.json`: 43 pairs on which both extractors agreed and
19 the author adjudicated from AI-proposed labels with quoted evidence
(D-016, D-017); the 7 excluded pairs are listed by question ID, with reasons, in
`data/lme-bitemporal-exclusions.json`. Our scorer is
deterministic substring/token presence over retrieved memories and is **not**
the benchmark's LLM-judged QA metric; the two must not be compared.

The ForgetEval compatibility run additionally requires a clone of
`deeplethe/lethe` at commit
`b6053b7bdacc78a91b9ea4bb25f32edad278c495`. No API keys or private data are
included in this repository, and no third-party dataset as such; the derived
LongMemEval content above is the one exception.

Repository-authored material and the fully synthetic fixture are distributable
under Apache-2.0. Frozen, byte-reproducible snapshots are attached to the
GitHub releases; the ICDE submission's is the latest `icde-eab-v*` tag, and an
earlier tag verifies only the runs it contains (`icde-eab-v8` predates the H15
and dropped-action-log runs). No DOI archive has been made (D-009).
