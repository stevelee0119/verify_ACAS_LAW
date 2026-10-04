# TK-42 관리자 화면 스크립트가 선언을 잃어 쪽 초기화가 중단됨 (7차 R4·S5가 만든 P1 회귀)
- 유형: 회귀(프런트엔드, **P1**) · 기준: 7차 최종 4da3910(시작 7adf43f에서는 정상) · 작성: evaluator 2026-10-03 · 근거: 평가 측 독립 측정([HISTORY 12절](../scorecards/HISTORY.md))

## 증상·증거
- `apps/web/static/admin.js`를 고치면서 **`let ready = false, initialized = false, previousHash = "";` 한 줄이 지워졌다**(`git diff 7adf43f 4da3910 -- apps/web/static/admin.js`의 `-` 줄, `+` 짝 없음). 파일은 `"use strict"`이므로 `initialized`·`ready`·`previousHash`가 선언 없이 읽히면 `ReferenceError`다.
- 브라우저(Playwright Chromium) 재현: 시작 7adf43f는 쪽 오류 0, `#adminNavigation`·`#jobControls` 있음. 4da3910은 **쪽 오류 `initialized is not defined`**, `#adminNavigation`·`#jobControls` **없음**. `operations.init()`이 `adminUI.init()`에서 예외로 끝나 사용자 관리 메뉴와 작업 제어 막대가 만들어지지 않는다. **영향은 관리자 화면에 한정되지 않는다**(독립 감사 A7-06, 코드로 확인): `app.js` 끝은 `workflowUI.init(); operationsUI.init(); projectTools.init(); calculationWorkbench.init();` 뒤 `init()`(건강 확인·신원·`loadProjects`)을 순차 실행하므로 `operationsUI.init()`의 예외가 **뒤 세 호출과 `init()`을 모두 막아** 프로젝트 조회가 시작되지 않고 화면이 '연결 확인 중'에 남는다. 관리자 권한 확인 이전에 호출되므로 일반 사용자에게도 해당한다(배포된 main의 장애를 검증한 것은 아니다). `operations.js`의 `refreshIdentity`·로그인 경로도 `adminUI.setIdentity()`를 부르므로 같은 예외를 만난다.
- 결과: 브라우저 시험(`tests/test_frontend_*.py` 외 `test_analysis_completion`·`test_reasoning_layout`·`test_drive_rag_relevance`, 197건) 시작 197 통과 → 4da3910에서 처음 55건을 돌린 시점에 **통과 4·실패 34·오류 17**(중단). GitHub `CI` 테스트 job은 20분 제한에서 **취소**됐다(시험이 시간 초과를 반복). 평가 측이 **그 한 줄만 되살린** 작업 트리에서는 197건 모두 통과 — 원인은 이 한 줄뿐이다.
- 기존 시험이 못 잡은 이유: 구현 측 보호 시험(TK-37)은 정적 문자열 점검이고, `tests/frontend_auth.test.cjs`는 `adminUI`를 가짜로 둔다. 구현 보고서에 **전체 시험·브라우저 시험 실행 기록이 없다**(지시서 5절 `pytest -q --ignore=tests/acceptance`, 0.3.5 위반).

## 요구
1. 지워진 선언을 되살린다(평가 측 검증 형태: `let active = …` 줄 아래 `let ready = false, initialized = false, previousHash = "";`). 다른 변경은 금지.
2. 화면 스크립트를 고친 커밋은 **브라우저 시험 전체**를 로컬 또는 CI에서 끝까지 돌린 결과를 보고한다.

## 수용
- 평가 측 시험 `tests/acceptance/test_round7_findings.py::test_admin_script_initializes_without_reference_errors` 통과(Node로 `admin.js`를 가짜 DOM에서 실행, 선언이 지워지면 실패), 같은 파일의 `…rejects_prototype_tab_names…`는 XPASS(평가 측이 표시 제거), 브라우저 시험 197건 통과, `CI` 테스트 job 20분 안에 완료.
