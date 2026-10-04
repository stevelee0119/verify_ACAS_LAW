# 7차 안정화 라운드(안정화 4) 시작 기준선 측정 보고서 (R0)

- 작성: 구현 담당 에이전트 (Antigravity)
- 작성일시: 2026-10-03
- 용도: 7차 작업 지시서(docs/handoff/PROMPT_FOR_STABILIZATION_ROUND7.md)에 따른 R0 시작 상태 고정 및 기준선 기록

---

## 1. 시작 상태 고정

### 1.1 기준 브랜치 및 시작 SHA
- **시작 브랜치**: `Steve_ACASiaLAW` (6차 구현 병합 + 평가 측 시험·도구 포함)
- **시작 SHA**: `7adf43f` (이후 커밋은 docs 전용 커밋이며 시작 상태 영향 없음, 현재 HEAD `415caae`)
- **6차 구현 커밋**: `01070f6` (Steve_ACASiaLAW에 병합 커밋 `a8ead24`로 병합 완료)

### 1.2 작업 환경 및 경로 정보
```text
작업 경로: C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/super_cosmos_surges_19h47
현재 HEAD: 415caae (Steve_ACASiaLAW fast-forward 병합)
현재 브랜치: super_cosmos_surges_19h47
작업 트리 상태: clean (미커밋 변경 없음)
core.autocrlf: input
```

### 1.3 최근 커밋 히스토리 (`git log -6 --oneline`)
```text
415caae docs(handoff): Docker OCR readiness 연속 초록 3회 기준 충족 기록, 필수 확인 추가를 사용자에게 요청
75ee4a0 docs(handoff): 7차 시작 상태를 CI 실측으로 정정 — 점수 게이트 성공, CI는 R6-04 1건만 실패
0a40289 docs(handoff): 7차 시작 상태 확정(시작 SHA 7adf43f) — 병합·승격 완료, F1 기준값 확정, CodeQL 로컬 입력 포함 확인, 오탐 65건 번호 목록
7adf43f test(eval): 6차 병합 뒤 평가 측 시험 적용 — 22 XPASS 승격과 6차 회귀 보호 시험(strict xfail 40) 고정
a8ead24 Merge remote-tracking branch 'origin/super_cosmos_surges_19h47' into Steve_ACASiaLAW (6차 구현 01070f6 병합)
01070f6 docs(handoff): 6차 안정화 작업 보완 지시서 반영 결과 보고서 작성 (R4)
```

### 1.4 실행 환경 명세
- **OS**: Windows 11 (PowerShell 환경, UTF-8)
- **Python**: 3.14.6
- **OCR 상태**: 로컬 Tesseract 미설치 (OCR 없음, Docker OCR readiness는 CI에서 초록 3회 확인됨)
- **네트워크 모드**: 오프라인 (`LV_ALLOW_NETWORK=0`)
- **버전 상태**: `0.9.13` (변경 없음, 불변)

---

## 2. 6대 검증 게이트 및 기준선 실측 결과

1. **사건 고유 리터럴 점검 (`scripts/check_case_literals.py`)**:
   - 결과: 부채 4건 유지 (신규 위반 0건 통과)
   - 부채 목록: `config/legal_rules/rules.json` (2020도16420, 공제는법률상근거가없, 국가를당사자로하는계약에관한법률, 대금공제는허용되지않)

2. **성적표 및 점수 게이트 (`scripts/scorecard.py && scripts/score_gate.py`)**:
   - 성적표 버전: 0.9.13 (rule 2026.09.30.1) · 415caae
   - dev: 종합 81.7 / 재현율 0.817 / 오탐 0건 / A등급 0건 / 인젝션 방어 성공
   - holdout: 종합 79.2 / 재현율 0.792 / 오탐 0건 / A등급 0건 / 인젝션 방어 성공
   - 점수 게이트 통과 (성공)

3. **버전 정책 점검 (`scripts/check_version_policy.py`)**:
   - 결과: 위반 없음 (0.9.13 불변 유지)

4. **기존 시험 실패 실측 (CI 및 로컬 일치 확인)**:
   - `test_legal_military_terms_not_masked_as_person` (R6-04): FAIL 확인 (`부대는`이 PERSON으로 오탐)
   - 전체 시험(`--ignore=tests/acceptance`): R6-04 1건 실패 외 다른 실패 없음 확인 (CI run 37093734438과 동일)

5. **수용 보호 시험 현황 (`tests/acceptance`)**:
   - 6차 회귀 보호 시험 (`tests/acceptance/test_round6_regressions.py`): strict xfail 40건 고정
   - 보안 보강 보호 시험 (`tests/acceptance/test_security_round.py`): strict xfail 11건 고정 (합계 strict xfail 51건)
   - 5차 22 XPASS 승격 시험 43건 일반 통과 유지

6. **정규식 복잡도 점검 (`scripts/probe_regex_complexity.py`)**:
   - 지수 증가 의심 2건 확인 (TK-38 A `pdf_parser.py:SINGLE_GLYPH_SHOW_RE`, TK-38 B `korean_amount.py:65`)

---

## 3. 7차 라운드 작업 순서 및 이행 방침

7차 작업 지시서 1절 순서에 따라 단계별로 진행합니다:
- **R1 (TK-39)**: 명시적 성명 라벨 후보 보호, 암묵 후보에만 문맥 제외 적용, 부대 등 명사 경계 판별. R6-04 및 R6-01(마스킹 18 + 라우터 12) 해결, 실제 `LLMRouter.run` 가짜 공급자 시험 포함. (CI 초록 달성)
- **R2 (TK-40)**: 법리 경고 면제의 구조화 (요건 긍정 소명, 발화 주체, 책임 범위 판정). R6-02 해결.
- **R3 (TK-41)**: 줄 결합 구조화 (1음절 독립어 공백 보존, 레이아웃 신호 국소화). R6-03 해결.
- **R4 (보안 S1~S5)**: ReDoS 지수 증가 해소, 경로 비교 `is_relative_to`, 503 응답 은닉, JS prototype 오염 방어. 보안 보호 11건 해결.
- **R5 (시험 및 정정)**: 3종 세트 고정, `config/legal_defense_groups.json` 편제명 source_url/verified_at 기록, 6차 보고서 오기 정정.
- **R6 (F1 설계 준비)**: `docs/handoff/requests/22_f1_design_prep.md` 작성.
