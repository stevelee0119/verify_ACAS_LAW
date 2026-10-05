# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-05 평가 측(F2 b7dfb0a 3차 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-05 (9)]

0. 규칙(AGENTS.md)
   - 커밋 전에는 바꾼 부분의 시험만 돌린다.
   - 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청')를 단다.
   - 리베이스·강제 푸시 금지(병합 커밋).
   - 보고서의 시험 건수·버전은 실제 출력 그대로 적는다(이번 b7dfb0a 보고 건수는 정확했다).

[A] PR #13 F1 — 병합 완료(Steve_ACASiaLAW 7f5399f). 할 일 없음.

[B] PR #17 F2 — b7dfb0a 불승인(잔여 2건). 브랜치 antigravity/f2-review-items.
    확인된 것은 그대로 둔다: 단일 행 저장, 필터·체크박스·일괄 검토·우선순위 정렬, 행 안 우선순위·담당자.
 1) 복수 finding 행 저장 — TK-60 7절.
    - 지금 일괄 API(POST /projects/{id}/reviews)가 연결 finding 전부에 같은 값을 덮어써서,
      다른 finding의 메모·담당자·우선순위가 대표 finding 값으로 바뀐다(평가 측이 실제 API로 재현).
    - 이 경로는 평가 측의 앞선 지시 오류였다. 지시를 바꾼다:
      a. 연결 finding마다 각자 GET /findings/{id}/workflow로 현재 값과 revision을 읽는다.
      b. 바꾼 칸만 덮어 PUT /findings/{id}/workflow로 보낸다. 단일 행과 같은 경로이고, API는 바꾸지 않는다.
      c. 일부가 409·오류면 실패한 건수를 알리고 다시 읽는다. 성공 안내는 전부 성공했을 때만 띄운다.
    - 시험: 메모·담당자·우선순위가 서로 다른 finding 2건이 연결된 행에서 상태를 바꾼 뒤, 실제 API(TestClient)로 각자 값이 보존되는지 확인한다.
      지금 모의 데이터는 두 finding의 메모가 같아서 이 결함을 잡지 못한다.
 2) push CI '점수 하락 게이트' 실패
    - 원인: test_f2_filters_search_severity_review_status를 test_f2_filters_and_row_counts로 이름을 바꿔 '시험 삭제'로 잡혔다.
    - 함수 이름만 옛 이름으로 되돌린다. 본문(새 단언 포함)은 그대로 둔다.
 3) T2r: 평가 측 PR #20(T2r 보강)이 Steve에 병합되면 `git merge upstream/Steve_ACASiaLAW`(병합 커밋)로 받는다. 그 시험 파일은 고치지 않는다.
 4) 로컬에서 돌릴 것
    - tests/test_f2_review_screen_browser.py, tests/test_f2_review_items.py, tests/test_workspace.py
    - 보호 시험: tests/acceptance/test_f1_protected.py, tests/acceptance/test_f1_screen_protected.py
    - 기존 브라우저 시험 전부: tests/test_*browser*.py, tests/test_frontend_*.py, tests/test_drive_rag_relevance.py, tests/test_reasoning_layout.py
    - python scripts/check_test_edits.py --base 158d6d4 (push CI와 같은 기준)
    - 푸시 뒤 PR #17에 '검토 요청'을 단다.

[C] FT·F3 — 아직 착수하지 않는다. F2 수용 뒤 평가 측이 T10·T11(FT)을 고정하고 알린다.
```
