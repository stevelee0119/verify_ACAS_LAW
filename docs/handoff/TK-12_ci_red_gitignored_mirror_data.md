# TK-12 CI 빨간불: 두 시험이 .gitignore된 미러 데이터에 의존
- 유형: 시험 설계(환경 의존) · 기준 커밋: 4ad64a7 · 작성: evaluator 2026-09-30

## 증상·증거
- main의 `CI` 워크플로(`테스트 (SQLite + PostgreSQL/pgvector + Redis)` 작업의 `pytest -q` 단계)가 4ad64a7에서 실패한다([실행 기록](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/36683167780)). 실패는 정확히 두 시험이다.
  - `tests/test_ground_truth_prepared_brief.py::test_precedent_and_regulation_existence` — `LocalLegalMirror().find_case("2018도15313")`가 `None`
  - `tests/test_ground_truth_prepared_brief.py::test_temporal_retroactive_application_review` — 부정경쟁방지법 제2조 버전이 없어 `review_temporal_application`이 `None`
- 원인: 두 시험은 `config/legal_mirror/*.json`의 판례·조문 자료를 전제로 한다. 이 파일들은 `.gitignore`(17행 `config/legal_mirror/*.json`)에 들어 있어 저장소에는 `README.md`만 있다. 작성자 PC에서는 통과하고 깨끗한 복제본·CI에서는 실패한다. 시험이 들어온 커밋은 c287b12(9/29 22:17)다. 확인한 실행 aa93276·73357d8·4ad64a7이 모두 실패했고 그 사이 커밋의 실행은 취소되었다.
- 평가 측 재현: 깨끗한 복제본(이 세션)에서 같은 두 시험이 실패하고, 4ad64a7의 미러 자동 보강(TK-10)으로도 해결되지 않았다.

## 수용 기준
- CI `pytest -q`가 통과한다. **시험을 건너뛰거나(skip) 기대값을 낮추어 통과시키지 않는다.**
- 두 시험이 쓰는 자료를 저장소 안 시험 자료(`tests/fixtures/` 아래, 전용 미러 폴더)로 두고, 시험이 `LocalLegalMirror(root=<그 폴더>)`로 읽게 한다. 자료는 국가법령정보센터 등 **공식 원문에서 확인한 것만** 쓴다(지어내지 않는다). 2018도15313 판결의 존재, 부정경쟁방지법 제2조 제1호 카목의 신설일(시험이 기대하는 2022-04-20)을 출처 URL과 함께 적는다.
- 시험 자료 폴더는 보호 경로(`tests/fixtures/`)이므로 구현 에이전트는 이 티켓에 자료를 첨부해 평가 에이전트에게 반영을 요청한다(`docs/AGENT_ROLES.md`).
- 해결 전까지 main의 `CI`는 빨간 상태다. 이 티켓과 무관한 변경의 병합 가부 판단에는 `점수 게이트`(`score-gate`)와 `tests/acceptance`를 쓴다.

## 경과(2026-10-01, de243cc)
- 구현 에이전트가 시험 쪽(`MIRROR_ROOT`)을 고치고 자료를 직접 적어 `requests/06_mirror_fixture.md`로 올렸다. **자료를 반영하지 않았다.** 조번호 오류(근로기준법 제107조→실제 제109조)와 출처 불명 URL이 확인되어서다. 자세한 근거는 [TK-21](TK-21_process_round2.md) 1절.
- 해결 경로(사용자 결정): (a) 사용자의 로컬 `config/legal_mirror/*.json` 제공 (b) 평가 에이전트가 공식 원문에서 구성(판례 2018도15313은 공식 확인 필요).
- 그때까지 main `CI`는 빨갛다(이 두 시험 + TK-19의 4건).
