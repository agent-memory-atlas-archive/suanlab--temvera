# Revision log — run_20261021_003403

기준선: `paper/main.tex`, `paper/refs.bib` @ `ae5aadb` (2026-10-20 21:20 +0900). 수정본: `revised/paper/main.tex`, `revised/paper/refs.bib`, `revised/scripts/verify_paper_claims.py`. 전체 차이: `execution/main.tex.diff`, `execution/refs.bib.diff`, `execution/verify_paper_claims.py.diff`. 원본은 바꾸지 않았고, 커밋·push도 하지 않았습니다.

행 번호는 기준선 기준입니다. **[승인 필요]** 표시는 이전에 저자가 승인한 문구(초록, AI 사용 공개)를 바꾼 것으로, 사본에만 반영돼 있습니다.

## A. 과학적 의미 또는 수치가 바뀐 수정

| ID | 위치(기준선) | 변경 전 | 변경 후 | 근거 |
|---|---|---|---|---|
| I-01 | L389-392 §V Systems | "all with gpt-4o-mini at temperature 0" | Mem0·Graphiti·Cognee는 temperature 0, LangMem은 라이브러리 기본(공급자 기본값), Hindsight는 추출 0.1·reflect 0.9 | `mem0_adapter.py:58`, `graphiti_adapter.py:92`, cognee `llm/config.py:111`, langmem `knowledge/extraction.py:229`, hindsight_api `config.py:220-223` |
| I-02 | 같은 문단 | 버전 없음 | LangMem 0.0.30, Hindsight는 "실행이 버전을 기록하지 않음, 서빙한 인터프리터에 hindsight-api 0.9.1 설치" | `external-langmem-v1` backbone; `hs-venv` dist-info(2026-08-17) — Hindsight는 근거 있는 추론으로 표기 |
| I-08 | L793 §VI-E | "Exact accuracy moved 0.610 → 0.527 → 0.539" | "Case-weighted exact accuracy moved 0.609 → 0.527 → 0.539" | `scale-cost-mem0-v1` 재계산: 2명 53/87 = 0.6092(사례 가중), 0.6103(셀 평균) |
| I-09 | L1010-1011 §VI-J | "gold answers range from 1 to 46 scoreable tokens across types" | "mean gold-answer length ranges from 2 to 46 scoreable tokens across types" | 유형별 평균 1.9-46.2, 개별 0-67(데이터셋 재계산) |
| I-19 | L72, L120, L353-354, L856-859, L868, L884, L919, L962, L998, L1086, L1094 | "human-written", "real conversations", "real-data" | "annotator-edited conversations", "benchmark conversations", 절 제목 "Does it hold beyond our generator?", 생성 방식(LLM self-chat 후 주석자 편집) 명시 | arXiv 2410.10813 §A.1-A.2 직접 확인. 초록 부분 **[승인 필요]** |
| I-16 | L69-72 초록 | "Deletion divides the same way: …"; "Cost is write-dominated, and where it falls is a design choice." | "In Mem0 and Graphiti, deletion divides the same way: …"; "Cost is write-dominated in Mem0 and read-dominated in Cognee: where it falls is a design choice." | 삭제는 2개 시스템·시드 1개(§VI-C), 비용은 Mem0만 계측, Cognee는 읽기 쪽이 큼(§VI-E) **[승인 필요]** |
| I-05 | L735-737, L742-744, L766-770 §VI-E | "An LLM-backed memory store inverts…"; 캡션에 시스템명 없음; "a store which retains history without filtering it, like Graphiti, is not cheaper at read time either, since its cost is also incurred on write" | "Mem0, which extracts on write, inverts…"; 캡션 "for Mem0"; "Graphiti also extracts on write, so we expect the same profile there, but its cost was not instrumented in these runs." | 비용 계측은 Mem0만(같은 절 L786-788) |
| I-04 | L716-719 §VI-D | "sit in the middle whichever way they are read, because a superseding write destroys its predecessor" | "We read Mem0 and LangMem only at the retrieval layer, but a reader could not lift them far: … capped by a ceiling the history fixes (§VI-H)" | Mem0·LangMem의 reader 구성은 없음; 근거를 §VI-H 상한으로 연결 |
| I-06 | L955-957 §VI-H | "on both backbones and at every scale" | "Graphiti on both backbones and at every scale, Cognee and Hindsight on the main grid" | 분석 대상 실행 목록 |
| I-03 | L538-539, L1097 | "our only same-protocol replication"; Limitations "our one same-protocol replication" | "our first same-protocol replication"; Limitations에 "only those two were replicated", 온도 차이 추가 | E-089 반복 실험 |
| I-15 | L116-130 기여 | (i)에 §VI-H·§VI-I 없음; (iii) "which the closest prior systems describe as a feature but do not measure" | (i)에 상한·정정 결과 추가; (iii) "which the systems describe as a feature but do not measure, and which prior deletion benchmarks judge by what a reader recovers rather than by what the stores retain" | 초록과 일치; §II의 Bemula·MemCut |
| I-17 | L1131-1142 감사 | 제안·실행 사실 없음 | "It also proposed several of the reported analyses and experiments, including those of §VI-H and §VI-I, and ran the experiments once the author had approved them." | 세션 기록 **[승인 필요]** |
| I-20 | L138-139 §II | "TOKI … over a dual-row schema with released code." | "TOKI … over a dual-row schema." | 연결된 저장소 HTTP 404(2026-10-21) |
| I-10 | L1019-1024 §VI-J | 15·23건 출처 미기재 | "counted from the library's error log during those runs, which the sealed artifacts do not keep" | 봉인 실행에 기록 없음 |
| I-11 | L1077-1079 §VIII | "Every figure … paired with a recomputation …" | 같은 문장 + "except four in §VI-J: Mem0's two dropped-update counts, which come from run logs, and the two gold-answer lengths, which need the dataset." | 미검증 수치 분석 |
| I-28 | §VII 신규 문단 | 없음 | "Two harness defects were caught before citation." (Hindsight 빈 답, Cognee 공유 저장소, 이전 원고 0.207 → 현재 0.194) | 원장 E-081, E-082; 수치는 검증기 항목 추가 |
| I-07 | L130 | "three retracted measurements" | "four retracted measurements" | §VII 목록 |
| I-14 | L1030 | 질의 수 없음 | "on 10 queries" | `vector-synonym-compare-v1.json` |

## B. 서지 정보 수정 (refs.bib)

| ID | 항목 | 변경 |
|---|---|---|
| I-21 | memgpt | @inproceedings(booktitle=arXiv) → @article(journal=arXiv preprint) |
| I-21 | forgeteval | 제목 "Benchmarking the Forgetting Axis of Agent Memory Systems", 저자 Yang, Dongxu |
| I-21 | graphiti | 제목 "Build Temporal Context Graphs for AI Agents"(v0.29.2 README) |
| I-22 | hipporag2 | ICML 2025, PMLR 267, pp. 21497-21515 |
| I-22 | minja / memoryagentbench / amemguard | NeurIPS 2025 / ICLR 2026 / ICML 2026 (쪽수 미확인이라 생략) |
| I-22 | mem0 | ECAI 2025, IOS Press, DOI 10.3233/FAIA251160 (Crossref 확인) |
| I-22 | hindsight, snodgrass1985 | 쪽·DOI·출판사 / DOI 추가 |
| I-23 | arXiv @misc 12개 | `howpublished = {arXiv preprint arXiv:<id>}` 추가 — IEEEtranN이 eprint를 출력하지 않아 ID가 빠져 있었음 |

## C. 표현만 바뀐 수정

| ID | 위치 | 변경 |
|---|---|---|
| I-12 | L137 | 인용 번호를 명사구 뒤로 |
| I-13 | L712-714 | "the exception that proves the mechanism" → 사실 서술 |
| I-18 | L593 그림 3 대체 텍스트(인쇄 안 됨) | "every system" → "both deployed systems" |

## D. 검증기(사본) 변경

- `PAPER`를 수정본 원고로, `ROOT`를 저장소 루트로 지정(봉인 실행 경로 유지).
- 바뀐 앵커 3개를 반영("Benchmark conversations:", "test is the benchmark conversations", "the benchmark check covers").
- 새 항목 12개(`_audit_claims`): 비용 실험 3개(0.609/0.527/0.539), Cognee 477·484, 임베딩 비중 0.2%, 턴당 비용 $0.0005, 유형당 10건, 동의어 질의 10개, Cognee v1 오류 40건·0.207, 재현 0.194.
- 결과: 수정본 기준 291개 항목 모두 통과(기준선 279 + 12).
