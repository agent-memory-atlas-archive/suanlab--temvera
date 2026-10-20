# Final report — run_20261021_003403

**최종 상태: 검토와 가능한 수정 완료.** 120개 항목 모두 판정했습니다. 남은 OPEN은 4개 항목(이슈 6건)이며, 모두 저자 결정이나 원고 밖 작업이 필요한 것입니다. BLOCKED와 NOT_REVIEWED는 없습니다. 수정 완료가 제출 가능을 보증하지는 않습니다.

## 범위
- `paper/main.tex` 1-1147행 전부(표 9, 그림 3, 선언문, 감사 문단), `refs.bib` 31개 항목, 그림 3개(재생성·렌더링), 제출용 초록 파일.
- 부록은 없습니다. 원장(evidence-ledger)은 원고가 인용한 행만 읽었습니다.
- 참고문헌: 17개는 서브에이전트가 1차 출처에서 확인했고, 그중 LongMemEval·TOKI·Mem0 DOI는 직접 재확인했습니다. 나머지 12개는 2026-10-19에 초록을 직접 확인한 기록을 사용했습니다.
  - 전문 확인: LongMemEval, Snodgrass·Ahn, ForgetEval/Graphiti README.
  - 나머지는 초록이나 랜딩 페이지 수준으로만 확인했습니다.

## 120개 항목 집계
PASS 85 · FIXED 28 · OPEN 4 · NOT_APPLICABLE 3 · BLOCKED 0 · NOT_REVIEWED 0 (`checklist.csv`)

## 이슈 31건 (`issues.csv`)
P1 2 · P2 16 · P3 13. 상태는 FIXED 25 · OPEN 6입니다. FIXED 중 3건(I-16, I-17, I-19의 초록 부분)은 이전 승인 문구라 저자 승인이 필요합니다.

### P1 (둘 다 수정)
- **I-19 LongMemEval을 "human-written"으로 기술.** 원문(§A.1-A.2)에 따르면 LLM(Llama 3 70B) self-chat으로 만든 뒤 주석자가 편집한 대화입니다. 초록, 서론, §V, §VI-G, §VI-J, §VIII, Limitations의 11곳을 고쳤습니다.
- **I-01 "all at temperature 0"은 사실이 아님.** LangMem은 공급자 기본값, Hindsight는 추출 0.1·reflect 0.9입니다. 코드와 라이브러리 기본값으로 확인했고, §V와 Limitations를 고쳤습니다.

### 주요 P2 (수정)
- **수치 오류**: 0.610은 셀 평균이었습니다. 원고 규약(사례 가중)에 맞춰 0.609로 고쳤습니다.
- **서술 오류**: Mem0·LangMem을 "어느 쪽으로 읽어도"라고 했으나 실제로는 한 방식으로만 읽었고, 반복 실험을 "유일한"이라고 했으나 이후 반복이 더 있었고, 두 모델 조건을 Cognee·Hindsight까지 확장해 썼습니다.
- **측정하지 않은 결론**: 계측하지 않은 Graphiti 비용에 대한 결론을 고쳤고, 비용 일반화의 범위를 좁혔습니다.
- **인용·참고문헌**: TOKI의 "코드 공개"(저장소 404)를 뺐습니다. 10-19에 추가한 참고문헌 12편이 arXiv ID 없이 인쇄되던 문제를 고쳤습니다.
- **재현성 주장의 범위**: 봉인 기록에 없는 수치 4개(로그·데이터셋 기반)를 §VIII에 예외로 명시했습니다. 검증기에 없던 인쇄 수치 12개를 재계산하고 사본 검증기에 추가했습니다.
- **기여와 공개 문구**: 기여 목록에 §VI-H·§VI-I를 넣고, 삭제 관련 선행연구와 어긋난 표현을 고쳤습니다. AI 사용 공개에 실험 제안·실행 사실을 추가했습니다(승인 필요).

### OPEN
- I-24 이전 투고처 초안 잔존
- I-25 제출용 릴리스가 원고보다 이전
- I-26 초록 길이
- I-27 다중 비교 문장
- I-30 초록의 k=5 단서
- I-31 원고 밖 문서의 "human-written"

## 실행한 검증
- 기준선:
  - 실행 검증 valid, 표 재계산 통과, 수치 279개 일치
  - 두 분석 스크립트 정상, 그림 3개 재생성 바이트 동일
  - pytest·ruff 통과, 빌드 11쪽·넘침 0
- 수정본:
  - 수치 291개 일치, 빌드 12쪽(참고문헌 포함; ICDE 제한은 참고문헌 제외 12쪽)
  - 넘침 0, 미정의 참조 0, 새 arXiv ID 12개 모두 인쇄 확인
  - p1·p4·p10·p11 시각 확인
- 원본 무변경: `baseline/sha256.txt` 전부 OK. 커밋·push 없음.

## 산출물
- 수정본: `revised/paper/main.tex`, `revised/paper/main.pdf`, `revised/paper/refs.bib`, `revised/paper/abstract.txt`, `revised/scripts/verify_paper_claims.py`
- 보고서: `state.md`, `coverage.csv`, `checklist.csv`, `claim_evidence.csv`, `references.csv`, `issues.csv`, `revision_log.md`, `reproducibility.md`, `experiment_plan.md`, `author_questions.md`
- 실행 기록: `execution/`(명령·로그, 차이 파일, 미검증 수치 목록, 참고문헌 확인 보고서, 렌더링)

## 한계
- LLM 시스템 실험은 다시 실행하지 않았습니다. 재현 수준은 봉인 기록 재계산까지입니다.
- 참고문헌 대부분은 초록이나 랜딩 수준으로만 확인했습니다.
- ICDE 공식 요건은 오늘 다시 확인하지 않고 2026-10-02 기록에 의존했습니다.


---

## 추가: 저자 결정 반영 (2026-10-21)

저자 답변(author_questions Q1-Q7)에 따라 다음을 처리했습니다.
- **Q1 초록**: 세 가지 수정을 반영했습니다. "at k=5"는 넣지 않았습니다. §V가 k=5를 전반에 명시하므로 초록 수치가 모두 k=5 기준이라, I-30은 결함이 아닌 것으로 판정했습니다. 길이는 280단어로 유지했습니다.
- **Q2 AI 사용 공개**: 저자가 지정한 내용으로 바꿨습니다. "The author and the AI system designed the analyses and experiments together, and the AI system ran them."
- **Q6 다중 비교**: §V에 문장을 추가했습니다.
- **Q7 bib**: `locomo`, `sql2011`을 삭제했습니다.
- **Q3 병합**: 수정본을 `paper/`에 반영했습니다(`aaf913d`). 검증기 12개 항목, 원장 E-091(감사 요약), 원장 E-063/E-083과 docstring의 "human-written" 정정도 함께 반영했습니다. 비공개 반론 메모도 갱신했습니다.
- **Q5 이전 초안**: `docs/paper-draft.md`, `paper/arr-checklist.md`에 Superseded 표시를 넣었습니다.
- **Q4 v4 릴리스**: `icde-eab-v4`를 공개했습니다(`169d818`).
  - sha256 `c8a52c07ea4ef21a3c49d772d64a144a7dd25977c48602414716eafdf07441fd`
  - 압축 파일만으로 빈 디렉터리에서 다음을 모두 통과했습니다: 실행 검증, 패키지 검증, 표 재계산, 291개 항목, 두 분석 스크립트, 그림 바이트 동일, pytest, 논문 빌드(12쪽).
  - 이 과정에서 단일 파일 결과(`vector-synonym-compare-v1.json`)가 압축 파일에서 빠지는 결함을 발견해 고쳤습니다(`169d818`).

갱신된 집계:
- 120개 항목: PASS 86 · FIXED 31 · OPEN 0 · NOT_APPLICABLE 3
- 이슈 31건: FIXED 29 · PASS 2 · OPEN 0

**최종 상태: 모든 문제 해결.** 적용 대상에 OPEN, BLOCKED, NOT_REVIEWED가 없습니다. 투고 적합성이나 게재 가능성은 보증하지 않습니다. 또한 참고문헌 대부분은 초록이나 랜딩 페이지 수준으로 확인했고, LLM 실험을 다시 실행하지는 않았다는 한계는 그대로입니다.
