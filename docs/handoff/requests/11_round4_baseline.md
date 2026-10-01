# 4차 라운드 기준선 및 시작 점검 보고서 (Round 4 Baseline)

- 작성: 구현 에이전트 (Antigravity) 2026-10-01
- 대상: 평가 에이전트 (claude-code)
- 기준 커밋: `a2604d0` (Steve_ACASiaLAW, 4차 지시서 반영 시점)
- 실행 환경: Windows 11, Python 3.14.6, 오프라인 모드, OCR 엔진 없음 (Tesseract 미설치), `core.autocrlf=input`, `PYTHONUTF8=1`

---

## 1. 4절 검증 명령 실행 결과 (시작 기준선)

### 1) 회귀 게이트 (`python scripts/regression_gate.py --base HEAD~1`)
```
회귀 게이트 — 기준 a64caf3 → 현재 a2604d0 (오프라인)
  case6_military_secret/primary                   20/20 → 20/20  
  case6_military_secret/text                      20/20 → 20/20  
  case7_suspension/primary                        25/25 → 25/25  
  case7_suspension/text                           25/25 → 25/25  
  case8_delay_penalty/primary                     22/22 → 22/22  
  case8_delay_penalty/text                        22/22 → 22/22  
  case9_state_compensation/primary                27/28 → 27/28  
  case9_state_compensation/text                   27/28 → 27/28  
  variant1_discipline/primary                     24/24 → 24/24  
  variant1_discipline/text                        24/24 → 24/24  
  variant2_food_license/primary                   21/21 → 21/21  
  variant2_food_license/text                      21/21 → 21/21  
회귀 없음
```

### 2) 하드코딩 변경분 점검 (`python scripts/check_hardcoding_diff.py --base HEAD~1`)
```
하드코딩 변경분 점검 — 기준 HEAD~1, 추가된 줄 0개
  새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
```

### 3) 사건 값 하드코딩 점검 (`python scripts/check_case_literals.py`)
```
사건별 시험에서 뽑은 사건 값 52개, 제품 코드에서 발견 5건
  [부채] config/legal_defense_groups.json: 어떠한제재도허용될수없다
  [부채] config/legal_rules/rules.json: 2020도16420, 공제는법률상근거가없, 국가를당사자로하는계약에관한법률, 대금공제는허용되지않
새 위반: 0건
```
> ※ `config/legal_defense_groups.json`의 부채 항목은 S1(TK-26) 단계에서 범주 구조로 전환하여 해소 예정.

### 4) 성적표 및 점수 게이트 (`python scripts/scorecard.py && python scripts/score_gate.py`)
```
성적표 — 0.9.13 (rule 2026.09.30.1) · a2604d0
조건: 오프라인, OCR 없음, python 3.14.6

세트             종합     재현율    오탐   A등급     인젝션
dev          81.7   0.817     0     0      방어
holdout      79.2   0.792     0     0      방어

향상: [dev] 종합 79.9 → 81.7
향상: [holdout] 종합 77.3 → 79.2
점수 게이트 통과
```

### 5) 수용 시험 점검 (`python -m pytest tests/acceptance -q -rxX`)
총 16건 xfail 확인 (지시서 명세와 일치):
- `tests/acceptance/test_case9_state_compensation.py::test_case9_check[docx-LEG-2]` (TK-24, 대상 외)
- `tests/acceptance/test_case9_state_compensation.py::test_case9_check[text-LEG-2]` (TK-24, 대상 외)
- `tests/acceptance/test_case9_state_compensation.py::test_injection_stamp_survives_line_wrapping[w36]` (TK-22)
- `tests/acceptance/test_case9_state_compensation.py::test_injection_stamp_survives_line_wrapping[w40]` (TK-22)
- `tests/acceptance/test_case9_state_compensation.py::test_regulation_claim_is_not_split_by_line_wrapping[w36]` (TK-22)
- `tests/acceptance/test_case9_state_compensation.py::test_regulation_claim_is_not_split_by_line_wrapping[w44]` (TK-22)
- `tests/acceptance/test_generalization_guards.py::test_config_file_is_read_by_code[config/legal_defense_groups.json]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[freedom-of-expression]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[freedom-of-residence]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[equality-principle]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[reliance-protection]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[unjust-enrichment]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[victim-consent]` (TK-26)
- `tests/acceptance/test_unseen_doctrine_overclaim[occupational-freedom]` (TK-26)
- `tests/acceptance/test_generalization_guards.py::test_reference_date_is_not_picked_arbitrarily_among_candidates[contract-two-dates]` (TK-27)
- `tests/acceptance/test_generalization_guards.py::test_reference_date_is_not_picked_arbitrarily_among_candidates[disposition-two-dates]` (TK-27)

### 6) 프로브 점검 (`python scripts/probe_document.py run --spec tests/fixtures/probes/<spec>.json [--text]`)
- `case6_military_secret`: primary 20/20, text 20/20 만점
- `case7_suspension`: primary 25/25, text 25/25 만점
- `case8_delay_penalty`: primary 22/22, text 22/22 만점
- `case9_state_compensation`: primary 27/28, text 27/28 (LEG-2 미탐 외 전건 통과)
- `variant1_discipline`: primary 24/24, text 24/24 만점
- `variant2_food_license`: primary 21/21, text 21/21 만점

---

## 2. 향후 작업 진행 계획
- **S0**: 회귀 원장(`tests/regression/test_ledger.py`) 신규 구축 (TK-01~TK-27 양성+대조군).
- **S1**: 하드코딩 정리 — TK-26 (법리 군집 설정 읽기 단일 원천화, 정규식 낱말 12개 제거, 체계로 닫힌 집합 구성, 리터럴 부채 감소).
- **S2**: 입력 계층 문단 복원 — TK-22 (파서 단계 문단 복원, 배치 불변 달성, 소비자별 언래핑 제거).
- **S3**: 내부 규정 비존재 법령 오탐 해소 — TK-23 A.
- **S4**: 기준일 임의 선택 해소 — TK-27.
- **S5**: 표시·모델 응답 안정화 — TK-25 제안 작성.
- **S6**: 외부 지적 재현 확인.
- **S7**: 코드 정리 및 최종 검증.
