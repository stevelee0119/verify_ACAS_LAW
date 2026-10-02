# 5차 안정화 라운드(안정화 2) 시작 기준선 측정 보고서 (U0)

- 유형: 라운드 시작 기준선 점검
- 기준 커밋: `838d964` (`Steve_ACASiaLAW` 최신, e4378f7 이후 사용자 결정 및 보호 시험 반영본)
- 측정 일시: 2026-10-02
- 환경: Windows (powershell, `$env:PYTHONUTF8 = '1'`), python 3.14.6, OCR 없음, 오프라인 (`LV_ALLOW_NETWORK=0`)
- 작성: 구현 담당 에이전트 (Antigravity)

---

## 1. 6대 검증 게이트 및 버전 정책 측정 결과

1. **사건 고유 리터럴 점검 (`scripts/check_case_literals.py`)**:
   - 결과: 부채 4건 유지 (신규 위반 0건)
   - 잔여 부채: `config/legal_rules/rules.json` (2020도16420 등 4건 유지)
2. **하드코딩 변경분 점검 (`scripts/check_hardcoding_diff.py --base HEAD`)**:
   - 결과: 추가된 줄 0개, 강한 신호 0건 통과
3. **회귀 게이트 (`scripts/regression_gate.py --base HEAD`)**:
   - 결과: 12/12 유지 (회귀 없음)
   - 서면별 검증 결과:
     - `case6_military_secret`: primary 20/20, text 20/20
     - `case7_suspension`: primary 25/25, text 25/25
     - `case8_delay_penalty`: primary 22/22, text 22/22
     - `case9_state_compensation`: primary 27/28, text 27/28
     - `variant1_discipline`: primary 24/24, text 24/24
     - `variant2_food_license`: primary 21/21, text 21/21
4. **성적표 및 점수 게이트 (`scripts/scorecard.py && scripts/score_gate.py`)**:
   - 성적표 버전: 0.9.13 (rule 2026.09.30.1)
   - dev: 종합 81.7 / 재현율 0.817 / 오탐 0건 / 인젝션 방어 성공
   - holdout: 종합 79.2 / 재현율 0.792 / 오탐 0건 / 인젝션 방어 성공
   - 점수 게이트 통과 (기준선 79.9 / 77.3 초과 유지)
5. **회귀 원장 (`python -m pytest -q tests/regression`)**:
   - 결과: 70 passed in 12.32s (100% 통과)
6. **버전 정책 점검 (`scripts/check_version_policy.py --base HEAD`)**:
   - 결과: 위반 없음 (버전: 0.9.13 변경 없음, 판정 대기)

---

## 2. 보호 시험(`tests/acceptance`) 현황

총 27건 xfail (strict) + 10건 KNOWN_OPEN 확인:
- **서면9 LEG-2**: 3건 (`docx-LEG-2`, `text-LEG-2`, `real_pdf-LEG-2`) — TK-24 관련
- **서면9 실제 PDF 원본**: 3건 (`regulation_sentence_is_one_claim`, `citation_law_name_matches_docx`, `claim_count_close_to_docx`) — TK-22 U4 해결 대상
- **민법 법리 과대주장 일반화**: 5건 (`setoff`, `performance`, `release`, `rescission`, `apparent-agency`) — TK-26 U5 해결 대상
- **당사자 이름 라벨 구분자**: 13건 (`colon`, `colon-spaced`, `hyphen`, `fullwidth-colon`, `fullwidth-slash`, `bracket-label`, `paren-name`, `claimant`, `applicant`, `creditor`, `witness`, `victim`, `spaced-name-colon`) — TK-28 U2 해결 대상
- **참고자료 일치 가드**: 3건 (`unread_file_with_same_title...`, `fabricated_statute_name...`, `short_statute_name...`) — TK-29 U1 해결 대상
- **PDF 배치 불변성**: 10건 `KNOWN_OPEN` (`test_layout_invariance_pdf.py`) — TK-22 U4 해결 대상

---

## 3. 5차 라운드 이행 순서

지시서에 따라 아래 순서로 단일 묶음씩 구현 및 커밋을 진행합니다:
1. **U1 (TK-29)**: 참고자료(Drive) 일치 판정 개선 (본문 읽은 참고자료 한정, 정규화 제목 일치, 법령 인용 CRITICAL 미인하)
2. **U2 (TK-28)**: 당사자 이름 라벨 구분자 일반화 및 이름 후보 구조 판정
3. **U3 (TK-28)**: 전송 전 검사(`inspect_request`)의 system/schema 등록 상수 출처 확인 방식 전환
4. **U4 (TK-22)**: PDF·docx 입력 계층 문단 복원 통합 및 소비자별 줄 결합 땜질 제거
5. **U5 (TK-26)**: 민법 군집 편·장·절 체계적 범위 정의
6. **U6 (TK-28)**: 시점 군 사전 병원 경과 닫힌 체계 보완
7. **U7**: 절차 점검 및 정리
8. **U8**: `main` 브랜치 보호 규칙 지정 (저장소 설정)
9. **U9**: 소규모 변경 2건 (U9-1: TK-23 B 조문 부존재 심각도 HIGH, U9-2: 생성 소프트웨어명 분리 INFO)
