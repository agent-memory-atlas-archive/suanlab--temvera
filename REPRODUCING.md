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

Every figure the paper reports is an aggregation over sealed per-case
transcripts, so the arithmetic can be checked with no API key, no Neo4j, and no
dataset download:

```bash
python scripts/recompute_paper_numbers.py --check
```

This verifies each cited run's seal, then recomputes the per-category table with
denominators and Wilson intervals, the retrieval-budget sweep, and the deletion
residual for both conditions. Regenerating the runs is a separate, credentialed
step described below; the two are deliberately decoupled so a reviewer can
confirm what we computed before deciding whether to re-run generation.

To check the *paper* rather than the tables, run:

```bash
python scripts/verify_paper_claims.py     # --list to see every claim
```

This holds 218 claims, each pairing the value as printed in `paper/main.tex` with
a function that recomputes it from a sealed run, and fails if either half moves
--- if the computation stops matching, or if the number stops appearing where
the paper prints it. Prose claims are anchored to their own sentence, because
document-wide presence is not enough: the drift this guard exists to catch left
every number still present somewhere, with correct tables and wrong prose beside
them. Each claim also declares whether it is case-weighted or cell-averaged,
since the paper uses both and confusing them makes correct numbers look wrong.
`tests/test_paper_claims.py` runs it, so `pytest` fails on drift.

Figures are regenerated from the same sealed runs with
`python scripts/make_figures.py`, and are byte-reproducible: a regenerated
figure should be identical to the shipped one.

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

The LongMemEval corpus is **not redistributed here**; download it from the
official release. Its code and data are MIT-licensed (verified against the
dataset metadata; evidence ledger E-001). Some sealed runs do carry its text,
which that licence permits: `longmemeval-e7-v2` ships a history database of
memories extracted from it, and the `lme-bitemporal-*` transcripts record
retrieved passages verbatim. The real-data labels are in
`data/lme-bitemporal-labels.json`; the excluded pairs are listed by question ID
only in `data/lme-bitemporal-exclusions.json` (decision D-016). Our scorer is
deterministic substring/token presence over retrieved memories and is **not**
the benchmark's LLM-judged QA metric; the two must not be compared.

The ForgetEval compatibility run additionally requires a clone of
`deeplethe/lethe` at commit
`b6053b7bdacc78a91b9ea4bb25f32edad278c495`. No API keys or private data are
included in this repository, and no third-party dataset as such; the derived
LongMemEval content above is the one exception.

Repository-authored material and the fully synthetic fixture are distributable
under Apache-2.0. Frozen, byte-reproducible snapshots are attached to the
GitHub releases (`icde-eab-v1` for the ICDE submission); no DOI archive has
been made (D-009).
