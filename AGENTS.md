# 구현 에이전트 지침 (Antigravity)

먼저 [docs/AGENT_ROLES.md](docs/AGENT_ROLES.md)를 읽는다. 아래는 그 요약이다.

- 너는 **구현 에이전트**다. 제품 코드(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`)를 고친다.
- 다음은 수정하지 않는다: `tests/acceptance/**`, `tests/fixtures/**`, `scripts/eval_testset.py`, `scripts/scorecard.py`, `scripts/score_gate.py`,
  `scripts/probe_document.py`, `scripts/score_report.py`, `scripts/check_case_literals.py`, `docs/scorecards/**`, `.github/workflows/score-gate.yml`, `docs/AGENT_ROLES.md`, `AGENTS.md`, `CLAUDE.md`.
  필요하면 `docs/handoff/`에 요청 티켓을 남긴다.
- **사건 고유 값(당사자명, 사건번호, 금액, 수치), 서면 문구(한글 열 글자 이상 그대로 따온 것), 서면의 영문 대문자 식별자(12자 이상)를 코드에 넣지 않는다.** `tests/acceptance/test_no_case_literals.py`가 막는다. 숫자만 빼고 서면의 문구로 정규식을 짜는 것도 맞춤 수정이다.
- 새 규칙은 값·문장이 다른 양성 예시 3건 이상, 대조군 3건 이상의 시험과 함께 낸다.
- 작업은 `docs/handoff/`의 티켓 단위로 한다. 티켓의 수용 기준은 측정 도구 출력이다. 서면 한 건에 맞춘 수정은 하지 않는다.
- 변경 뒤 `python scripts/scorecard.py && python scripts/score_gate.py`를 돌려 통과를 확인하고, 커밋 메시지에 점수 변화와 `Agent: implementer`를 적는다.
- 점수 기준선을 낮추지 않는다.
