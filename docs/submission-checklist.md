# PVLDB Volume 20 — October 2026 cycle

| | |
|---|---|
| **Abstract due** | **2026-09-25, 17:00 Pacific** — mandatory, missing it is a desk rejection |
| **Paper due** | **2026-10-01, 17:00 Pacific** |
| Reviews expected | around 2026-11-15 |
| System | <https://cmt3.research.microsoft.com/PVLDBv20_2027/> (volume 20, **not** the v19 site) |
| Track | Experiment, Analysis & Benchmark |

## To paste into CMT

**Title** — the category tag is required in the CMT title as well as the PDF:

```
Temporal Fields Are Not Temporal Correctness: Measuring Bitemporal and Deletion
Semantics in Deployed Agent Memory [Experiment, Analysis & Benchmark]
```

**Abstract**: `paper/abstract.txt` — 5 paragraphs, 2,754 characters, 407 words.
Plain text; the only non-ASCII characters are five em dashes (U+2014). Generated
by `scripts/make_abstract.py` from the paper source, and `tests/test_abstract.py`
fails if the two drift apart, so it cannot go stale the way it did once already.

**Author**: Suan Lee, School of Computer Science, Semyung University, Jecheon,
South Korea. Contact: suanlee@semyung.ac.kr.

**Reproducibility package** (required *at initial submission* for volume 20, not
at camera-ready): <https://github.com/suanlab/temvera> — instructions in the
README and `REPRODUCING.md`, frozen snapshot at the `pvldb-eab-v1` release.

## Only the author can do these

- [ ] Register in CMT and **declare domain and PC conflicts**. The CFP
      desk-rejects for undeclared conflicts *and* for spurious ones, so the list
      wants trimming rather than padding. Its four criteria: same institution
      within five years (or an accepted offer starting within six months);
      collaboration within five years via joint publication, joint project or
      co-organised event; PhD advisor in either direction, irrespective of when;
      relative or close personal friend. Handled by the author.
- [ ] Submit the abstract by 09-25, then the PDF by 10-01.
- [ ] Decide whether to use an institutional email address.
- [ ] Confirm the Jecheon campus city if it needs correcting.
## Bibliography, checked against primary sources (2026-09-06)

Every reference now carries authors. Six entries were corrected against their
primary source, and four of those had *paraphrased rather than quoted* titles —
`minja` had the arXiv v1 title where v4 now reads differently, and `springdrift`
and `memlineage` were shortened. Hindsight was cited as a GitHub repository when
it is an ACL 2026 system demonstration with seven authors.

`memincept` was **removed**. Cited from OpenReview forum `1YNrlSSRsk`, its title
matched nothing on DBLP, arXiv, or a domain-restricted search, and OpenReview
returns a 403 challenge to automated requests, so neither authors nor title could
be confirmed. It supported one clause of related work that A-MemGuard and MINJA
already cover. Restore it if you can open the forum in a browser; the record is
kept in `studies.csv` as `withdrawn_unverifiable`.

## Desk-rejection triggers, checked

The CFP names four: incomplete abstract, unattested COIs, violated formatting,
exceeded caps. The two we control are verified:

| Check | Status |
|---|---|
| Page cap, 12 excluding references | **8 pages**, references begin on page 8 |
| Official template | `acmart` v2.19 `[sigconf, nonacm]` + vendored `pvldb.sty` |
| Category tag in the PDF title | present |
| Author names on page 1 (single-blind) | present |
| PVLDB reference-format / CC / ISSN / availability blocks | all four render |
| Build | 0 errors, 0 undefined references or citations |
| Fonts | all embedded, no Type 3 |
| Figure alt text | `\Description` on all three figures |
| Bibliography | authors verified against primary sources, except the two above |

## Artifact, verified from a clean clone

Run on a fresh clone with a fresh interpreter, which is how the Reproducibility
Committee will see it — not from the development environment, where three
failures were invisible:

```
temvera verify-artifacts …      30 sealed runs valid
verify_paper_claims.py          87 printed figures match their runs
pytest                          130 passed, 5 skipped
ruff check .                    passed (on a newer ruff than we develop against)
```

The five skips are the tests that check documentation quotes against mem0 and
graphiti-core, which are not dependencies; they run only where those packages
are installed.

**Requires CPython 3.11+.** On 3.10 pip backtracks for fifteen minutes before
reporting it, so both README and REPRODUCING put that check first.

## What regenerating the runs needs

An OpenAI key, a Neo4j 5.26 server, and a second interpreter for LangMem, whose
`openai` requirement conflicts with the pinned Mem0 and Graphiti. Scoring and
aggregation need none of these — that separation is deliberate and is the claim
the committee can check cheaply.
