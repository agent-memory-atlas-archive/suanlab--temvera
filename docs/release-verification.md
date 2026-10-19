# Release Verification Record

## 2026-10-20 icde-eab-v3, checked from the archive alone

The v3 candidate was extracted into an empty directory outside any git
repository and every check the release notes name was run there, with the
package imported from the extracted `src/`:

- `verify-artifacts` over the 56 accepted runs and `verify-artifact-package`.
- `scripts/recompute_paper_numbers.py --check`.
- `scripts/verify_paper_claims.py`: 257 claims.
- `scripts/analyze_filtering_laws.py`: both bounds, no rebuilt-case mismatch.
- `scripts/make_figures.py`: all three figures byte-identical to the shipped ones.
- The full pytest suite, and the paper builds (11 pages).

Doing this exposed that earlier archives omitted `scripts/` and `paper/` and two
cited runs (evidence ledger E-088). Those archives are left as published.

## 2026-07-16 current local candidate

The repository was copied to `/tmp` without `.git` or caches and tested with
CPython 3.11.15, pytest 9.1.1, Ruff 0.15.21, and build 1.5.0.

- 89 tests passed.
- `ruff check .` passed.
- Wheel and sdist builds succeeded in isolated PEP 517 environments.
- The wheel installed without the source tree and successfully ran
  `temvera generate`, `temvera benchmark`, `temvera verify-dataset`, and
  aggregate `temvera verify-artifacts` against the accepted local runs.
- Wheel SHA-256:
  `6fd242e6b9966c9e86a88169be281de1d4a2bb6e45547702d879ac4e536dba54`
- Sdist SHA-256:
  `6461d678676cc4d862d9fa4e657eba4c984f3f495360e0c23ebe4a46cd605c1f`

The wheel contains `LICENSE`, declares Apache-2.0 in package metadata, and was
installed into a clean environment before the CLI smoke tests. The dataset and
artifact manifests also identify Apache-2.0 redistribution status.

The deterministic local research archive was also generated and passed its
internal verifier: 305 files and ten accepted runs, SHA-256
`f8fd2e150fd8a300a8bf4eef93c6997e41850530248bd874b34ed620f624c5d3`.
It is stored under ignored `dist/`, includes `LICENSE`, and records
`permitted_under_apache_2_0`. Public archive/DOI publication is deferred by
decision D-009.
The hashes describe candidates built immediately before this record was
updated; a public release must rebuild after final metadata and licensing.
