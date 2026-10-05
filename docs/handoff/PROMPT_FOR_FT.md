# FT 지시서 — 행위시법 검토 보강(요청 16 + TK-34) 1단계: 설계 보충

작성: 평가 에이전트(claude-code) 2026-10-05 · 기준: `Steve_ACASiaLAW` 8b70497(F1·F2 병합 뒤) · 대상: Antigravity
범위·규칙의 원문: [F1 지시서 1절 FT](PROMPT_FOR_FEATURE_ROUND_F1.md), [TK-34](TK-34_item_level_temporal_review.md). 이 문서는 그 원문을 바꾸지 않고 착수 순서와 보호 시험을 정한다.

## 0. 순서
1. **(이번) 설계 보충만 낸다.** 코드를 쓰지 않는다. `docs/handoff/requests/42_ft_design.md`로 PR을 올리고 '검토 요청'을 단다.
2. 평가 측이 회신한다(승인·보완 요구, 새 `rule_id` 승인 여부).
3. 회신 뒤 구현한다. 브랜치는 `antigravity/ft-temporal-review`(기준 `Steve_ACASiaLAW` 최신)이다. FT 커밋은 다른 기능 커밋과 섞지 않는다.

## 1. 보호 시험(평가 측이 고정함 — 구현 측은 고치지 않는다)
`tests/acceptance/test_ft_protected.py`

| 시험 | 지금 | FT 뒤 |
|---|---|---|
| T10 오탐 대조 4개(번호만 바뀐 목, 신설 목을 신설 뒤 행위에 인용 등) | 통과 | 계속 통과 |
| T10 양성 — 기존 `test_prepared_brief_mirror_official.py::test_new_data_ka_cited_for_2020_act_is_flagged` | strict xfail | XPASS(표시는 평가 측이 지운다) |
| T11 구조 확인(시행일이 서로 다른 연혁의 소급 적용 검출) | 통과 | 계속 통과 |
| T11 같은 시행일 두 버전: 결과가 갈리면 두 버전을 모두 싣고 확인 요청(UNVERIFIED, HIGH 아님, `human_review`) | strict xfail | XPASS |
| T11 같은 시행일 두 버전이 모두 맞으면 확인 요청으로 남기지 않음 | strict xfail | XPASS |
| T11 연혁 순서를 바꿔도 결과가 같음(한 버전을 골라 확정 금지) | strict xfail | XPASS |

- 입력 본문은 공식 원문 미러(`tests/fixtures/prepared_brief_mirror`)에서 가져왔다.
- T11의 같은 시행일 배열은 평가 측이 꾸민 것이다. 실제 사례(국가재정법 제96조)의 원문은 이 세션에서 확보하지 못했다. 설계 보충에 실제 사례를 확인할 방법이 있으면 적는다.

## 2. 지시 사전 점검 결과(평가 측, 8b70497)
- FT 모듈(`legal_history`·`temporal_review`)을 쓰는 기존 시험 16개 파일과 위 보호 시험: **669 통과, xfail 5**(T11 3·TK-34 1·기존 1).
- **충돌 1 — 범위를 이렇게 정한다:** `tests/test_legal_completion.py::test_ambiguous_identity_boundary_repeal_or_retroactivity`의 첫 경우는 **단일 조문 확인(`resolve_statute`)** 에서 같은 시행일 두 버전을 fail-closed(조회 실패)로 고정한다.
  - FT-b는 **행위시법 검토 경로(`official_versions` → `review_temporal_application`)에서만** 두 버전을 병기·대조한다.
  - `select_version`의 기존 동작과 `resolve_statute`의 fail-closed는 바꾸지 않는다. 이 시험은 그대로 통과해야 한다.
  - 다르게 하려면 설계 보충에 사유를 적고 평가 측 승인을 먼저 받는다.
- 미확인 사유 문구 대응(`packages/verification_engine/review_items.py`의 "Multiple versions share …")과 `tests/test_unverified_reasons.py`는 유지한다. FT-b 뒤에도 다른 경로에서 그 사유가 나올 수 있다.

## 3. 설계 보충에 담을 것(F1 지시서 1절 FT·TK-34 수용 기준)
1. **목 단위 본문 대조 방식(FT-a):**
   - 인용의 목 글자를 어디서 읽는지(지금 `Citation`에는 목 필드가 없고 `raw_text`에만 있다).
   - 버전마다 해당 목 본문을 어떻게 잘라 청구 문언과 대조하는지.
   - 목이 없거나 못 찾으면 어떻게 하는지(확정하지 않음).
2. **번호만 바뀐 개정과 내용이 바뀐 개정의 구분 근거:** 본문 대조로 하는지, 개정문을 쓰는지. 법령명·조문 번호·목 글자·날짜를 코드·설정에 넣지 않는 방법.
3. **동일 시행일 복수 버전(FT-b):** 2절의 범위 안에서 두 버전을 받는 방법, 각 버전의 대조, 결과가 갈릴 때 확인 요청으로 두는 방법. 순서·공포일·개정 번호로 하나를 고르지 않는다.
4. **판정 경로와 `rule_id`:**
   - 기준일 버전과는 다르고 현행과만 맞으면 기존 `TEMPORAL.CURRENT_ONLY_MATCH`로 충분한지 먼저 검토한다.
   - 새 `rule_id`나 `FindingType`이 필요하면 요청서로 승인을 받고, F2 배정표와 T3(배정 완전성)에 반영하는 계획을 적는다.
5. **오탐 대조군 계획:** T10 오탐 대조 4개 외에 추가할 대조(공식 원문으로 지은 것만).
6. **영향 범위:** 고정 시험·probe·회귀 게이트에서 점수가 내려가지 않는다는 근거와 확인 방법. FT는 점수가 오를 수는 있으나 내려가면 안 된다.

## 4. 금지
- 회신 전 FT 코드 작성.
- 보호 경로(`tests/acceptance/**`·`tests/fixtures/**`·`scripts/` 평가 도구·`docs/scorecards/**`) 수정.
- skip·xfail 표시 변경.
- 사건 고유 값(법령명·조문 번호·목 글자·날짜) 하드코딩.
- 작업 커밋에서 버전 변경.
