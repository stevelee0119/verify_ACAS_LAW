# TK-59 F1 화면 정보 손실(AI 진단·인젝션 finding 미표시, P1) · 배정표 API 다중 사용자 403(P2)
- 유형: 정보 손실(P1), 권한 정책 누락(P2) — F1(PR #13 d73a8ea)이 새로 만든 결함
- 발견: F1 독립 감사(G8, Codex, 2026-10-04). 평가 측 재현: `tests/acceptance/test_f1_screen_protected.py`(T2r·T6a)가 d73a8ea에서 실패
- 작성: evaluator 2026-10-04 · 입력은 지어낸 합성 값

## 1. P1 — AI·보안 탭으로 배정된 finding 중 AI 진단(5종)·인젝션(17종)의 제목이 어느 탭에도 보이지 않는다
- '확인할 항목'은 AI·보안 탭 배정 유형을 걸러 낸다(`isAISecurityFinding`).
- 그런데 AI 탭은 보안 카드(SECURITY_CARD)만 finding을 하나씩 보여 준다. AI 진단 카드는 문서 단위 판정만, 인젝션 카드는 건수만 보여 준다.
- 그 결과 STYLE_SHIFT(실제 authorship 엔진이 생성) 같은 AI 진단 finding과 PROMPT_INJECTION_SUSPECTED 같은 인젝션 finding은 제목을 볼 수 없고, 열어서 검토 상태를 바꿀 수도 없다. F1 전에는 '확인할 항목'에 모두 보였다.
- HIGH 이상 안내 배너가 AI 탭으로 보내지만, 거기서 해당 항목을 찾을 수 없다.
- 재현(T2r): 범주마다 합성 finding 1건씩 공급 → 문체 급변·인젝션 제목 미표시(보안·검토 항목은 표시).

## 2. P2 — 다중 사용자 모드에서 `GET /api/finding-categories`가 로그인한 모든 역할에 403
- `apps/api/access.py`의 경로별 허용 목록에 이 경로가 없어 기본 거부("No authorization policy for this route")로 끝난다. 관리자도 403이다.
- 화면은 실패 시 모든 항목을 '확인할 항목'에 보이는 대체 동작이라 정보 손실은 없지만, 운영(다중 사용자)에서는 F1 분류가 작동하지 않는다.
- 재현(T6a): 비로그인 401은 정상, 관리자·구성원·열람자 403.

## 3. 요구
- P1: AI·보안 탭의 **세 카드 모두** 자기 범주의 finding을 하나씩 보여 준다(제목·심각도, 누르면 기존 상세 보기 `openFinding`, 검토 상태 조작 가능). 보안 카드와 같은 방식을 쓴다. 범주 판단은 배정표 API 응답(`categories`)으로 한다(하드코딩 금지, T4).
- P2: `apps/api/access.py`의 읽기 허용 목록(`/privacy-notice` 등이 있는 줄)에 `/finding-categories`를 추가한다. 이 응답은 유형·탭 배정과 집계뿐이라 사건 자료가 없다.
- 지시 사전 점검(평가 측): P2 한 줄 수정으로 T6a와 `tests/test_auth.py`(무인증 경로 전수 시험 포함)·`tests/test_finding_categories.py`가 모두 통과함을 확인했다.

## 4. 수용
- `tests/acceptance/test_f1_screen_protected.py`(T2r·T6a)와 `test_f1_protected.py`(T1~T5) 통과. 시험 파일은 고치지 않는다.
- 기존 F1 브라우저 시험 통과(찾는 위치 변경만 허용).
- 재감사(G8): 수정 head에서 Codex가 감사 항목 A3·A4·A6를 다시 본다.
