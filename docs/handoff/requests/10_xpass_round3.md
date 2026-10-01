# 3차 작업(Round 3) XPASS 해소 요청서

- 작성: 구현 에이전트 (Antigravity) 2026-10-01
- 대상: 평가 에이전트 (claude-code)
- 관련 지시서: `PROMPT_FOR_ANTIGRAVITY_ROUND3.md` (Q1 ~ Q8)

---

## 1. 개요

3차 작업(Q1~Q8)을 통해 구현된 일반화 로직으로 인하여, `tests/acceptance/` 내 `strict=True`로 설정된 xfail 시험 9건이 모두 정상 통과(XPASS)되었습니다. 해당 시험들의 xfail 표시 해소를 요청합니다.

## 2. XPASS 시험 목록 (총 9건)

### 1) 기준일 후보 소실 회귀 해결 (Q1 관련, TK-19)
- `tests/acceptance/test_variant_generalization.py::test_reference_date_candidate_is_kept[embezzle-verb]`
- `tests/acceptance/test_variant_generalization.py::test_reference_date_candidate_is_kept[unlawful-method]`
- `tests/acceptance/test_variant_generalization.py::test_two_offense_dates_are_never_verified`
  - 내용: 날짜 뒤 일반 명사/동사('횡령', '방법') 끝음절을 법령명으로 오인하던 정규식 가지를 제거하고 법령 구조 신호 조합으로 개선하여 두 개 이상의 행위일이 존재할 때 단일 기준일로 오판하여 VERIFIED되는 회귀를 방지하고 기준일 후보 보존 정상화.

### 2) 서면8 텍스트 입력 무리한 주장 해결 (Q7 관련, TK-20 4절)
- `tests/acceptance/test_case8_delay_penalty.py::test_case8_check[text-LEG-1]`
  - 내용: 텍스트 입력 시 하드 래핑 줄바꿈으로 인한 문장 분절을 길이 보존(1:1 치환) 언래핑으로 결합하여 헌법상 기본권/민법 일반원칙 기반 무리한 주장 탐지 정상화 (서면8 text 22/22 만점 달성).

### 3) 미공개 변형 서면 2 항목 일반화 해결 (Q5, Q6, Q7 관련, TK-20)
- `tests/acceptance/test_variant_generalization.py::test_variant2_check[PII-4]`
  - 내용: 당사자 주소의 영문 동 표기('A동 1203호') 및 구조적 주소 꼬리 매칭 지원.
- `tests/acceptance/test_variant_generalization.py::test_variant2_check[PII-10]`
  - 내용: 소송대리인 및 법원 주소 판별 시 블록 경계를 넘는 문맥 고려(다중 라인 문맥 대응).
- `tests/acceptance/test_variant_generalization.py::test_variant2_check[PII-12]`
  - 내용: 소송대리인 법인명과 같은 줄에 위치한 담당변호사 직책·성명 마스킹 지원.
- `tests/acceptance/test_variant_generalization.py::test_variant2_check[INJ-1a]`
  - 내용: `@@ ... @@` 등 연속/대칭 기호 구분자 및 의도 군집 신호 합산 기반 인젝션 탐지.
- `tests/acceptance/test_variant_generalization.py::test_variant2_check[LEG-1]`
  - 내용: 헌법 제23조 재산권 및 사정변경 원칙에 기초한 단정적 당연무효 주장을 3대 법리 군집(GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS) 4단 구조로 탐지 (변형2 21/21 만점 달성).

## 3. 요청 사항
- 위 9건의 시험에 대해 `strict=True` xfail 마커를 해제해 주시기 바랍니다.
