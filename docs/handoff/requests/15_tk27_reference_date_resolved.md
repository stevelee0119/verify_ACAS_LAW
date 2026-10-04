# [해소] TK-27 기준일 후보 임의 선택 해소 및 불확실성 보존

- **작성 일시**: 2026-10-01
- **작성자**: 구현 에이전트 (Antigravity)
- **대상**: 평가 에이전트 / 사용자
- **관련 티켓**: `docs/handoff/TK-27_reference_date_arbitrary_pick.md`

---

## 1. 해결 내용

### (1) 기준일 후보 임의 선택 제거 및 불확실성 보존
- `packages/legal_engine/temporal_review.py::document_reference_date`:
  - 계약(`CONTRACT`) 시 `max(dates)`를 골라 `DOCUMENT_INFERRED`로 만들던 임의 추정을 제거했습니다.
  - 처분(`DISPOSITION`) 시 `min(dates)`를 골라 `DOCUMENT_INFERRED`로 만들던 임의 추정을 제거했습니다.
  - 후보 날짜가 1개일 때만 `DOCUMENT_INFERRED` 단일 기준일로 채택하고, 2개 이상일 때는 `basis = "AMBIGUOUS"`로 모든 후보 날짜(`candidates`, `dates`)를 그대로 보존합니다.

### (2) 개정·시행일과 복수 후보 날짜 분기 대조
- `packages/legal_engine/temporal_review.py::review_declared_amendments`:
  - 개정·시행일이 **모든(all)** 기준일 후보보다 뒤인 경우:
    - 사후 개정 소급 적용 주장이 확실하므로 `SUSPICIOUS` (HIGH)로 판정합니다.
    - 서면8 TMP-1(계약일 2023. 5. 30., 납기 2023. 12. 31. 뒤인 2025. 1. 1. 개정 소급 적용 주장)이 22/22 만점으로 정상 통과합니다.
  - 개정·시행일이 **일부(any)** 기준일 후보보다만 뒤인 경우 (후보 날짜 사이에 개정일이 낀 경우):
    - 단정하지 않고 `UNVERIFIED` (MEDIUM) 및 "기준일 특정 확인 필요(사람 확인)"로 보고합니다.
  - 개정·시행일이 모든 후보보다 앞서거나 같은 경우:
    - 소급 적용 주장이 아니므로 판정하지 않습니다.

---

## 2. 검증 결과

1. **`tests/acceptance/test_generalization_guards.py`**:
   - `test_reference_date_is_not_picked_arbitrarily_among_candidates[contract-two-dates]`: `XPASS` (strict xfail 해소)
   - `test_reference_date_is_not_picked_arbitrarily_among_candidates[disposition-two-dates]`: `XPASS` (strict xfail 해소)
   - `[offense-two-dates]`: 계속 통과 (대조군 보존)
2. **서면8 (`case8_delay_penalty`)**:
   - PDF 입력: 22/22 (TMP-1 정상 통과)
   - 텍스트 입력: 22/22 (TMP-1 정상 통과)
3. **회귀 게이트 (`regression_gate.py`)**: 12/12 유지 (회귀 0건)
4. **회귀 원장 (`tests/regression/test_ledger.py`)**: 58/58 통과 (TK-27 양성 6건, 대조군 3건 추가)
5. **성적표 (`scorecard.py && score_gate.py`)**: dev 81.7 / holdout 79.2 통과

평가 에이전트는 `test_generalization_guards.py`의 해당 2건에 대한 `xfail` 마크 제거를 검토해 주시기 바랍니다.
