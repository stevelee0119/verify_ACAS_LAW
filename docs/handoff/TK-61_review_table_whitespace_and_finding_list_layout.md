# TK-61 '확인할 항목' 표의 과도한 공백 · AI·보안 탭 세부 항목 좌우 배치 불균일 (P3, 표시)
- 유형: 표시 결함(P3). F2(PR #17)와 TK-59 보완(F1)의 화면 배치에서 생겼다.
- 발견: 사용자 보고(2026-10-05, 운영 `main` 67a87ba의 서면9 온라인 실행 결과).
- 재현: 평가 측이 그 결과 JSON을 모의 API로 화면에 공급했다(Chromium 1440×1000).
- 작성: evaluator 2026-10-05

## 1. '확인할 항목' 표(`#reviewTable`)의 과도한 공백
**원인(측정)**
- 표가 `table-layout: auto`라서 머리글의 열 너비(10/25/25/40%)가 지켜지지 않는다.
- 셋째 열의 판정 배지(`.badge … validity-verdict`)는 `white-space: nowrap`이다.
- 행위시법 행의 판정 문구는 긴 한 문장이다("증액·개정 규정 소급 적용 오류 — … (RETROACTIVE_APPLICATION_ERROR)").
- 그래서 셋째 열이 1194px로 늘어나고, 모든 행에서 넷째 열(법리 타당성·AI 의견)이 157px로 좁아진다.
- 넷째 열이 세로로 2000px 넘게 늘어나면서 첫째~셋째 열에 큰 공백이 생긴다.

| 행 | 열 너비(1~4열, px) | 행 높이 |
|---|---|---|
| 현행 | 105 / 301 / **1194** / **157** | 250, **2151**, **2058**, 371, **2486**, 221 |
| CSS 3줄 적용(평가 측 임시 주입) | 113 / 283 / 283 / 452 | 250, 770, 733, 391, 863, 221 |

**요구**
- `#reviewTable { table-layout: fixed; }`
- 셀 안 긴 토큰 줄바꿈: `#reviewTable td { overflow-wrap: anywhere; }`
- 판정 배지 줄바꿈 허용: `#reviewTable .validity-verdict { white-space: normal; display: inline-block; max-width: 100%; }`
- 화면 문구·내용은 바꾸지 않는다.

**선택(같은 PR에 넣어도 됨, 문구·데이터 불변)**
- 셋째 열 근거 문구가 내부 코드(`NOT_ASSESSED`, `OFFICIAL_NOT_FOUND`, `UNVERIFIED_SCOPE`)로 보인다. `label()` 대응표에 사람 말 표기를 추가한다. 기존 용어집(terminology)에 있는 표기를 쓴다.
- 넷째 열의 AI 교차검증 의견이 길면 `<details>`로 접어 행 높이를 줄인다. 기본은 펼침이나 접힘 중 화면 시험이 정하는 쪽으로 한다.

## 2. AI 작성·보안 진단 탭 세부 항목(AI 진단·인젝션·보안 카드)의 좌우 배치
**원인**
- `.security-finding-item`이 `display: flex`(가로)다.
- 제목 버튼(`.link-button`)은 글자 길이만큼 폭이 정해지고 가운데 정렬이며, 설명(`small`)이 나머지 폭을 쓴다.
- 그래서 항목마다 왼쪽 폭이 다르다(160~300px).
- 폭이 좁은 보안 카드에서는 제목이 세 줄로 꺾인다("생성 소프트웨어 정보").

**결정(사용자 요청 → 평가 측 권고 2안)**
- 제목을 위에, 설명을 아래에 둔다. 세 카드에 같은 방식을 적용한다.
- 근거
  - 설명 길이 편차가 크다(한 줄~세 줄).
  - 좁은 카드와 모바일에서 좌우 배치가 무너진다.
  - 다른 목록(모델별 판정, 예전 '확인할 항목' 행)이 위·아래 배치라 화면 전체가 일관된다.
- 요구
  ```css
  .security-finding-item { display: block; }
  .security-finding-item > .link-button { display: block; width: 100%; text-align: left; margin-bottom: 4px; }
  .security-finding-item > small { display: block; }
  ```
- 제목 버튼(누르면 상세 창)과 배지·문구는 그대로 둔다.

## 3. 지시 사전 점검(평가 측, 8b70497)
- 위 CSS를 임시로 넣고 기존 브라우저 시험을 모두 돌렸다: `tests/test_*browser*.py`, `tests/test_frontend_*.py`, `tests/test_drive_rag_relevance.py`, `tests/test_reasoning_layout.py`, T2r·T6a. 결과 **148 passed**. 임시 변경은 되돌렸다.
- `tests/test_frontend_model_opinions.py`의 `.validity-verdict` 내용 단언("근거 결여")은 문구 불변이라 영향이 없다.

## 4. 수용
- 같은 결과 JSON으로 평가 측이 다시 잰다.
  - 표 열 너비가 머리글 비율의 ±5%p 안이다.
  - 첫 6행 중 가장 높은 행이 현행 대비 50% 이하다.
  - 세 카드 세부 항목의 제목 왼쪽 끝 x좌표가 같다.
- 위 기존 브라우저 시험 전부 통과.
- 새 브라우저 시험 1개 이상: 긴 판정 문구가 있어도 표 열 너비가 비율을 지키는지, 세부 항목이 위·아래 배치인지.
- 화면만 바꾸는 변경이라 점수·probe가 전후 같아야 한다.
