# 8E 완료 보고 — TK-55

브랜치: `codex/round8c-key-context` · PR [#10](https://github.com/stevelee0119/verify_ACAS_LAW/pull/10)

구현 SHA: `2c52653e12dcb19c6133eb3a9d1b49e9e34e0fc6`. 시작 기준은 `d20cde2`; 판정 대상 기준점은 `a7bd8bd`다. 먼저 `origin/evaluator/round8-promotion`을 병합해 `b9c9ce3`을 만들었다. 리베이스나 강제 푸시는 하지 않았다.

사용자 정정(8E 지시서 0절)에 따라 이름 키 값의 fail-closed를 원본 `system` 경로에 적용했다. 새 회귀 시험은 실제 `LLMRouter.run`을 호출해 동일한 이름 키 입력을 user와 원본 system에 각각 넣고 전송되지 않는 것을 확인한다.

## 변경 요약

- 사람 라벨이 키 앞의 다른 낱말보다 우선하도록 복구했다. 구조화 영문 라벨은 유지했고 평문 탐지기는 변경하지 않았다.
- 값 어휘 목록에 의존하던 비인명 판정을 제거했다. fail-closed를 명시적인 사람 이름 필드 키에 한정하고, 알려진 강한 문맥만 처리한다.
- 키 신호가 없는 역할 명사 유형은 확장하지 않았다. 평가 측 strict xfail 24건이 알려진 미해결 경계를 고정한다.
- 새로 작성한 회귀 시험은 접두어가 있는 사람 라벨, 새 비인명 구절 전송, 이름 값 모양 차단, 키 신호 없는 유형 유지, user/system 실제 라우터 경로를 다룬다.

## 설계 메모 및 평가 측 회신

첫 8E 커밋은 [34_round8e_design.md](34_round8e_design.md)다. 구현은 메모의 좁은 fail-closed 범위를 따랐다. 중간 정정으로 원본 system 경로 검사와 실제 `LLMRouter.run` 검증을 추가했다.

8D 회신에서 지적한 키 의미 추측 및 키 신호 없는 누락 위험은 이번에 키 범위를 넓히지 않고 strict xfail 24건으로 고정했다. 낱말 목록에 기반한 비인명 판정은 제거했고, fail-closed 범위를 강한 이름 필드 신호로 좁혔다. 영문 접두 라벨 지원은 유지했다. 8E 메모에 대한 별도 회신은 보고서 작성 시점까지 확인되지 않았다.

## Diff stat

`git diff a7bd8bd HEAD --stat`:

```text
 CLAUDE.md                                          |   1 +
 docs/AGENT_ROLES.md                                |   2 +
 docs/handoff/PROMPT_FOR_ROUND8D_CODEX.md           | 115 ++++++++++++++++++
 docs/handoff/PROMPT_FOR_ROUND8E_CODEX.md           |  88 ++++++++++++++
 docs/handoff/README.md                             |   9 +-
 ...ame_key_coverage_and_english_label_overreach.md |  69 +++++++++++
 ...55_round8d_overblock_and_key_head_regression.md |  51 ++++++++
 docs/handoff/requests/34_round8e_design.md         |  13 ++
 docs/handoff/requests/35_round8e_completion.md    |  86 +++++++++++++++
 docs/scorecards/DAILY_TREND.md                     |  32 +++++
 docs/scorecards/HISTORY.md                         |  14 +++
 docs/scorecards/RELEASE_PROCEDURE.md               |  70 +++++++++++
 docs/scorecards/VERSION_POLICY.md                  |   4 +
 docs/scorecards/f1_gate_verdict.md                 |  68 +++++++++++
 packages/llm_router/privacy.py                     | 132 ++++++++++++---------
 .../test_round8_known_open_key_signal.py           |  59 +++++++++
 tests/regression/test_r8e_key_context.py           |  94 ++++++++++++++
 17 files changed, 850 insertions(+), 57 deletions(-)
```

`git diff a7bd8bd HEAD --stat -- tests/`:

```text
 .../test_round8_known_open_key_signal.py | 59 ++++++++++++++++++++++++++++++++
 tests/regression/test_r8e_key_context.py  | 94 ++++++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 153 insertions(+)
```

## 전체 검증

실행 환경: Linux, Python 3.11.17, Tesseract 5.3.4. 아래 출력은 구현 SHA `2c52653`에서 실행한 `python scripts/verify_all.py --base d20cde2`의 원문이다.

```text
verify_all — HEAD 2c52653, 기준 d20cde2, 모드 full
  환경: python 3.11.17, tesseract 5.3.4, Linux-6.18.44-x86_64-with-glibc2.39
  [통과] environment: python 3.11.17, tesseract 5.3.4
  [통과] acceptance: 통과 909, 실제 실패 0, strict XPASS 0
  [통과] regression_ledger: 통과 471, 실제 실패 0, strict XPASS 0
  [통과] score_gate: 점수 게이트 통과
  [통과] regression_gate: 회귀 없음
  [통과] hardcoding_diff:   새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
  [통과] test_edits:   기존 시험의 삭제·표시 변경 없음
  [통과] version_policy: 버전 정책: 위반 없음 (버전 변경 없음)
  [통과] full_tests: 통과 3174, 실제 실패 0, strict XPASS 0
  [통과] browser_tests: 통과 196, 실제 실패 0, strict XPASS 0
요약 저장: artifacts/verify_all.json
```

검증은 종료 코드 0이다. `tests/acceptance/test_round8_known_open_key_signal.py` 단독 실행에서도 24건 모두 xfail, XPASS 0이었다. 평문 탐지 불변은 기존 8D 회귀 시험 `test_english_word_containing_label_does_not_trigger_person_detection`으로 확인한다.

## 동일 SHA CI

제품 구현 SHA는 `2c52653e12dcb19c6133eb3a9d1b49e9e34e0fc6`다. 보고서만 추가한 브랜치 HEAD `3306895276e96b3122c7cdbeafa90846bed727fa`의 필수 CI도 성공했다.

- [CI 37174907883](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37174907883): SQLite 통합 테스트, 마이그레이션, PostgreSQL/pgvector + Celery 테스트 모두 성공; Docker OCR readiness 성공.
- [점수 게이트 37174910032](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37174910032): 점수, acceptance, regression ledger/gate, 하드코딩, 시험 변경, 버전 정책 단계 모두 성공.

## 미해결 및 측정 대기

키 신호가 없는 역할 명사 유형은 TK-55에서 정한 알려진 미해결이다. 비공개 세트와 새 즉석 점검의 수치는 평가 측이 측정한다. 본 보고서는 그 결과를 추정하지 않는다.
