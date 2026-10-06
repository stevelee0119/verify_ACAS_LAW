# TK-62 FT 목 단위 경로가 판본 간 대비 없이 '불일치'를 만든다 — 새 A등급 오탐 (P1, 탐지)
- 유형: 탐지 결함(P1). FT 구현 PR #27(ca0067b)이 새로 만든 것이다. 아직 병합되지 않았다.
- 발견: 평가 측 FT 구현 판정(2026-10-06). 코드 대조와 재현으로 확인했다.
- 작성: evaluator 2026-10-06

## 1. 원인
- `packages/legal_engine/temporal_review.py`의 `version_outcomes`가 문제다.
  - 인용이 '제N호 X목'이고 해당 호를 목 단위로 분할한 경우, 주장이 어느 목과도 VERIFIED가 아니면 그 판본을 **무조건 `CONTRADICTED`(basis `SUBITEM_NOT_EXIST`)** 로 둔다.
  - 이 처리는 판본마다 따로 적용된다. 다른 판본에 목 단위 일치가 있든 없든 상관없다.
  - 비교기가 `UNVERIFIED`(판단 보류)를 낸 경우도 불일치로 바뀐다.
- 그래서 주장이 호 머리글에 있고 목 본문에는 없는 인용은 모든 판본이 CONTRADICTED가 된다. 결과는 `TEMPORAL.NO_VERSION_MATCH`(CONTRADICTED·HIGH·A등급)다.
- 승인 설계(`requests/42_ft_design.md` 개정 1, 1.2)는 '목 부존재'를 신설 목의 소급 인용을 가리는 근거로만 쓴다. 판본 사이의 대비가 없는데 불일치를 만드는 것은 설계 밖이다.

## 2. 재현(평가 측, 합성 조문)
- 입력
  - 조문 한 개: ① 아래 제1호 머리글 "다음 각 목의 어느 하나에 해당하는 경우 손해액의 3배 이내", 가목·나목에는 수치 없음.
  - 두 판본(2019-01-01~2022-12-31, 2023-01-01~)의 본문은 같다.
  - 인용 '제5조 제1항 제1호 가목', 주장 '손해액의 3배 이내에서 배상', 기준일 2021-06-01.

| 커밋 | 판본 결과 | finding |
|---|---|---|
| c206386(FT 전) | VERIFIED, VERIFIED | `REFERENCE_VERSION_MATCH` VERIFIED·INFO·B |
| ca0067b(PR #27) | CONTRADICTED, CONTRADICTED | **`NO_VERSION_MATCH` CONTRADICTED·HIGH·A** |

- 공식 원문 미러(`tests/fixtures/prepared_brief_mirror`)에는 '호 머리글에 수치, 목에는 없음' 구조의 조문이 없다. 그래서 미러 입력으로는 재현하지 못했다. 위는 코드 경로를 보이는 합성 입력이다.

## 3. 요구
1. 판본마다 목 단위 결과를 먼저 모은다: 일치한 목, 또는 '부존재'(분할 성공, 일치 목 없음).
2. **어느 판본에서든 목 단위 VERIFIED가 하나 이상 있을 때만** '부존재' 판본을 CONTRADICTED(SUBITEM_NOT_EXIST)로 둔다.
3. 2에 해당하지 않으면 모든 판본을 FT 전과 같은 조·항 단위 비교 결과로 둔다.
4. 시험: 2절 구조(합성, 시험 설명에 합성임을 적음)에서 finding이 FT 전과 같음을 단언한다.

## 4. 지시 사전 점검(평가 측, ca0067b + 임시 패치, 커밋 안 함)
- 3절 1~3을 임시로 넣었다.
- 결과
  - 2절 재현: `REFERENCE_VERSION_MATCH`로 돌아왔다.
  - 보호 시험 T10 양성·T11 3개: 계속 통과(strict XPASS 4).
  - 관련 시험 7개 파일(`test_ft_protected`·`test_prepared_brief_mirror_official`·`test_ft_temporal_review`·`test_v4_p3_temporal`·`test_v4_review_temporal`·`test_legal_completion`·`test_unverified_reasons`): 134 passed, 실패는 strict XPASS 4뿐이다.

## 5. 수용
- 위 시험이 추가되고 통과한다.
- CI 실패가 strict XPASS 4건뿐이다.
- 평가 측이 2절을 다시 재현해 FT 전과 같음을 확인한다.
- 수용 SHA에서 평가 측이 `verify_all` 전체 모드를 돌린다.
