# TK-60 F2 행 안 검토 상태 저장 실패(거짓 성공) · 기존 진행 상태·담당자 필터와 일괄 검토 선택 상실(P2)
- 유형: 기능 결함(P2) 1건 + 기존 기능 회귀(P2) 1건 + 지시 미충족 1건. 모두 F2(PR #17 158d6d4)의 화면 변경이 새로 만든 것이다.
- 발견: 평가 측 F2 판정(2026-10-05). 실제 API 재현과 브라우저 비교로 확인했다. 입력은 저장소 fixture 서면9·서면8 PDF를 오프라인으로 처리한 결과와 합성 값이다.
- 작성: evaluator 2026-10-05

## 1. 행 안 검토 상태 select가 저장되지 않는다(거짓 성공)
- 화면은 `PUT /api/findings/{id}/workflow`에 `{"review_status": "<값>"}`을 보낸다.
- 이 API의 입력(`WorkflowInput`, `apps/api/routers/workspace.py`)은 `workflow_state`·`decision`·`priority`·`assignee`·`note`·`revision`이다. `review_status`는 무시된다.
- 실제 API 재현:
  - 기록이 없는 finding에 '오탐'을 보낸다. 응답은 200이고 화면은 '검토 상태가 저장되었습니다'를 띄운다. 그러나 서버의 `review_status`는 NEEDS_REVIEW로 남는다. 기본값 기록(revision 1)도 하나 생긴다.
  - 그 뒤 같은 finding에 보내는 저장은 모두 409(revision 0을 보냄)다.
  - 기존 기록(메모·담당자·우선순위)이 있는 finding은 409라서 지워지지는 않는다.
- `tests/test_f2_review_screen_browser.py::test_f2_inline_workflow_manipulation`은 PUT을 모의 응답으로 받고 잘못된 본문(`review_status`)을 단언한다. 그래서 이 결함을 잡지 못했다.

## 2. 기존 검토 작업 기능이 통합 표에 연결되지 않았다(회귀)
F1(7f5399f)과 F2(158d6d4)를 같은 입력과 같은 모의 API로 비교했다. 검토 기록 1건에 담당자와 완료 상태를 넣었다.

| 항목 | F1 7f5399f | F2 158d6d4 |
|---|---|---|
| '담당자 검색' 필터 적용 뒤 행 수 | 서면9 1, 서면8 1 | 12, 10 (무반응) |
| '진행 상태: 완료' 필터 적용 뒤 행 수 | 1, 1 | 12, 10 (무반응) |
| 행 선택 체크박스 | 9, 7 | 0 → '선택 항목 검토' 일괄 검토를 쓸 수 없음 |
| 정렬 | 변호사 지정 우선순위 | 심각도만 |

- 원인: 새 `renderFindings()`가 `workflowUI.matches`·`workflowUI.decorateFinding`·`workflowUI.priority`를 더 이상 부르지 않는다.
- 필터와 일괄 검토 버튼은 여전히 화면에 있어서, 사용자는 기능이 작동한다고 오해한다.

## 3. 지시 미충족 — 행 안 우선순위·담당자 조작이 없다
- 지시(통합 전달문 (7) [B] 2)는 "검토 상태·우선순위·담당자 조작은 행 안에 둔다"였다.
- 화면은 `f.priority`·`f.assignee`가 있을 때만 글자로 보인다. 그런데 `/findings` 응답(`FindingOut`)에는 이 필드가 없어서 실제로는 보이지도 않는다.

## 4. 요구
1. 행 안 저장은 기존 계약을 그대로 쓴다. API는 바꾸지 않는다.
   - 현재 값과 `revision`을 `workflowUI`가 가진 검토 기록(`/projects/{id}/review-workflows`)이나 `GET /api/findings/{id}/workflow`에서 읽는다.
   - 그 값에 바꾼 칸만 덮어 `PUT`한다. 메모·담당자·우선순위를 보존한다.
   - 상태 대응:
     | 화면 상태 | workflow_state | decision |
     |---|---|---|
     | 확인 전 | NOT_STARTED | UNDECIDED |
     | 지적 수용 | COMPLETED | AGREED |
     | 오탐 | COMPLETED | FALSE_POSITIVE |
     | 조치 완료 | COMPLETED | UNDECIDED |
   - 409가 오면 '다른 검토자가 바꿨다'고 알리고 다시 읽는다. 성공 안내는 응답을 받은 뒤에만 띄운다.
2. 행에 finding이 여럿이면 행 조작이 연결 finding 전부에 적용되어야 한다. 기존 일괄 API `POST /api/projects/{id}/reviews`(`expected_revisions` 원자 처리)를 쓴다.
3. 행 안에 우선순위(1~3)와 담당자 조작을 둔다. 같은 저장 경로를 쓴다.
4. 통합 표에 기존 기능을 다시 연결한다.
   - 진행 상태·담당자 필터: 행의 연결 finding 중 하나라도 맞으면 표시한다.
   - 행 선택 체크박스: 연결 finding 전부를 선택에 넣는다.
   - 우선순위 정렬: 우선순위 다음 심각도 순이다.
   - 순수 인용 행(연결 finding 0)은 지금처럼 '저장 불가(정보 전용)'로 둔다.
5. 시험
   - `test_f2_inline_workflow_manipulation`의 본문 단언을 실제 계약으로 고친다: `workflow_state`·`decision`·`revision`이 있고, 메모·담당자가 보존된다. 이 시험은 이번 PR이 새로 만든 것이라 고쳐도 된다.
   - 실제 API(TestClient)로 '오탐 저장 → `/findings` 응답의 `review_status`가 FALSE_POSITIVE' 시험을 추가한다.
   - 브라우저 시험을 추가한다: 담당자·진행 상태 필터가 행 수를 줄이는지, 행 체크박스로 일괄 검토가 되는지, 연결 finding 2건 행(`review_items` 경로)에 '같은 인용에서 파생된 항목' 묶음이 보이는지.

## 5. 지시 사전 점검(평가 측, 158d6d4)
- 위 대응표대로 `workflow_state`·`decision`·`revision`과 기존 메모·담당자·우선순위를 함께 보내 4개 상태를 차례로 저장했다. `review_status`는 ACCEPTED → FALSE_POSITIVE → RESOLVED → NEEDS_REVIEW로 바뀌었고 메모·담당자·우선순위는 그대로였다. API 변경이 필요 없다.
- 관련 기존 시험 `tests/test_workspace.py`·`tests/test_identity_security.py`: 86 passed.

## 6. 수용
- 위 시험과 보호 시험(T1~T5, T2r, T6a) 통과.
- 기존 브라우저 시험 전부 통과: `tests/test_*browser*.py`, `tests/test_frontend_*.py`, `tests/test_drive_rag_relevance.py`, `tests/test_reasoning_layout.py`.
- 평가 측이 같은 비교(F1 대비 필터·선택·정렬, 실제 API 저장)를 다시 돌려 확인한다.
