# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-05 평가 측(F2 158d6d4 2차 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-05 (8)]

0. 규칙(AGENTS.md)
   - 커밋 전에는 바꾼 부분의 시험만 돌린다.
   - 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청')를 단다.
   - 리베이스·강제 푸시 금지(병합 커밋).
   - 보고서의 시험 건수·버전은 실제 출력 그대로 적는다(pytest 마지막 요약 줄, config.py의 version).
     예: 이번 보고서의 '20 passed'는 실제 25, '70 passed'는 실제 73이었다.

[A] PR #13 F1 — 병합 완료(Steve_ACASiaLAW 7f5399f). 할 일 없음.

[B] PR #17 F2 — 158d6d4 불승인(보완 필요). 브랜치 antigravity/f2-review-items.
    서버 review_items, 4열 표, 임시 섹션 제거와 정보 보존, 보안 배너는 확인됐다. 그대로 둔다.
 0) CI 실패 1건(T2r)은 평가 측 시험의 대기 결함이었다. 제품 탓이 아니다.
    - 평가 측이 tests/acceptance/test_f1_screen_protected.py를 보강해 Steve_ACASiaLAW에 넣는다(평가 측 PR).
    - 그 PR이 병합되면 `git merge upstream/Steve_ACASiaLAW`(병합 커밋)로 받는다. 이 파일은 고치지 않는다.
 1) TK-60 보완 — docs/handoff/TK-60_f2_row_workflow_broken_and_workflow_controls_lost.md 4절 전부.
    a. 행 안 저장: 기존 계약을 쓴다. API는 바꾸지 않는다.
       - 지금 값과 revision을 읽고, 바꾼 칸만 덮어 PUT한다(메모·담당자·우선순위 보존).
       - 상태 대응: 확인 전 = NOT_STARTED/UNDECIDED, 지적 수용 = COMPLETED/AGREED,
         오탐 = COMPLETED/FALSE_POSITIVE, 조치 완료 = COMPLETED/UNDECIDED.
       - 409면 알리고 다시 읽는다. 성공 안내는 응답을 받은 뒤에만 띄운다.
    b. finding이 여럿인 행은 연결 finding 전부에 적용한다. 기존 POST /api/projects/{id}/reviews를 쓴다.
    c. 행 안에 우선순위(1~3)·담당자 조작을 둔다.
    d. 기존 진행 상태·담당자 필터, 행 선택 체크박스(일괄 검토), 우선순위 정렬을 통합 표에 다시 연결한다.
       - 지금 F2는 필터가 무반응이고 체크박스가 0개다.
 2) 시험
    - test_f2_inline_workflow_manipulation의 본문 단언을 실제 계약(workflow_state·decision·revision)으로 고친다.
    - 실제 API(TestClient)로 '오탐 저장 → /findings의 review_status = FALSE_POSITIVE' 시험을 추가한다.
    - 브라우저 시험을 추가한다: 필터 행 수, 체크박스 일괄 검토, review_items 경로에서 연결 finding 2건 행의 묶음 표시.
    - 기존 시험의 내용 단언은 바꾸지 않는다.
 3) 보고서 정정 — docs/handoff/requests/41_f2_completion.md
    - 시험 건수를 실제 출력으로 고친다.
    - '수정 파일 7개'를 실제 개수로 고친다.
    - '남은 것'을 실제대로 적는다.
 4) 로컬에서 돌릴 것
    - 보호 시험: tests/acceptance/test_f1_protected.py, tests/acceptance/test_f1_screen_protected.py
    - tests/test_f2_review_items.py, tests/test_f2_review_screen_browser.py
    - tests/test_workspace.py
    - 기존 브라우저 시험 전부: tests/test_*browser*.py, tests/test_frontend_*.py, tests/test_drive_rag_relevance.py, tests/test_reasoning_layout.py
    - 푸시 뒤 PR #17에 '검토 요청'을 단다.

[C] FT·F3 — 아직 착수하지 않는다. F2 수용 뒤 평가 측이 T10·T11(FT)을 고정하고 알린다.
```
