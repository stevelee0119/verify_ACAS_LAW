# 구현 에이전트 지침 (Codex 주력 · Antigravity)

먼저 [docs/AGENT_ROLES.md](docs/AGENT_ROLES.md)를 읽는다. 아래는 그 요약이다.

- 너는 **구현 에이전트**다. 제품 코드(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`)를 고친다.
- 다음은 수정하지 않는다: `tests/acceptance/**`, `tests/fixtures/**`, `scripts/eval_testset.py`, `scripts/scorecard.py`, `scripts/score_gate.py`,
  `scripts/probe_document.py`, `scripts/score_report.py`, `scripts/verify_all.py`, `scripts/check_case_literals.py`, `scripts/regression_gate.py`, `scripts/check_hardcoding_diff.py`, `scripts/check_test_edits.py`, `scripts/check_protected_paths.py`, `scripts/ci_failed_tests.py`, `docs/scorecards/**`, `.github/workflows/score-gate.yml`, `.github/workflows/ci.yml`, `docs/AGENT_ROLES.md`, `AGENTS.md`, `CLAUDE.md`.
  필요하면 `docs/handoff/`에 요청 티켓을 남긴다. 이 경로를 평가 측이 아닌 커밋이 바꾸면 CI의 '보호 경로 변경 점검'이 실패한다(평가 측이 검토해 승인 목록에 적으면 통과).
- **사건 고유 값(당사자명, 사건번호, 금액, 수치), 서면 문구(한글 열 글자 이상 그대로 따온 것), 서면의 영문 대문자 식별자(12자 이상)를 코드에 넣지 않는다.** `tests/acceptance/test_no_case_literals.py`가 막는다. 숫자만 빼고 서면의 문구로 정규식을 짜는 것도 맞춤 수정이다.
- 새 규칙은 값·문장이 다른 양성 예시 3건 이상, 대조군 3건 이상의 시험과 함께 낸다.
- 작업은 `docs/handoff/`의 티켓 단위로 한다. 티켓의 수용 기준은 측정 도구 출력이다. 서면 한 건에 맞춘 수정은 하지 않는다.
- 커밋 전에는 **바꾼 파일과 관련 시험만** 돌린다. `verify_all`(`--quick` 포함)은 돌리지 않아도 된다. 같은 점검을 CI가 같은 SHA에서 돈다(2026-10-04 사용자 승인 '구현·평가 중복 제거').
  푸시 뒤 CI가 실패하면 그 job 로그 끝의 '실패 시험 목록'을 보고 고친다. 보고는 PR 코멘트 3줄(바꾼 것·남은 것·'검토 요청')로 한다. 완료 보고서 파일은 라운드 첫 완료와 탐지 규칙 변경 때만 쓴다. 커밋 메시지에는 점수 변화(아는 경우)와 `Agent: implementer`를 적는다.
- 판정은 같은 SHA의 CI(Linux, Python 3.11, tesseract 5.3.4)로 한다. 로컬 환경이 달라도 된다.
- 검출 휴리스틱(개인정보·법리 규칙)을 바꾸면 코드보다 먼저 `docs/handoff/requests/`에 1쪽 이내 설계 메모를 낸다. 같은 접근이 두 번 실패하면 접근을 바꾼다.
- 평가 측 비공개 세트의 수치는 알 수 없으므로 보고서에 적지 않는다. 보고서의 diff stat·시험 결과는 최종 커밋 SHA 기준이어야 한다(미커밋 트리 금지).
- 브랜치 규칙: 작업은 새 브랜치에서 하고 PR로 올린다. 병합 전 CI 필수 확인 3개(점수 하락 게이트·테스트·Docker OCR readiness)가 같은 SHA에서 성공해야 한다. 강제 푸시, 통합 브랜치(`Steve_ACASiaLAW`·`main`)에 직접 푸시하는 것은 금지다.
- 점수 기준선을 낮추지 않는다.
