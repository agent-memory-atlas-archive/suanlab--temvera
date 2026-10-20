# Author questions

조사로 해결되지 않고 저자 판단이 필요한 것만 모았습니다.

## Q1. 초록 수정 승인 (I-16, I-19, I-30, I-26)
초록은 2026-10-20에 승인받은 문구입니다. 수정본(`revised/paper/main.tex` L69-73)에는 다음 세 가지가 반영돼 있습니다.

1. **[사실 오류 수정, 강하게 권함]** "on 43 human-written supersessions from LongMemEval" → "on 43 supersessions in LongMemEval's annotator-edited conversations".
   - LongMemEval의 대화는 Llama 3 70B self-chat으로 만들고 주석자가 편집한 것입니다(원문 §A.1).
2. **[범위]** "Deletion divides the same way" → "In Mem0 and Graphiti, deletion divides the same way".
3. **[범위]** "Cost is write-dominated, and where it falls is a design choice" → "Cost is write-dominated in Mem0 and read-dominated in Cognee: where it falls is a design choice".

추가로 결정하실 것:
- **"at k=5"를 넣을지 (I-30)**: "three independent implementations score 0.000 on valid-time queries"는 k=5에서만 성립합니다. 예산 단서는 지난번 길이 때문에 뺐습니다.
  - 넣으면: 정확해지고 2단어 늘어납니다.
  - 빼면: 본문(§VI-B, 그림 2)에만 단서가 남습니다.
- **길이 (I-26)**: 수정본은 280단어입니다(현재 270). ICDE는 명시 제한이 없고 IEEE 관례는 250 안팎입니다. 줄인다면 후보는 "rendered as natural language and"(5단어)입니다.

## Q2. AI 사용 공개 문구 추가 승인 (I-17)
2026-10-05 승인 문구에 다음 한 문장을 더했습니다(사본만).

> "It also proposed several of the reported analyses and experiments, including those of §VI-H and §VI-I, and ran the experiments once the author had approved them."

세션 기록상 사실입니다(H1·H2·H6 제안, 사전 등록, 실행). 다른 표현을 원하시면 알려 주세요.

## Q3. 수정본을 원고에 반영할지 (병합)
이번 감사는 원본을 건드리지 않았습니다. 반영하려면 다음이 함께 필요합니다.
- `revised/paper/main.tex`, `refs.bib`를 `paper/`로 복사합니다.
- 사본 검증기의 `_audit_claims` 12개 항목과 바뀐 앵커 3개를 `scripts/verify_paper_claims.py`에 옮깁니다. `ROOT`/`PAPER` 경로 변경은 옮기지 않습니다.
- `make_abstract.py`로 `abstract.txt`를 다시 만듭니다.
- 원장 E-063·E-083과 docstring 2곳의 "human-written"을 고칩니다(I-31).
- 원장에 감사 결과 행을 추가합니다.

진행 여부를 알려 주세요.

## Q4. 제출용 릴리스 (I-25)
§VIII은 "a frozen snapshot attached to its submission release"라고 쓰지만, 공개된 최신 릴리스 `icde-eab-v3`는 이후 변경(편차 실험, H6, 초록, 이번 감사)을 담고 있지 않습니다. 병합 후 `icde-eab-v4`를 만들지 결정해 주세요.

## Q5. 저장소 정리 (I-24)
`docs/paper-draft.md`(ICLR 초안)와 `paper/arr-checklist.md`(ACL ARR 체크리스트)가 남아 있고, 옛 서술("human-written" 등)을 담고 있습니다. 공개 아티팩트에 포함되므로 심사위원이 볼 수 있습니다.
- 삭제하지 않았습니다. 머리말에 "대체됨(superseded) — 현재 원고는 paper/main.tex" 표시만 넣을지 정해 주세요.

## Q6. 다중 비교 문장 (I-27)
여러 비교에 Wilson 구간을 쓰지만 다중 비교 언급은 없습니다. 원하시면 §V Scoring 끝에 다음 문장을 넣을 수 있습니다.

> "Intervals are per estimate and are not adjusted for multiple comparisons; the comparisons we draw are descriptive."

현재 원고가 실제로 그렇게 서술하고 있는지는 확인했습니다.

## Q7. 인용하지 않는 bib 항목
`locomo`, `sql2011`은 인쇄되지 않습니다. `sql2011`은 연도(2002 → LoC 2003)와 키 이름이 부정확합니다. 지울지, 그대로 둘지 정해 주세요.
