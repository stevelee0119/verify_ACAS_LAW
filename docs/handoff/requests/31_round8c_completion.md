# 8C 완료 보고 — TK-53

## 커밋과 기준

- 구현 SHA: `743c5926b817eef8d06aea9aeee0c222f588ff90`
- 전체 검증 및 첫 PR CI SHA: `b5258c072b31f5a520ffb4766d22f75d5cb3bade` (완료 보고서만 추가된 커밋)
- 시작 브랜치: `evaluator/round8-promotion` 최신 tip `ef79f37ce6fded1bd419966d1b049e4c11afb8cd`
- 작업 브랜치: `codex/round8c-key-context`
- 검증 기준: `--base d20cde2`; 보고서 diff 기준: `78c38dc`
- Python: `3.11.17`
- Tesseract: `tesseract 5.3.4`

## Diff stat (`78c38dc..743c592`)

전체:

```text
 docs/handoff/PROMPT_FOR_ROUND8C_CODEX.md   |   7 +-
 docs/handoff/requests/30_round8c_design.md |  15 +++++
 packages/llm_router/privacy.py             | 100 +++++++++++++++++++++++++++-
 packages/pii_engine/detector.py            |   4 ++
 tests/regression/test_r8c_key_context.py   |  98 ++++++++++++++++++++++++++++
 5 files changed, 219 insertions(+), 5 deletions(-)
```

`PROMPT_FOR_ROUND8C_CODEX.md`의 7줄 변경은 시작 tip에 있던 변경으로, 이번 브랜치에서 수정하지 않았다.

테스트만:

```text
 tests/regression/test_r8c_key_context.py | 98 ++++++++++++++++++++++++++++++++
 1 file changed, 98 insertions(+)
```

## 설계 메모와 구현

설계 메모는 먼저 별도 커밋 `61acb43`으로 추가했다. 정규화된 한국어·영어 이름 키를 단일 detector 라벨 어휘로 분류하고, 성씨 형태가 확인되는 한국어 이름 값에만 이름 문맥을 더한다. JSON 문자열의 원문 검사는 유지하며 주민번호·연락처 등 기존 개인정보 키 처리는 별도로 유지한다.

구현은 설계와 대체로 일치한다. 시험 중 `담당자명`과 `plaintiffName` 키가 라벨 어휘와 연결되지 않는 점을 발견해 정규화 키에서 canonical detector 라벨을 찾도록 했다. 법인 문맥 시험 값은 원문 detector 자체가 `COMPANY`로 탐지하는 값 대신, 원문 검출 없이 이름 키 문맥의 추가 차단만 평가하는 값으로 바꿨다. 런타임 동작 범위는 바뀌지 않았다. 불용어 변경은 하지 않았다.

## 검증 환경과 결과

게시된 환경의 기본 런타임은 Python `3.12.14`, Tesseract `5.5.0`이며 Python 3.11과 한국어 OCR 데이터가 없고 sudo 인증도 제공되지 않았다. 설정의 apt 명령은 이 호스트에서 실행할 수 없었다. 이전에 준비한 Ubuntu 24.04 CI 호환 검증 컨테이너에서 Python `3.11.17`, Ubuntu CI 패키지 Tesseract `5.3.4`, `eng/kor/osd` 데이터와 Chromium을 사용했다. `python -m scripts.check_ocr_runtime`과 OCR 회귀 사례는 통과했다.

아래에 최초 `--skip-ui` 결과와, 설정 Publish 후 브라우저를 설치해 완료한 필수 전체 모드 결과를 모두 기록한다. 전체 모드는 커밋된 SHA `b5258c072b31f5a520ffb4766d22f75d5cb3bade`에서 실행했다.

콘솔 출력:

```text
verify_all — HEAD 743c592, 기준 d20cde2, 모드 skip-ui
  환경: python 3.11.17, tesseract 5.3.4, Linux-6.18.44-x86_64-with-glibc2.39
  [통과] environment: python 3.11.17, tesseract 5.3.4
  [통과] acceptance: 통과 909, 실제 실패 0, strict XPASS 0
  [통과] regression_ledger: 통과 432, 실제 실패 0, strict XPASS 0
  [통과] score_gate: 점수 게이트 통과
  [통과] regression_gate: 회귀 없음
  [통과] hardcoding_diff:   새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
  [통과] test_edits:   기존 시험의 삭제·표시 변경 없음
  [통과] version_policy: 버전 정책: 위반 없음 (버전 변경 없음)
  [통과] full_tests: 통과 3135, 실제 실패 0, strict XPASS 0
요약 저장: artifacts/verify_all.json
```

명령 종료 코드는 `0`이었다. 별도 로컬 실행에서 `tests/regression/test_r8a_structured_privacy.py`와 `tests/regression/test_r8c_key_context.py`가 모두 통과했다. 신규 회귀 파일에는 21개 시험을 추가했다.

전체 모드 콘솔 출력:

```text
verify_all — HEAD b5258c0, 기준 d20cde2, 모드 full
  환경: python 3.11.17, tesseract 5.3.4, Linux-6.18.44-x86_64-with-glibc2.39
  [통과] environment: python 3.11.17, tesseract 5.3.4
  [통과] acceptance: 통과 909, 실제 실패 0, strict XPASS 0
  [통과] regression_ledger: 통과 432, 실제 실패 0, strict XPASS 0
  [통과] score_gate: 점수 게이트 통과
  [통과] regression_gate: 회귀 없음
  [통과] hardcoding_diff:   새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
  [통과] test_edits:   기존 시험의 삭제·표시 변경 없음
  [통과] version_policy: 버전 정책: 위반 없음 (버전 변경 없음)
  [통과] full_tests: 통과 3135, 실제 실패 0, strict XPASS 0
  [통과] browser_tests: 통과 196, 실제 실패 0, strict XPASS 0
요약 저장: artifacts/verify_all.json
```

위 전체 모드 명령도 종료 코드 `0`이었다.

## 푸시, PR, CI

브랜치는 `origin/codex/round8c-key-context`에 일반 push했다. 요청 제목 `8C: TK-53 이름 키 정규화 + 키 문맥 축소`, 대상 `Steve_ACASiaLAW`로 [PR #10](https://github.com/stevelee0119/verify_ACAS_LAW/pull/10)을 열었다. 아래 CI 결과는 검증 SHA `b5258c072b31f5a520ffb4766d22f75d5cb3bade`와 일치한다.

- [CI 테스트 — SQLite, PostgreSQL/pgvector, Redis; 통과 15m49s](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37167658441/job/111333896542)
- [Docker OCR readiness — 통과 57s](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37167658441/job/111333896627)
- [점수 하락 게이트 — 통과 6m15s](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37167658459/job/111333896554)
- Sourcery review — 통과 1m20s

## 남은 일

- 평가 측 검토와 사용자의 승인 뒤 PR을 병합한다. 구현 에이전트는 병합하지 않는다.
