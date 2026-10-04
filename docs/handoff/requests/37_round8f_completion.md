# 8F 완료 보고 — TK-56 / TK-57

브랜치: `codex/round8c-key-context` · PR [#10](https://github.com/stevelee0119/verify_ACAS_LAW/pull/10)

시작 기준은 `3306895`이며, `origin/evaluator/round8-promotion` 최신 `a9e16ab`를 병합 커밋 `91bd457`로 반영했다. 구현 SHA는 `86c215bb881e2cbf0e1c9b0f065d90cdeed82aa2`다. 리베이스·강제 푸시는 하지 않았다.

## 변경 요약

- 이름 문맥은 `privacy.py`를 `86bd035` 판으로 되돌리고 지시된 네 변경과 결정적 영문 라벨 순서만 적용해 8C 기준으로 수렴했다. `detector.py`의 평문 탐지 분리는 유지했다.
- 연락처·주민등록번호에는 문자별 원문 위치를 보관하는 NFKC 탐지 뷰를 적용했다. 정규화된 PHONE/RRN 구간을 원문 span으로 되돌려 실제 라우터 전송 전에 마스킹한다. 날짜·사건번호·금액·사업자번호·법인등록번호·법령 번호는 PHONE/RRN으로 분류되지 않는 대조 시험을 추가했다.
- 기존 OCR 회귀 시험은 라벨 없는 RRN이 줄바꿈을 넘지 않는 동작을 요구한다. 이를 보존하면서 라벨이 있는 주민번호 및 연락처의 줄바꿈 표기는 정규화하도록 조정했다.

## 설계 메모 및 차이

첫 8F 커밋은 [36_round8f_design.md](36_round8f_design.md)다. 구현은 NFKC 문자별 출처 매핑, 정규화 구간의 원문 복원, 법률 식별자·사업자번호 가드를 따른다. 기존 OCR 시험과의 호환을 위해 라벨 없는 RRN의 줄바꿈 경계는 넘지 않도록 했다는 점을 메모에 구체적으로 적지 않았다.

## Diff stat

`git diff 3306895 HEAD --stat`:

```text
 docs/handoff/PROMPT_FOR_ROUND8E_CODEX.md           |  12 +-
 docs/handoff/PROMPT_FOR_ROUND8F_CODEX.md           | 105 +++++++++++
 docs/handoff/PROMPT_FOR_UPLOAD_PRIVACY_NOTICE.md   |  54 ++++++
 docs/handoff/README.md                             |   6 +-
 ...55_round8d_overblock_and_key_head_regression.md |   9 +-
 ...ound8e_structured_regression_and_convergence.md |  27 +++
 docs/handoff/TK-57_contact_rrn_notation_gaps.md    |  24 +++
 docs/handoff/requests/35_round8e_completion.md     |  14 +-
 docs/handoff/requests/36_round8f_design.md         |  11 ++
 docs/handoff/requests/37_round8f_completion.md     |  95 ++++++++++
 docs/scorecards/DAILY_TREND.md                     |   2 +-
 docs/scorecards/HISTORY.md                         |  14 ++
 docs/scorecards/f1_gate_verdict.md                 |  65 +++++++
 packages/llm_router/privacy.py                     | 206 +++++----------------
 packages/pii_engine/detector.py                    | 154 ++++++++++++++-
 tests/regression/test_r8d_key_context.py           |  13 +-
 tests/regression/test_r8e_key_context.py           |   9 +-
 tests/regression/test_r8f_contact_rrn.py           | 100 ++++++++++
 18 files changed, 735 insertions(+), 185 deletions(-)
```

`git diff 3306895 HEAD --stat -- packages/ tests/`:

```text
 packages/llm_router/privacy.py           | 206 +++++++------------------------
 packages/pii_engine/detector.py          | 154 +++++++++++++++++++++--
 tests/regression/test_r8d_key_context.py |  13 +-
 tests/regression/test_r8e_key_context.py |   9 +-
 tests/regression/test_r8f_contact_rrn.py | 100 ++++++++++++++++
 5 files changed, 310 insertions(+), 172 deletions(-)
```

## 전체 검증

실행 환경: Linux, Python 3.11.17, Tesseract 5.3.4. 아래는 구현 SHA `86c215b`에서 실행한 `python scripts/verify_all.py --base d20cde2`의 콘솔 출력이다. 종료 코드 0.

```text
verify_all — HEAD 86c215b, 기준 d20cde2, 모드 full
  환경: python 3.11.17, tesseract 5.3.4, Linux-6.18.44-x86_64-with-glibc2.39
  [통과] environment: python 3.11.17, tesseract 5.3.4
  [통과] acceptance: 통과 909, 실제 실패 0, strict XPASS 0
  [통과] regression_ledger: 통과 489, 실제 실패 0, strict XPASS 0
  [통과] score_gate: 점수 게이트 통과
  [통과] regression_gate: 회귀 없음
  [통과] hardcoding_diff:   새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
  [통과] test_edits:   기존 시험의 삭제·표시 변경 없음
  [통과] version_policy: 버전 정책: 위반 없음 (버전 변경 없음)
  [통과] full_tests: 통과 3192, 실제 실패 0, strict XPASS 0
  [통과] browser_tests: 통과 196, 실제 실패 0, strict XPASS 0
요약 저장: artifacts/verify_all.json
```

## 테스트 표시와 회귀 시험

8F 지시서 2절 C와 실제 표시를 대조했다. 지정 사유의 `xfail(strict=True)`는 다음 21개 항목에만 있다.

- `test_r8d_key_context.py`: `test_name_fields_outside_exact_label_vocabulary_fail_closed` 4개 지정 매개변수; `test_name_key_values_with_spacing_lists_titles_or_particles_are_blocked` 5개 전체; `test_person_role_key_with_attached_particle_keeps_name_stem_context`; `test_non_person_keys_keep_scanning_without_name_key_fail_closed`의 `institutionName`만; `test_uncertain_non_korean_or_non_string_name_field_values_are_blocked` 3개 전체.
- `test_r8e_key_context.py`: `test_explicit_person_name_fields_keep_fail_closed_value_shapes` 5개 전체; `test_name_field_fail_closed_blocks_actual_router_send_in_both_positions`의 `user`, `original_system` 각 매개변수.

그 외 시험의 표시·코드는 바꾸지 않았다. 표적 실행에서 21건은 모두 xfail, XPASS 0이었다. `test_person_label_survives_a_preceding_nonperson_word`는 통과한다.

평가 측 acceptance 시험 `test_round8_known_open_key_signal.py`의 24건은 기존 사유 그대로 xfail이고 XPASS는 없다. 표적 실행에는 21개 TK-56 xfail과 24개 acceptance xfail, 새 8F 연락처·RRN 시험이 포함됐고 종료 코드 0이었다.

## 동일 SHA CI

아래 CI는 모두 구현 SHA `86c215bb881e2cbf0e1c9b0f065d90cdeed82aa2`에서 실행됐다.

- PR CI run [37178502813](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37178502813): Docker OCR readiness 성공; SQLite + in-process Worker, migration, PostgreSQL/pgvector + Celery 단계 모두 성공.
- PR 점수 게이트 run [37178502736](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37178502736): 모든 단계 성공. 시험 삭제·약화 점검도 merge base `a04826f` 기준 통과.
- 별도로 발생한 push 이벤트 점수 게이트 run [37178500443](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37178500443)은 이전 브랜치 커밋 `7aa1c14`를 기준으로 검사해 xfail 표시 단계가 실패했다. 이 비교 기준에는 8F 지시서가 지정한 TK-56 표시 21건이 없어서 생긴 event별 기준점 차이다. PR 점수 게이트는 같은 제품 SHA에서 통과했다. 보호된 `scripts/check_test_edits.py`와 워크플로는 변경하지 않았다.

## 미해결·측정 대기

성명 자동 마스킹은 사용자의 결정대로 8C 수준에 동결했다. 키 신호가 없는 유형과 이름 값 fail-closed의 알려진 미해결은 8C 수렴에 따른다. 연락처·주민등록번호 필수 게이트, 성명 동결 지표, 과차단 지표는 평가 측이 실제 라우터 경로와 비공개 세트로 측정한다. 결과는 추정하지 않는다.

## 8F-1 보완 — 구분 기호가 줄바꿈에 붙은 주민등록번호

평가 측 최신 판 `4858a33`을 merge commit `fac0069`로 반영한 뒤 작업했다. 8F-1 설계 메모는 [38_round8f1_design.md](38_round8f1_design.md)다. 구현 SHA는 `e1bd9ffe4b3af02dc71d413b6310adad22e3c1e4`다.

- 라벨 없는 주민등록번호의 원문 구간에 줄바꿈이 있으면, 줄바꿈 바로 앞·뒤에 NFKC 후 하이픈, Unicode Pd 대시, 또는 U+2212가 있는 경우에만 차단한다.
- 하이픈류 없이 줄만 넘긴 번호는 기존과 같이 탐지하지 않는다. 기존 `test_ocr_spaced_resident_numbers_are_masked_before_leaving`는 수정하지 않았다.
- 새 시험은 구분자 두 방향을 user·system·구조화 값에 실제 `LLMRouter.run`으로 넣고 미전송을 확인한다. 무기호 줄넘김은 탐지되지 않고 전송되며, 사건번호·날짜·금액 대조군도 주민번호로 분류되지 않고 전송된다.

`git diff 7ec9f93 HEAD --stat` (8F-1 증가분):

```text
 docs/AGENT_ROLES.md                                |  1 +
 docs/handoff/PROMPT_FOR_ROUND8F_CODEX.md           | 23 +++++-
 docs/handoff/PROMPT_FOR_UPLOAD_PRIVACY_NOTICE.md   | 23 ++++++
 docs/handoff/README.md                             |  5 +-
 ...ound8e_structured_regression_and_convergence.md |  5 ++
 docs/handoff/requests/37_round8f_completion.md     | 65 ++++++++++++++++
 docs/handoff/requests/38_round8f1_design.md        |  5 ++
 docs/scorecards/DAILY_TREND.md                     | 13 +--
 docs/scorecards/HISTORY.md                         |  6 ++
 docs/scorecards/approved_test_marks.json           | 12 +++
 docs/scorecards/f1_gate_verdict.md                 | 71 +++++++++++++++-
 packages/pii_engine/detector.py                    | 18 +++-
 scripts/check_test_edits.py                        | 34 +++++++-
 tests/regression/test_r8f1_rrn_linebreak.py        | 96 ++++++++++++++++++++++
 tests/test_check_test_edits.py                     | 32 ++++++++
 15 files changed, 395 insertions(+), 14 deletions(-)
```

`git diff 7ec9f93 HEAD --stat -- packages/ tests/`:

```text
 packages/pii_engine/detector.py             | 18 +++-
 tests/regression/test_r8f1_rrn_linebreak.py | 96 +++++++++++++++++++++++++++++
 tests/test_check_test_edits.py              | 32 ++++++++++
 3 files changed, 145 insertions(+), 1 deletion(-)
```

`python scripts/verify_all.py --base d20cde2` 출력은 제품 SHA `e1bd9ff`에서 종료 코드 0이다. 환경: Linux, Python 3.11.17, Tesseract 5.3.4.

```text
verify_all — HEAD e1bd9ff, 기준 d20cde2, 모드 full
  환경: python 3.11.17, tesseract 5.3.4, Linux-6.18.44-x86_64-with-glibc2.39
  [통과] environment: python 3.11.17, tesseract 5.3.4
  [통과] acceptance: 통과 909, 실제 실패 0, strict XPASS 0
  [통과] regression_ledger: 통과 501, 실제 실패 0, strict XPASS 0
  [통과] score_gate: 점수 게이트 통과
  [통과] regression_gate: 회귀 없음
  [통과] hardcoding_diff:   새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
  [통과] test_edits:   기존 시험의 삭제·표시 변경 없음
  [통과] version_policy: 버전 정책: 위반 없음 (버전 변경 없음)
  [통과] full_tests: 통과 3207, 실제 실패 0, strict XPASS 0
  [통과] browser_tests: 통과 196, 실제 실패 0, strict XPASS 0
요약 저장: artifacts/verify_all.json
```

표적 실행에서 새 8F-1 시험, 기존 무기호 줄넘김 시험, 시험 표시 검사 시험이 통과했다. 평가 측 판정의 21개 xfail 표시 및 acceptance xfail 24건은 그대로 유지됐다.

같은 제품 SHA의 CI 결과:

- [PR CI run 37181424993](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37181424993): 성공. SQLite/in-process worker, migration, PostgreSQL/pgvector + Celery broker 테스트 및 Docker OCR readiness 모두 성공.
- [PR score gate 37181425011](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37181425011): 성공. 점수 게이트와 수용·회귀·하드코딩·시험 표시·버전 정책 단계 성공.
- [Push CI run 37181423153](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37181423153): 성공. SQLite/in-process worker, migration, PostgreSQL/pgvector + Celery broker 테스트 및 Docker OCR readiness 모두 성공.
- [Push score gate 37181423159](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37181423159): 성공. 점수 게이트와 전체 보호 단계 성공.
