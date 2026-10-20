# Reference verification: paper/refs.bib (19 keys)

Audit date: 2026-10-21. Inputs: `paper/refs.bib`, `execution/citation_contexts.json`, `paper/main.tex` (lines 134-180, 205-212, 856-864, 996-1000), and `paper/main.bbl` to see how entries render.

How I checked:
- **arXiv metadata.** One batch query to the arXiv export API (`https://export.arxiv.org/api/query?id_list=...`). It returns the official title, the full author list, the v1 date, the latest-version date, the comment field, journal_ref and the abstract. Each section gives the canonical abs URL `https://arxiv.org/abs/<id>`. Unless a section says otherwise, I read the metadata and abstract through the API and did not open the abs HTML page.
- **GitHub.** I used the GitHub REST API to check that each repo exists, to resolve the cited commits and tag, and to read README files at the pinned revision.
- **Venues.** I checked these on ACL Anthology `.bib` exports, Crossref, PMLR, and the neurips.cc, icml.cc and iclr.cc virtual poster pages. OpenReview served a browser-check wall, so I could not read it.
- **Full text.** I read the full text of only two cited sources: LongMemEval (arXiv PDF v2) and Snodgrass and Ahn 1985 (author-hosted PDF). For the rest, my claim judgments rest on the abstract or README.
- **Casing.** I ignored casing differences that come only from IEEEtranN lowercasing titles.

---

## mem0
- key: mem0
- source_url: https://arxiv.org/abs/2504.19413 (API metadata); https://api.crossref.org/works/10.3233/FAIA251160
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 5 authors in order, arXiv id and year 2025 match arXiv v1 (2025-04-28). Only one arXiv version exists.
  - The bib leaves out the peer-reviewed venue. Crossref DOI 10.3233/FAIA251160 is an IOS Press book chapter: container "Frontiers in Artificial Intelligence and Applications" / "ECAI 2025", issued 2025-10-21, with the same title and the same 5 authors. Crossref gives no volume or page numbers, so I did not confirm them.
- claim_support: SUPPORTED. The paper cites Mem0 only as part of "the baseline landscape" (line 172). Abstract: "We introduce Mem0, a scalable memory-centric architecture that addresses this issue by dynamically extracting, consolidating, and retrieving salient information from ongoing conversations."
- proposed_bib_fix: Optional upgrade to the published version. The arXiv-only entry is not wrong.
  ```
  @inproceedings{mem0,
    title     = {Mem0: Building Production-Ready {AI} Agents with Scalable Long-Term Memory},
    author    = {Chhikara, Prateek and Khant, Dev and Aryan, Saket and Singh, Taranjeet and Yadav, Deshraj},
    booktitle = {ECAI 2025},
    series    = {Frontiers in Artificial Intelligence and Applications},
    publisher = {IOS Press},
    year      = {2025},
    doi       = {10.3233/FAIA251160},
    note      = {arXiv:2504.19413}
  }
  ```

## zep
- key: zep
- source_url: https://arxiv.org/abs/2501.13956 (API metadata)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies: None. Title, all 5 authors (Rasmussen, Paliychuk, Beauvais, Ryan, Chalef), id and year 2025 match v1 (2025-01-20), the only version. I found no journal_ref.
- claim_support: SUPPORTED, as a baseline-landscape mention. Abstract: "We introduce Zep, a novel memory layer service for AI agents ... through its core component Graphiti -- a temporally-aware knowledge graph engine". This also supports the "Zep/Graphiti" pairing.
- proposed_bib_fix: none

## memgpt
- key: memgpt
- source_url: https://arxiv.org/abs/2310.08560 (API metadata)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 7 authors and year match v1 (2023-10-12). The latest version is v2 (2024-02-12).
  - **The entry type is wrong.** It is `@inproceedings` with `booktitle = {arXiv preprint arXiv:2310.08560}`. In main.bbl this renders as "in *arXiv preprint arXiv:2310.08560*, 2023", which wrongly presents an arXiv preprint as a proceedings volume. arXiv has no journal_ref, and I found no published venue.
- claim_support: SUPPORTED, as a baseline-landscape mention. Abstract: "we introduce MemGPT (Memory-GPT), a system that intelligently manages different memory tiers". The paper's "MemGPT/Letta" pairing (Letta is the later name of the project) is not checked against this source.
- proposed_bib_fix:
  ```
  @article{memgpt,
    title   = {{MemGPT}: Towards {LLMs} as Operating Systems},
    author  = {Packer, Charles and Wooders, Sarah and Lin, Kevin and Fang, Vivian and Patil, Shishir G. and Stoica, Ion and Gonzalez, Joseph E.},
    journal = {arXiv preprint arXiv:2310.08560},
    year    = {2023}
  }
  ```

## hipporag2
- key: hipporag2
- source_url: https://arxiv.org/abs/2502.14802 (API metadata); https://proceedings.mlr.press/v267/gutierrez25a.html
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 5 authors and year match.
  - The bib cites the arXiv preprint, but the paper was published at ICML 2025. The arXiv v2 comment says "ICML 2025". PMLR lists it in volume 267, pages 21497-21515.
- claim_support: SUPPORTED, as a baseline-landscape mention. Abstract: "we ... propose HippoRAG 2, a framework that outperforms standard RAG comprehensively on factual, sense-making, and associative memory tasks."
- proposed_bib_fix:
  ```
  @inproceedings{hipporag2,
    title     = {From {RAG} to Memory: Non-Parametric Continual Learning for Large Language Models},
    author    = {Guti{\'e}rrez, Bernal Jim{\'e}nez and Shu, Yiheng and Qi, Weijian and Zhou, Sizhe and Su, Yu},
    booktitle = {Proceedings of the 42nd International Conference on Machine Learning (ICML)},
    series    = {Proceedings of Machine Learning Research},
    volume    = {267},
    pages     = {21497--21515},
    year      = {2025}
  }
  ```

## longmemeval
- key: longmemeval
- source_url: https://arxiv.org/abs/2410.10813 (API metadata); full text read at https://arxiv.org/pdf/2410.10813v2; repo https://github.com/xiaowu0162/LongMemEval
- access_level: full_text
- existence: CONFIRMED
- metadata_discrepancies: None. Title, all 6 authors, ICLR 2025 and year match. The arXiv comment says "ICLR 2025", and the repo description says "(ICLR 2025)". I did not open the ICLR or OpenReview record because OpenReview served a browser-check wall.
- claim_support, line 860: PARTIAL.
  - Supported:
    - Knowledge-update questions: "knowledge-update (KU) focuses on the ability to recognize changes in the user's life states and update the memory accordingly".
    - Timestamped sessions: "S ≡ [(t1, S1), ..., (tN, SN)] ... ti is the session's timestamp", and "assign a plausible timestamp to all sessions".
    - Gold holds only the updated value. This agrees with the KU grading prompt: "If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer." The source does not state outright that the superseded value is never shipped; that part is the paper's own observation.
  - Not supported: the surrounding framing that LongMemEval is **human-written text** (line 856: "cannot show that the failure modes survive human-written text. LongMemEval's knowledge-update questions ... supply that case"). The source says the conversations are LLM-generated and then human-edited:
    - "the evidence sessions are LLM-simulated and human-edited" (Fig. 2).
    - "Each evidence statement is then separately embedded into a task-oriented evidence session created by self-chatting".
    - Filler sessions come from "(1) self-chat sessions simulated ... and (2) publicly released user-AI style chat data including ShareGPT ... and UltraChat".
- claim_support, line 998 ("On human-written LongMemEval conversations"): NOT_SUPPORTED as worded, for the same reason. "Human-edited, LLM-simulated" or "naturalistic, non-synthetic-template" would be accurate.
- proposed_bib_fix: None needed. Optionally add `url = {https://openreview.net/forum?id=...}` once confirmed. The **paper text** needs correcting: "human-written" should become, for example, "LLM-simulated, human-edited".

## minja
- key: minja
- source_url: https://arxiv.org/abs/2503.03704 (API metadata); https://neurips.cc/virtual/2025/poster/118152
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 8 authors and year match arXiv. The latest version is v5 (2026-02-12).
  - The bib cites the arXiv preprint, but the paper was published at NeurIPS 2025 as a poster. The neurips.cc page lists the same title and the same 8 authors. I did not confirm proceedings volume or pages.
- claim_support: SUPPORTED ("shows query-only poisoning"). Abstract: "The attacker injects malicious records into the memory bank by only interacting with the agent via queries and output observations."
- proposed_bib_fix:
  ```
  @inproceedings{minja,
    title     = {Memory Injection Attacks on {LLM} Agents via Query-Only Interaction},
    author    = {Dong, Shen and Xu, Shaochen and He, Pengfei and Li, Yige and Tang, Jiliang and Liu, Tianming and Liu, Hui and Xiang, Zhen},
    booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
    year      = {2025},
    note      = {arXiv:2503.03704}
  }
  ```

## memoryagentbench
- key: memoryagentbench
- source_url: https://arxiv.org/abs/2507.05257 (API metadata); https://iclr.cc/virtual/2026/poster/10010781
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 3 authors and year 2025 (v1, 2025-07-07) match. The latest version is v4 (2026-06-28).
  - The bib cites the arXiv preprint, but the paper was accepted at ICLR 2026. The iclr.cc poster page lists the same title and authors.
- claim_support: SUPPORTED ("evaluates selective forgetting among four competencies"). Abstract: "we identify four core competencies essential for memory agents: accurate retrieval, test-time learning, long-range understanding, and selective forgetting."
- proposed_bib_fix: Change to `@inproceedings` with `booktitle = {International Conference on Learning Representations (ICLR)}`, `year = {2026}` and `note = {arXiv:2507.05257}`. Keep the other fields.

## toki
- key: toki
- source_url: https://arxiv.org/abs/2606.06240 (API metadata); https://github.com/ZenAlexa/toki-bitemporal-memory (HTTP 404)
- access_level: abstract_or_landing
- existence: CONFIRMED (paper)
- metadata_discrepancies: None. Title, the single author (Ziming Wang), id and year 2026 match v1 (2026-06-04), the only version.
- claim_support: PARTIAL.
  - Supported: "defines bitemporal operators over a dual-row schema". Abstract: "TOKI types the four heuristics as one family of bitemporal operators over a dual-row schema".
  - Not supported: "with released code". The arXiv comment says "Code, data, and reproducibility artifact: https://github.com/ZenAlexa/toki-bitemporal-memory". However, that URL returns HTTP 404 on 2026-10-21, both through the GitHub API and as the web page. The repo is not among the user's public repos, and a GitHub search for "toki bitemporal" returns nothing. The code may be private, renamed or deleted.
- proposed_bib_fix: None to the bib. Suggest rewording "with released code" to "with code announced at <URL> (unavailable as of Oct 2026)", or dropping the phrase.

## memstrata
- key: memstrata
- source_url: https://arxiv.org/abs/2606.26511 (API metadata)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies: None. Title, the single author (Neeraj Yadav), id and year 2026 match v1 (2026-06-25). The title has no "MemStrata", but the abstract names the system MemStrata.
- claim_support: SUPPORTED. Abstract: "a deterministic (subject, relation, object) supersession rule retires the stale value in a bi-temporal ledger" and "The central result is the stale-fact-error rate".
- proposed_bib_fix: none

## graphnativebitemporal
- key: graphnativebitemporal
- source_url: https://arxiv.org/abs/2607.26520 (API metadata)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies: None. Title, both authors (Alp Niksarli, Gopesh Baheti), id and year 2026 match v1 (2026-07-29).
- claim_support: SUPPORTED. Abstract: "versioned content nodes carrying two closed-open time intervals: valid time ... and transaction time ... This design supports point-in-time semantic retrieval".
- proposed_bib_fix: None. Style note: the sentence "A \citep{graphnativebitemporal} graph-native bitemporal memory store" reads oddly, because the numeric citation sits between "A" and the noun phrase.

## springdrift
- key: springdrift
- source_url: https://arxiv.org/abs/2604.04660 (API metadata); https://github.com/seamus-brady/springdrift (README)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies: None. Title, the single author (Seamus Brady), id and year 2026 match v1 (2026-04-06).
- claim_support: SUPPORTED ("combines append-only memory, auditability and git-backed recovery"). Abstract: "an auditable execution substrate (append-only memory, supervised processes, git-backed recovery)". The README adds: "Git (required -- all agent memory is git-backed for versioning". The abstract said code "will be available ... upon publication", and the repo is now public.
- proposed_bib_fix: none

## memlineage
- key: memlineage
- source_url: https://arxiv.org/abs/2605.14421 (API metadata)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies: None. Title, both authors (Ciyan Ouyang, Rui Hou), id and year 2026 match v1 (2026-05-14).
- claim_support: SUPPORTED ("proposes lineage-based action gating"). Abstract: "attaches ... LLM-mediated derivation lineage to every entry ... The sensitive-action gate then refuses dispatches whose active justification descends from an external ancestor".
- proposed_bib_fix: none

## forgeteval
- key: forgeteval
- source_url: https://github.com/deeplethe/lethe; README and docs/forgeteval.md read at commit b6053b7bdacc78a91b9ea4bb25f32edad278c495
- access_level: full_text (README and benchmark docs)
- existence: CONFIRMED. The repo exists. Commit b6053b7 exists: it is the merge of PR #4, dated 2026-06-16, with the message "docs: sync README benchmark table to published paper (385-case)".
- metadata_discrepancies:
  - **Title not found in the source.** The bib title "ForgetEval: A Benchmark for Forgetting in Agent Memory" does not appear in the repo. The README's own citation block gives "ForgetEval: Benchmarking the Forgetting Axis of Agent Memory Systems". The repo itself is "lethe", described as "The best-benchmarked open-source AI memory system and the first AI memory built to forget."
  - **Author.** The bib author is the org "{DeepLethe}". The README credits "Dongxu Yang, *DeepLethe*, 2026" and its BibTeX uses `author = {Yang, Dongxu}`.
  - Year 2026 is consistent with the commit date.
- claim_support: SUPPORTED ("generates seeded lifecycle cases with deterministic substring scoring across supersession, decay, amnesia, purge and drift"). README: "1000 generated cases across five families — supersession, decay, amnesia, purge, drift ... Pass / fail is exact substring matching on top-k recall, no LLM judge, deterministic." docs/forgeteval.md: "Deterministic. `generate(n_per_family, seed=42, distractors=4)`". The co-cited arXiv 2606.15903 abstract also says "scored by deterministic substring match".
- proposed_bib_fix:
  ```
  @misc{forgeteval,
    title        = {{ForgetEval}: Benchmarking the Forgetting Axis of Agent Memory Systems},
    author       = {Yang, Dongxu},
    howpublished = {\url{https://github.com/deeplethe/lethe}, commit b6053b7},
    year         = {2026},
    note         = {Benchmark code in the Lethe repository (DeepLethe)}
  }
  ```

## graphiti
- key: graphiti
- source_url: https://github.com/getzep/graphiti; tag v0.29.2 resolved through the API; README and pyproject read at v0.29.2
- access_level: full_text (README)
- existence: CONFIRMED. Tag `v0.29.2` exists: commit ff7e29c, release "v0.29.2 - FalkorDB Bug Fixes", published 2026-06-08. pyproject has `name = "graphiti-core"`, `version = "0.29.2"`.
- metadata_discrepancies:
  - **Title is a paraphrase, not the source's.** The bib title "Graphiti: Temporally-Aware Knowledge Graphs for Agent Memory" is not the repo's. The README heading at v0.29.2 is "Build Temporal Context Graphs for AI Agents", and the GitHub description is "Build Real-Time Knowledge Graphs for AI Agents". "Temporally-aware knowledge graph engine" is wording from the Zep arXiv abstract.
  - The author "{Zep}" is acceptable; the org is getzep / Zep Software.
  - Year 2026 matches the tag date.
- claim_support: SUPPORTED, as a baseline-landscape mention. README: "Graphiti is the open-source temporal context graph engine at the core of" Zep, and "Explicit bi-temporal tracking with automatic fact invalidation".
- proposed_bib_fix: `title = {Graphiti: Build Temporal Context Graphs for {AI} Agents}` (README heading at v0.29.2). Alternatively, keep a neutral `title = {Graphiti}`. Keep `howpublished` as is.

## hindsight
- key: hindsight
- source_url: https://aclanthology.org/2026.acl-demo.27/ (.bib export); https://arxiv.org/abs/2512.12818 (API metadata); https://github.com/vectorize-io/hindsight (README at commit 1549987)
- access_level: abstract_or_landing
- existence: CONFIRMED. The ACL 2026 demo paper exists. Commit 1549987 exists (full sha 15499870151b..., 2026-07-15, "docs: Add Omnigent integration page (#2710)").
- metadata_discrepancies:
  - Title, all 7 authors (including "Latimer, Christopher" and "Boschi, Nicol{\`o}"), booktitle (64th ACL, Volume 3: System Demonstrations) and year 2026 match the ACL Anthology entry exactly.
  - The bib leaves out pages 275--285, DOI 10.18653/v1/2026.acl-demo.27, and the publisher and address. These are omissions, not errors.
  - The arXiv preprint has a different title ("Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects", 2512.12818). That is not an error.
- claim_support: SUPPORTED, as a baseline-landscape mention. Abstract: "We present Hindsight, a memory architecture that treats agent memory as a structured, first-class substrate for reasoning".
- proposed_bib_fix: add `pages = {275--285}`, `doi = {10.18653/v1/2026.acl-demo.27}`, `publisher = {Association for Computational Linguistics}`

## amemguard
- key: amemguard
- source_url: https://arxiv.org/abs/2510.02373 (API metadata); https://icml.cc/virtual/2026/poster/61006
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 10 authors in order, id and year 2025 (v1, 2025-09-29) match arXiv.
  - The bib cites the arXiv preprint, but the paper was accepted at ICML 2026 as a poster. The icml.cc page lists the same title and authors. I did not confirm the PMLR volume or pages.
- claim_support: SUPPORTED ("is a current defence baseline"). Abstract: "we introduce A-MemGuard (Agent-Memory Guard), the first proactive defense framework for LLM agent memory" and "Our code is available". The repo TangciuYueng/AMemGuard exists.
- proposed_bib_fix: Change to `@inproceedings` with `booktitle = {Proceedings of the 43rd International Conference on Machine Learning (ICML)}`, `year = {2026}` and `note = {arXiv:2510.02373}`. Keep the authors. I did not verify the ordinal "43rd" against the proceedings; plain "International Conference on Machine Learning (ICML)" is the safe form. Leaving the bib at arXiv 2025 is acceptable but outdated.

## snodgrass1985
- key: snodgrass1985
- source_url: https://api.crossref.org/works/10.1145/971699.318921 (also 10.1145/318898.318921); full text at https://www2.cs.arizona.edu/~rts/pubs/SIGMOD85.pdf (author-hosted)
- access_level: full_text
- existence: CONFIRMED
- metadata_discrepancies:
  - Authors (Richard Snodgrass, Ilsoo Ahn), journal ACM SIGMOD Record, volume 14, number 4, pages 236--246 and year 1985 match Crossref DOI 10.1145/971699.318921.
  - The printed title is "A Taxonomy of Time in Databases" (PDF title page and author's publication list), which matches the bib. Crossref and ACM metadata say "A taxonomy of time databases"; that is an ACM metadata error, not a bib error.
  - The same paper appears as SIGMOD '85 Proceedings, pp. 236-246, DOI 10.1145/318898.318921, and the author's list cites the proceedings. The bib's SIGMOD Record citation is also valid.
  - DOI is missing from the bib.
- claim_support: SUPPORTED. The paper says "the query we need is standard": the value valid at event time V as recorded by transaction time T. Full text: "a temporal DBMS makes it possible to view tuples valid at some moment seen as of some other moment, completely capturing the history of retroactive/postactive changes. We use the term temporal database to emphasize the need for both valid time and transaction time".
- proposed_bib_fix: add `doi = {10.1145/971699.318921}`

## locomo (uncited; existence only)
- key: locomo
- source_url: https://arxiv.org/abs/2402.17753 (API metadata); https://aclanthology.org/2024.acl-long.747/ (.bib export)
- access_level: abstract_or_landing
- existence: CONFIRMED
- metadata_discrepancies:
  - Title, all 6 authors and year 2024 match.
  - The paper was published at ACL 2024 (Volume 1: Long Papers), pp. 13851--13870, DOI 10.18653/v1/2024.acl-long.747, but the bib cites only the arXiv preprint.
  - The entry is not cited, so it is not printed: main.bbl has no locomo item and there is no \nocite.
- claim_support: N/A (not cited)
- proposed_bib_fix: If it gets cited, change to `@inproceedings` with `booktitle = {Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)}`, `pages = {13851--13870}`, `year = {2024}` and `doi = {10.18653/v1/2024.acl-long.747}`. Otherwise it can be deleted.

## sql2011 (uncited; existence only)
- key: sql2011
- source_url: https://openlibrary.org/isbn/9781558608559.json; search results pointing to https://dl.acm.org/doi/10.5555/862872
- access_level: abstract_or_landing (catalogue record only)
- existence: CONFIRMED. "Temporal Data and the Relational Model" by C. J. Date, Hugh Darwen and Nikos A. Lorentzos, Morgan Kaufmann, ISBN 1-55860-855-9, 422 pp.
- metadata_discrepancies:
  - **Year is ambiguous.** The Open Library / LoC record gives publish_date "2003" (LC class "QA76.9.D3 D3729 2003"; LCCN 2002110398). Retailer and search listings give 2002. The bib says 2002.
  - **The key is misleading.** The book predates the SQL:2011 standard (ISO/IEC 9075:2011) and is not about it.
  - The entry is uncited and not printed.
- claim_support: N/A (not cited)
- proposed_bib_fix: If it gets cited, rename the key (for example `date2003temporal`) and use `year = {2003}`, the LoC catalogue date. Add `isbn = {1-55860-855-9}`. If SQL:2011 itself is meant, cite ISO/IEC 9075-2:2011 or Kulkarni and Michels, "Temporal features in SQL:2011", SIGMOD Record 41(3), 2012. I did not verify the Kulkarni and Michels reference in this audit.

---

## Summary of issues
1. **longmemeval (paper text, lines 856-860 and 998).** The paper calls LongMemEval conversations "human-written". The source says they are "LLM-simulated and human-edited", with filler sessions from self-chat, ShareGPT and UltraChat. Line 998: NOT_SUPPORTED. Line 860: PARTIAL; the knowledge-update and timestamp details are supported.
2. **toki: PARTIAL.** "with released code": the arXiv-stated repo github.com/ZenAlexa/toki-bitemporal-memory returns 404 as of 2026-10-21.
3. **memgpt.** Wrong entry type (`@inproceedings` with booktitle = arXiv preprint). It renders as "in arXiv preprint ...".
4. **forgeteval.** The bib title does not appear in the source. The author should be Dongxu Yang rather than the org "DeepLethe".
5. **graphiti.** The bib title is a paraphrase, not the repo's. Tag v0.29.2 is confirmed.
6. **Published venues missing.** The bib cites arXiv for papers now published elsewhere: hipporag2 (ICML 2025, PMLR 267:21497-21515), minja (NeurIPS 2025), memoryagentbench (ICLR 2026), amemguard (ICML 2026), mem0 (ECAI 2025, FAIA, DOI 10.3233/FAIA251160), and locomo (ACL 2024, uncited).
7. **Missing details only.** hindsight lacks pages and DOI; snodgrass1985 lacks a DOI.
8. **sql2011 (uncited).** The year is 2002 in the bib versus 2003 in the LoC record, and the key name is misleading.

All other verdicts are SUPPORTED. All 17 cited keys and both uncited keys exist. All three pinned GitHub revisions exist: lethe b6053b7, graphiti v0.29.2 and hindsight 1549987.
