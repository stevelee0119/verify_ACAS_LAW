# TK-22 입력 계층 문단 복원, 배치 불변성 회귀 해소 및 XPASS 요청서

- 작성: 구현 에이전트 (Antigravity) 2026-10-01
- 대상: 평가 에이전트 (claude-code)
- 관련 티켓: `TK-22` (입력 단계: 물리적 줄을 문단으로 복원하지 않아 주장·표지가 토막 난다)
- 커밋 예정 묶음: S2

---

## 1. 개요 및 구현 내역
1. **입력 계층 문단 복원 일원화 (`packages/document_engine/paragraph_reconstruction.py`)**:
   - `TextParser` 등 입력 계층에서 물리적 줄(`lines`)과 속성을 `attributes["lines"]`에 보존하면서 소비자가 쓰는 `text`를 구조 신호 기반으로 문단 단위로 복원하도록 구현했습니다.
   - 문단 결합 시 한글 낱말 사이의 공백 1개를 보존하고, 어절 중간 줄바꿈(조사·어미로 시작)은 공백 없이 결합하도록 처리했습니다.
2. **줄 단위 의미 영역 보존**:
   - 당사자 표시란(원고, 피고, 피고인 등), 사건 표제부, 소송대리인, 법원 제출처, 단독 목차 제목, 빈 줄 등 줄 단위가 의미를 갖는 영역은 단독 블록(줄 단위)으로 엄격하게 보존했습니다.
   - `packages/pii_engine/detector.py`의 `is_lawyer_court_address_context`에서 문단 내 당사자 본인 주소 판정을 보강하여 당사자 주소 마스킹이 정상 유지되도록 개선했습니다.
3. **짝 괄호 및 인젝션 표지 분절 해소**:
   - `[`, `<<`, `{{`, `<!--`, `/*`, `@@`, `##` 등 구조적 구분자가 줄바꿈으로 나뉜 경우 닫힘 기호가 나올 때까지 단일 블록으로 안전하게 결합 복원하여, 임의의 줄 폭(wrap36, wrap40 등)에서도 구조적 인젝션 탐지가 유지되도록 조치했습니다.
4. **회귀 원장 및 검증 게이트 유지**:
   - `tests/regression/test_ledger.py`에 TK-22 양성 3건, 대조군 3건 추가 (총 40건 전건 통과).
   - dev 81.7 / holdout 79.2 (오탐 0건, 인젝션 방어, 점수 게이트 통과).
   - 기존 서면6~8, 9, 변형 1·2 전건 12/12 프로브 만점 유지 (회귀 없음).

---

## 2. XPASS 해소 시험 목록 (총 4건)
다음 4건의 시험이 `strict=True` xfail에서 통과(XPASS)되었습니다 (`tests/acceptance/test_case9_state_compensation.py`):
1. `test_injection_stamp_survives_line_wrapping[w36]`
2. `test_injection_stamp_survives_line_wrapping[w40]`
3. `test_regulation_claim_is_not_split_by_line_wrapping[w36]`
4. `test_regulation_claim_is_not_split_by_line_wrapping[w44]`

대조군 `w56` 2건도 계속 통과하고 있습니다.
해당 시험들의 xfail 표시 해소를 요청합니다.

---

## 3. `test_layout_invariance.py` KNOWN_OPEN 전건(11건) 해소
`tests/acceptance/test_layout_invariance.py`의 알려진 미해결(`KNOWN_OPEN`) 11건이 문단 복원에 의해 모두 풀렸습니다:
1. `("case6_military_secret", "wrap40"): {"INJ-1"}` 풀림
2. `("case6_military_secret", "wrap48"): {"INJ-1"}` 풀림
3. `("case7_suspension", "wrap40"): {"CIT-6"}` 풀림
4. `("case8_delay_penalty", "wrap40"): {"INJ-1"}` 풀림
5. `("case8_delay_penalty", "wrap48"): {"INJ-1"}` 풀림
6. `("case9_state_compensation", "wrap40"): {"INJ-1"}` 풀림
7. `("case9_state_compensation", "wrap48"): {"INJ-1"}` 풀림
8. `("variant1_discipline", "wrap40"): {"INJ-1b"}` 풀림
9. `("variant1_discipline", "wrap48"): {"INJ-1b"}` 풀림
10. `("variant2_food_license", "wrap40"): {"INJ-1a"}` 풀림
11. `("variant2_food_license", "wrap64"): {"INJ-1b"}` 풀림

새로운 회귀(`missing - known`)는 0건입니다.
평가 에이전트 소관 보호 경로이므로 `test_layout_invariance.py`의 `KNOWN_OPEN` 갱신을 요청합니다.
