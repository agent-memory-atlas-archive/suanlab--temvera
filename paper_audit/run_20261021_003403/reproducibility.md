# Reproducibility — run_20261021_003403

## 달성한 검증 수준
**봉인된 실행 기록으로부터의 재계산과 재생성**까지입니다. LLM을 부르는 실험(외부 시스템 실행)은 다시 돌리지 않았습니다(`ALLOW_PAID_SERVICES: false`, `EXPERIMENT_SCOPE: reproduce_existing`). 따라서 "결과 재현"은 봉인된 사례별 기록이 원고의 수치를 낳는다는 확인이고, 시스템이 같은 답을 다시 낸다는 확인은 아닙니다. 후자는 원고의 반복 실험(E-089: 4개 셀 × 4회, 전체 정확도 동일)이 부분적으로 다룹니다.

## 자료·코드 계보
- 생성기 `src/temvera/generator.py` → 자연어 변환 `nl_workload.py` → 외부 시스템 재생 `external_experiment.py`(forward-checkpoint) → 봉인 실행 `experiments/runs/<id>/`(config, environment, results, transcript, checksums) → 채택 목록 `experiments/accepted-runs.json`(64개).
- 원고 수치: `scripts/verify_paper_claims.py`(기준선 279개, 수정본 291개)와 `scripts/recompute_paper_numbers.py`(표 재계산). 그림: `scripts/make_figures.py`. 두 법칙: `scripts/analyze_filtering_laws.py`. 정정 실험: `scripts/analyze_corrections.py`(사전 등록 `docs/preregistration-h6.md`, 커밋 `5272ced`).
- 봉인되지 않은 수치(본문에 명시하도록 수정함): Mem0 dropped-update 15·23건(실행 로그), 정답 길이 2-46(데이터셋 필요).

## 환경
- 저장소 `/home/suan/project/Temvera` @ `ae5aadb` (main, origin보다 1커밋 앞섬), 작업 트리 깨끗(이번 감사 디렉터리 제외).
- CPython 3.11.15(`.venv`), pytest, ruff; TeX: latexmk + 동봉 IEEEtran.cls V1.8b, IEEEtranN.bst.
- 외부 시스템 실행 환경(다시 돌리지 않음): Mem0 0.1.118, Graphiti 0.29.2 + Neo4j 5.26, LangMem 0.0.30(별도 venv), Cognee 1.4.2(별도 venv), hindsight-api 0.9.1(별도 venv의 데몬).

## 실행한 명령 (execution/commands.tsv, 누적 67.6초)
| 이름 | 명령 | 결과 | 시간 |
|---|---|---|---|
| verify_artifacts | `temvera verify-artifacts experiments/accepted-runs.json experiments/runs` | valid | 0.3s |
| recompute_tables | `python scripts/recompute_paper_numbers.py --check` | rc 0 | 1.0s |
| verify_claims | `python scripts/verify_paper_claims.py` | 279/279 | 7.2s |
| analyze_bounds | `python scripts/analyze_filtering_laws.py` | rc 0, 재구성 불일치 0 | 3.8s |
| analyze_corrections | `python scripts/analyze_corrections.py` | rc 0 | 0.3s |
| make_figures_copy | `python scripts/make_figures.py` 전후 비교 | 3개 그림 바이트 동일 | 1.6s |
| pytest | `pytest -q` | 전부 통과 | 44.7s |
| ruff | `ruff check .` | 통과 | 0.0s |
| build_original | `latexmk -pdf paper/main.tex` | 11쪽, 넘침 0 | 0.1s |
| verify_claims_revised | `python revised/scripts/verify_paper_claims.py` | 291/291 | — |
| build_revised | `latexmk -pdf revised/paper/main.tex` | 12쪽(참고문헌 포함), 넘침 0, undefined 0 | — |

모든 로그는 `execution/<이름>.log`에 있습니다. `make_figures.py`는 `paper/figures/`에 다시 썼지만 바이트가 같아 원본 체크섬이 그대로입니다(`baseline/sha256.txt`, `sha256sum -c` 전부 OK).

## 원 결과와 비교
- 재계산 결과는 원고 수치와 모두 일치(기준선 279개).
- 불일치로 발견해 수정한 것: 0.610(셀 평균) → 0.609(사례 가중, 원고 규약), "1 to 46" → "2 to 46"(유형별 평균).
- 검증기가 다루지 않던 인쇄 수치 12종을 재계산해 일치 확인 후 사본 검증기에 추가(`execution/uncovered_numbers.txt`).
