# TK-27 기준일 후보가 여럿이면 임의로 하나를 고른다(계약은 늦은 날짜, 처분은 이른 날짜)
- 유형: 불확실성 보존 위반(설계) · 기준 커밋: main 9933548 · 작성: evaluator 2026-10-01
- 출처: 외부 평가 의견(Astra, 2026-10-01)이 `document_reference_date`의 계약일 최대값 선택을 지적했고, 평가 측이 재현·확인했다.

## 증상(평가 측 재현, 오프라인)
```
계약  `…2023. 5. 30. 공급계약을 체결하였고, 납기는 2023. 12. 31.로 정하였다.`  → 기준일 2023-12-31, basis DOCUMENT_INFERRED (후보 2개: 05-30, 12-31)
처분  `…2024. 5. 3. 1차 처분을 하였고, 2024. 7. 1. 재처분을 하였다.`            → 기준일 2024-05-03, basis DOCUMENT_INFERRED (후보 2개)
행위  `피고인은 2021. 6. 1. 횡령하였다. 피고인은 2022. 2. 3. 다시 횡령하였다.`   → 기준일 None, basis AMBIGUOUS (후보 2개 보존)  ← 올바른 동작
```
`temporal_review.document_reference_date`가 계약(`CONTRACT`)이면 `max(dates)`, 처분(`DISPOSITION`)이면 `min(dates)`를 `DOCUMENT_INFERRED`로 고른다(6e5cd78). 행위일에는 쓰지 않는 이 추정을 다른 두 종류에만 쓴다. 후보 날짜 사이에 개정·시행일이 끼는 서면에서는 어느 기준일을 고르느냐에 따라 같은 개정이 '행위 전'도 '행위 후'도 된다. 불확실을 확정처럼 보이게 하는 3차 Q1과 같은 종류의 오류다.

## 요구
1. 후보가 둘 이상이면 하나로 추정하지 않는다. 후보를 모두 보존하고(`candidates`), 개정·시행일과 **각 후보를 따로 비교**한다. 2차 지시서 P5-b의 설계 그대로다: 개정·시행일이 **모든** 기준일 후보보다 뒤면 근거 강함(SUSPICIOUS 이상), **일부** 후보보다만 뒤면 사람 확인(UNVERIFIED·후보 병기).
2. 서면8 TMP-1(계약 체결 2023. 5. 30.·납기 2023. 12. 31. 뒤 2025. 1. 1. 개정 시행규칙 소급 적용 주장)은 개정일이 모든 후보 뒤이므로 **계속 통과**해야 한다. `regression_gate.py`로 확인한다.
3. 단일 후보면 지금처럼 추정 기준일을 쓴다.

## 수용 기준
- `python -m pytest tests/acceptance/test_generalization_guards.py -rxX`: `test_reference_date_is_not_picked_arbitrarily_among_candidates[contract-two-dates·disposition-two-dates]` XPASS(대조군 `offense-two-dates` 계속 통과).
- 서면8 오프라인 22/22(PDF·텍스트), `python scripts/regression_gate.py --base <직전 커밋>` 회귀 없음.
- 구현 측 새 시험: 개정일이 후보 사이에 끼는 입력, 모든 후보보다 뒤인 입력, 단일 후보 입력(양성·대조군).
