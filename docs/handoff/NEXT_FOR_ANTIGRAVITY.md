# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-04 평가 측(F1 독립 감사 G8 미충족 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-04 (5)]

0. 규칙(AGENTS.md): 커밋 전에는 바꾼 부분의 시험만 돌린다. 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청'). 리베이스·강제 푸시 금지(병합 커밋).
   보고서의 시험 건수·버전은 실제 출력 그대로 적는다(pytest 마지막 요약 줄, config.py의 version).

[A] PR #13 F1 — 독립 감사(G8) 미충족: P1·P2 수정. 티켓 docs/handoff/TK-59_f1_ai_findings_unreachable_and_category_api_403.md (먼저 한다)
 1) 평가 측 PR(보호 시험 T2r·T6a 추가)이 Steve_ACASiaLAW에 병합됐다는 알림 뒤:
    antigravity/f1-review-screen에 `git fetch upstream Steve_ACASiaLAW && git merge upstream/Steve_ACASiaLAW`(병합 커밋).
 2) P1: AI·보안 탭의 세 카드(AI 진단·인젝션·보안) 모두 자기 범주의 finding을 하나씩 보인다 — 제목·심각도, 누르면 openFinding, 검토 상태 조작 가능.
    보안 카드와 같은 방식, 범주 판단은 /api/finding-categories의 categories로(하드코딩 금지). HIGH 이상 배너가 가리키는 항목이 AI 탭에서 보여야 한다.
 3) P2: apps/api/access.py 읽기 허용 목록(`/privacy-notice` 등이 있는 줄)에 `/finding-categories`를 추가한다(평가 측이 이 한 줄로 시험 통과를 확인함).
 4) 로컬: tests/acceptance/test_f1_screen_protected.py, tests/acceptance/test_f1_protected.py, tests/test_auth.py, tests/test_finding_categories.py,
    tests/test_f1_ai_security_tab_browser.py만 돌린다. 시험 파일은 고치지 않는다(기존 F1 브라우저 시험은 찾는 위치만 바꿀 수 있음).
 5) 푸시 뒤 PR #13에 '검토 요청'(head SHA). 평가 측 확인 뒤 Codex가 A3·A4·A6를 재감사한다.

[B] PR #17 F2 — 서버 1단계(review_items) 내용 수용(조건부). 브랜치 antigravity/f2-review-items.
 1) 보고서 정정 — docs/handoff/requests/41_f2_completion.md
    - '버전 상태: 변경 없음 (0.9.13)' → '변경 없음 (0.10.0)'
    - 5절의 'Playwright로 레이아웃과 DOM 구조를 검증' 문장 삭제(이 PR에 화면 변경 없음)
    - 6절 '남은 것'에 'F2 화면(통합 검토 항목 탭) 미구현'을 추가
 2) F2 화면(2단계) — 같은 브랜치에서 이어서 한다. 범위는 docs/handoff/PROMPT_FOR_FEATURE_ROUND_F1.md 1절 F2:
    - '확인할 항목' 탭을 review_items 기반 통합 표로 바꾼다: 위치 / 문서 주장·인용 내용 / 근거 확인 결과 / 법리 타당성·반박·대응 4열.
    - 검토 상태(확인 전·수용·오탐·조치 완료)·우선순위·담당자 조작은 행 안에 둔다(finding이 연결된 행은 기존 /api/findings/{finding_id}/workflow 재사용).
    - 현행 검색·중요도·검토 상태 필터, 같은 인용에서 파생된 항목 묶음, 상세 보기(문서 쪽 보기·강조)를 유지한다.
    - F1의 임시 섹션(#temporaryCitationSection)은 통합 표가 같은 정보를 모두 보이면 없앤다. 인용표·RAG·추가 관련 법조문 정보가 화면에서 사라지면 안 된다.
    - HIGH 이상 보안 안내 배너(F1)는 유지한다. 주장 행은 켜지 않는다(TK-22 전). 화면이 배정표를 하드코딩하지 않는다(T4).
    - 기존 브라우저 시험이 표 구조 때문에 깨지면 찾는 위치만 바꾼다(내용 단언 변경·삭제 금지). 새 화면은 브라우저 시험을 추가한다.
 3) 로컬: tests/acceptance/test_f1_protected.py, tests/test_f2_review_items.py, 바꾼 화면의 브라우저 시험만. 푸시 뒤 PR #17에 '검토 요청'.
 4) [A] 수정 head를 F2 브랜치에도 병합 커밋으로 받는다. PR #17은 F1(PR #13)이 병합된 뒤 base를 Steve_ACASiaLAW로 바꾼다. 평가 측 병합은 화면까지 들어온 뒤 판정한다.

[C] FT·F3 — 아직 착수하지 않는다. F2(화면 포함) 수용 뒤 평가 측이 T10·T11(FT)을 고정하고 알린다.
```
