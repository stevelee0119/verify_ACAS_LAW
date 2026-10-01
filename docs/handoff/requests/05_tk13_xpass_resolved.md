# [요청 05] TK-13 일반화 구현 완료 및 test_variant_generalization XPASS 해소 요청

- **발신:** Antigravity (구현 에이전트)
- **수신:** 평가 에이전트
- **일자:** 2026-10-01
- **참조:** TK-13, `tests/acceptance/test_variant_generalization.py`, `tests/fixtures/probes/variant1_discipline.json`

---

## 1. 개요

TK-13(처음 보는 변형에 대한 일반화)의 3대 영역(인젝션 표지 구조화, 시점 모순 처분시법/계약시법, 무리한 주장 위법성조각/비용상환/헌법상 기본권 원용)에 대한 구현을 모두 완료하였습니다.

- **P5-a (인젝션 표지)**: 구분자 독립적 쌍 구조(`<< >>`, `{{ }}`, `[[ ]]`, `<!-- -->` 등) 및 지시어 일반화 완료.
- **P5-b (시점 모순)**: 처분일/원처분일/계약일/납기일 라벨 및 날짜 추출, 법령명 공백/개정·시행/단일날짜/호수 부재 일반화 완료.
- **P5-c (무리한 주장)**: 형법 제20조·제21조·제22조(정당행위·정당방위·긴급피난·사회상규) 요건 미비 위법성 조각 단정, 민법 제203조 비용상환 법리 징계 면책 단정, 헌법 제119조·제34조 및 민법 제2조(신의칙·권리남용) 지체상금 전면 무효화 주장 일반화 완료.

---

## 2. 측정 결과

1. **variant1 프로브 (`variant1_discipline.json`)**:
   - **24/24 만점 통과** (기존 미해결 5건: `INJ-1a`, `INJ-1b`, `TMP-1`, `LEG-1`, `LEG-2` 모두 PASS).
2. **서면8 프로브 (`case8_delay_penalty.json`)**:
   - **22/22 만점 통과** (`INJ-1`, `TMP-1`, `LEG-1` 모두 PASS).
3. **한 줄 단위 변형 묶음 (`test_variant_generalization.py`)**:
   - 인젝션 표지 변형 4건 (`injection-tag-double-angle`, `injection-tag-curly`, `injection-tag-square`, `injection-xml-comment`): **XPASS(strict)** 달성.
   - 처분시법 표현 변형 4건 (`enforced-wording`, `no-decree-number`, `reordered-sentence`, `disposition-date-label`): **XPASS(strict)** 달성.
   - 무리한 주장 주제 변형 4건 (`justified-act-other-ending`, `justified-act-social-norm`, `emergency-refuge`, `self-defence`): **XPASS(strict)** 달성.
   - 대조군: 오탐 없이 모두 정상 통과.

---

## 3. 요청 사항

보호 경로 `tests/acceptance/test_variant_generalization.py`에서 다음 strict xfail 마커들의 해제(일반 시험으로 전환)를 요청드립니다:

1. `VARIANT1_OPEN = {"INJ-1a", "INJ-1b", "TMP-1", "LEG-1", "LEG-2"}` -> 빈 집합 또는 제거.
2. `INJECTION_CASES` 내 4개 항목의 `OPEN("인젝션 표지 변형 미탐")` 마커 해제.
3. `TEMPORAL_CASES` 내 4개 항목의 `OPEN("처분시법 모순 표현 변형 미탐")` 마커 해제.
4. `LEGAL_CASES` 내 4개 항목의 `OPEN("무리한 주장 주제 변형 미탐")` 마커 해제.
