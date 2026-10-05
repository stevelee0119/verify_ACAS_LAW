# 기능 라운드 F1 시작 기준선 측정 보고서 (F0)

- **작성**: 구현 담당 에이전트 (Antigravity)
- **작성일시**: 2026-10-04
- **용도**: 기능 라운드 F1 작업 지시서(docs/handoff/PROMPT_FOR_FEATURE_ROUND_F1.md)에 따른 시작 상태 고정 및 기준선 기록
- **시작 브랜치**: `Steve_ACASiaLAW`
- **시작 SHA**: `a04826f6959dee0e1fed9d402d61cbfbdbdf5457` (`Merge PR #9: 평가 측 사용자 결정(1~5) 반영 — 역할 개정·verify_all·8C 지시서(Codex)`)
- **작업 브랜치**: `antigravity/f1-review-screen`

---

## 1. 시작 상태 고정

### 1.1 작업 환경 및 경로 정보
```text
작업 경로: C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/super_cosmos_surges_19h47
현재 HEAD: a04826f6959dee0e1fed9d402d61cbfbdbdf5457
현재 브랜치: antigravity/f1-review-screen (upstream/Steve_ACASiaLAW 추적)
작업 트리 상태: clean (미커밋 변경 없음)
네트워크 모드: 오프라인 (LV_ALLOW_NETWORK=0)
인코딩 환경: PYTHONUTF8=1
버전 상태: 0.9.13 (불변)
```

### 1.2 최근 커밋 히스토리 (`git log -5 --oneline`)
```text
a04826f Merge PR #9: 평가 측 사용자 결정(1~5) 반영 — 역할 개정·verify_all·8C 지시서(Codex)
f8dbdc2 평가 측: verify_all 감사 규칙 대응 — tesseract 호출 고정 인자, 공통 실행 함수 감사 주석
cd0908e 평가 측: verify_all 리뷰 반영 — XML 파싱 제거·--base 검증·추적 안 된 파일 거부·CI 환경 강제
62dc731 docs(handoff): 평가 측 2026-10-03 라운드 프로세스 종합 검토 보고서
6ba30ae 평가 측: 라운드 종합 검토 승인 반영 — verify_all 추가, 8C 프롬프트 분리, AGENTS/ROLES 개정
```

### 1.3 실행 환경 명세
- **OS**: Windows 11 (PowerShell, `PYTHONUTF8=1`)
- **Python**: 3.14.6
- **Tesseract**: 로컬 미설치 (None, CI 환경 Linux 5.3.4 kor/eng와 다름)
- **Playwright 채널**: Google Chrome (`LV_TEST_BROWSER_CHANNEL="chrome"`)

---

## 2. 검증 게이트 및 기준선 실측 결과

### 2.1 사건 고유 리터럴 점검 (`scripts/check_case_literals.py`)
- **명령**: `python scripts/check_case_literals.py`
- **결과**: 부채 4건 유지, 신규 위반 0건 (종료 코드 0 통과)
```text
사건별 시험에서 뽑은 사건 값 53개, 제품 코드에서 발견 4건
  [부채] config/legal_rules/rules.json: 2020도16420, 공제는법률상근거가없, 국가를당사자로하는계약에관한법률, 대금공제는허용되지않
```

### 2.2 성적표 및 점수 게이트 (`scripts/score_gate.py`)
- **명령**: `python scripts/score_gate.py`
- **결과**: 점수 게이트 통과 (종료 코드 0)
```text
경고: 조건 불일치: OCR 5.3.4 → 없음
향상: [dev] 종합 79.9 → 81.7  (기준선 갱신은 평가 에이전트가 요청하고 사용자가 승인한다)
향상: [holdout] 종합 77.3 → 79.2  (기준선 갱신은 평가 에이전트가 요청하고 사용자가 승인한다)
점수 게이트 통과
```

### 2.3 버전 정책 점검 (`scripts/check_version_policy.py`)
- **명령**: `$env:PYTHONUTF8 = "1"; python scripts/check_version_policy.py --base a04826f`
- **결과**: 위반 없음 (종료 코드 0, 버전 0.9.13 변경 없음)
```text
버전 정책: 위반 없음 (버전 변경 없음)
```

### 2.4 회귀 게이트 (`scripts/regression_gate.py`)
- **명령**: `$env:PYTHONUTF8 = "1"; python scripts/regression_gate.py --base a04826f`
- **결과**: 12개 명세×입력 방식 전수 비교 통과, 회귀 0건 (종료 코드 0)
```text
회귀 게이트 — 기준 a04826f → 현재 a04826f (오프라인)
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

### 2.5 회귀 원장 시험 (`tests/regression`)
- **명령**: `$env:PYTHONUTF8 = "1"; python -m pytest -q tests/regression`
- **결과**: 224 통과, 1 xfail (종료 코드 0)
```text
........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
.....x...                                                                [100%]
224 passed, 1 xfailed in 27.5s
```

---

## 3. 기준선 확정 요약

- 모든 5대 검증 게이트(리터럴, 성적표, 버전, 회귀 게이트, 회귀 원장)가 정상 통과(종료 코드 0)함을 실측 확인하였습니다.
- 시작 SHA `a04826f`를 F1 기능 라운드의 확정 기준선으로 삼고, 다음 단계인 설계 요청서(`docs/handoff/requests/19_f1_design.md`) 제출을 진행합니다.
