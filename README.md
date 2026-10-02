# Temvera

> Temporal, provenance-aware memory infrastructure for AI agents.

Temvera is a research project investigating how long-running AI agents should
store, revise, retrieve, forget, and audit memory. The project treats memory as
an evolving data-management problem rather than a flat vector store.

## Paper artifact (ICDE 2027, Experimental, Analysis, and Benchmark)

*Temporal Fields Are Not Temporal Correctness: Measuring Bitemporal and Deletion
Semantics in Deployed Agent Memory.*

Every number the paper reports is an aggregation over sealed per-case
transcripts, so **the whole paper can be checked without an API key, a database
server, or a dataset download**:

**Requires CPython 3.11 or newer.** Check before anything else — on an older
interpreter `pip` spends fifteen minutes backtracking through dependency
versions before it reports the real problem:

```bash
python3 -V          # must be >= 3.11; if not, use python3.11 below
```

```bash
git clone https://github.com/suanlab/temvera && cd temvera
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

temvera verify-artifacts experiments/accepted-runs.json experiments/runs  # 30 sealed runs
python scripts/recompute_paper_numbers.py --check    # rebuild every table
python scripts/verify_paper_claims.py                # 87 printed figures vs. their runs
pytest && ruff check .
```

`verify_paper_claims.py` is the one to run if you only run one: it pairs each
figure as printed in the paper with a recomputation from a sealed run, and fails
if either half moves.

Regenerating the runs is a separate, credentialed step — it needs an OpenAI key,
a Neo4j server, and a second interpreter for LangMem, whose `openai` requirement
conflicts with the pinned Mem0 and Graphiti. The two paths are deliberately
decoupled: you can confirm what we computed before deciding whether to re-run
generation. [REPRODUCING.md](REPRODUCING.md) has the full protocol, and a frozen
snapshot with checksums is attached to the
[`pvldb-eab-v1` release](https://github.com/suanlab/temvera/releases/tag/pvldb-eab-v1).

## Research thesis

Git-native, bitemporal memory can make agent beliefs inspectable, reversible,
and governable while retaining competitive retrieval quality. Temvera studies
this thesis through three connected tracks:

1. **Memory substrate** — append-only events, bitemporal facts, provenance,
   belief revision, consolidation, and human-reviewable history.
2. **Retrieval and indexing** — exact, lexical, vector, temporal, and graph
   retrieval with calibrated fusion and reranking.
3. **Evaluation and security** — judge-free lifecycle benchmarks, stale-fact
   resistance, abstention, provenance integrity, and memory-poisoning defenses.

## Repository map

```text
Temvera/
├── docs/                 Research program, architecture, and proposals
├── data/                 Dataset manifests and generated benchmark data
├── experiments/          Reproducible experiment configurations and outputs
├── src/temvera/          Typed research reference implementation
├── tests/                Deterministic tests and benchmark verifiers
├── CITATION.cff          Citation metadata
└── pyproject.toml        Minimal Python research package configuration
```

Start with [docs/index.md](docs/index.md), then read the
[research program](docs/research-program.md) and
[roadmap](docs/roadmap.md).

## Current status

Local WP1–WP4 mechanism studies are implemented. Prior-art breadth,
identical-budget external-system reproduction, human evaluation, licensing,
and public archival remain incomplete. Claims outside the frozen synthetic
fixtures remain hypotheses.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

No production readiness is claimed. The package implements the deterministic
research substrate and experiment harness behind a provisional API.

## Deterministic lifecycle smoke test

The local baseline requires no model or external service:

```bash
temvera generate /tmp/temvera-demo --seed 17 --entities 4 --revisions 3
temvera benchmark /tmp/temvera-demo
```

The report compares the bitemporal oracle with append-only, full/recent
context, BM25@1, and last-write-wins baselines under identical histories. It is
a harness identifiability check, not a performance or novelty result.

Verify the accepted sealed experiment package with:

```bash
temvera verify-artifacts experiments/accepted-runs.json experiments/runs
```

See [REPRODUCING.md](REPRODUCING.md) for the complete local protocol.

## Name

**Temvera** combines *temporal* and *veritas*: memory whose truth is interpreted
with respect to time and supporting evidence. The name has been selected for
this project after a preliminary collision screen; that screen is not legal
trademark clearance or reservation.

## License

Repository-authored code, documentation, fully synthetic fixtures, and accepted
local experiment outputs are licensed under [Apache-2.0](LICENSE). Third-party
artifacts are governed by their own licenses and are not redistributed here.
