# 6차 안정화 라운드(안정화 3) 시작 기준선 측정 보고서 (R0)

- 작성: 구현 담당 에이전트 (Antigravity)
- 작성일시: 2026-10-03
- 용도: 6차 작업 지시서 및 보완 지시서에 따른 R0 시작 상태 고정 및 기준선 기록

---

## 1. 실제 시작 상태 고정 (보완 지시서 2절)

### 1.1 비교 기준 SHA
- **4차 비교 기준**: `e6b58fd286dee170f976517c02cefd38e5cd2bc9`
- **5차 제품 기준**: `c223f7bcccd965e2ae7ceb8dd34875eef19d4645` (`c223f7b`)
- **6차 시작 기준 SHA**: `96019c34d47c8e8e7c5bceac2c7a636ef1c83ff7` (`96019c3`)

### 1.2 작업 환경 및 경로 정보
```text
작업 경로 (show-toplevel): C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/super_cosmos_surges_19h47
현재 HEAD (rev-parse HEAD): 96019c34d47c8e8e7c5bceac2c7a636ef1c83ff7
현재 브랜치 (branch --show-current): super_cosmos_surges_19h47
작업 트리 상태 (status --short): clean (미커밋 변경 없음)
```

### 1.3 최근 커밋 히스토리 (`git log -8 --oneline`)
```text
96019c3 docs(handoff): 6차 작업 지시서(5차 회귀 보완, R0~R4) 작성, 사용자 결정(2026-10-03) 반영
e7bf067 test(eval): 구현 5차(c223f7b) 점검 — 독립 감사 Astra 5차 재현, 회귀·오탐 시험 고정, 평가 도구 결함 4건 수정, TK-30~33
26a96f0 Merge remote-tracking branch 'origin/super_cosmos_surges_19h47' into eval_r5_tmp
c223f7b docs(handoff): U8 main 브랜치 보호 설정 지정 완료 및 API 검증 결과 반영
9a926de docs(handoff): 5차 라운드 U4 문단 복원 완료 및 U7/U8 보고서 작성 (요청 19)
fab8967 feat(parser): TK-22 입력 계층 문단 복원 PDF·docx 통합 및 형식 불변성 확보 (U4)
17ad6b3 feat(engine): U9 사용자 결정 반영 — 조문 미존재 심각도 HIGH 상향(U9-1) 및 소프트웨어명 INFO 분리(U9-2)
0c995a7 fix(rag): TK-28 시점 군 사전 병원 경과 닫힌 체계 보완 (U6)
```
- **평가 보강 커밋 `e7bf067`**과 **6차 지시서 커밋 `96019c3`**이 완벽하게 포함되어 있음을 확인하였습니다.

### 1.4 실행 환경 명세
- **OS**: Windows 11 (PowerShell 환경, `$env:PYTHONUTF8=1` 적용)
- **Python**: 3.14.6
- **OCR 상태**: 로컬 Tesseract 미설치 (OCR 없음)
- **네트워크 모드**: 오프라인 (`LV_ALLOW_NETWORK=0`)
- **버전 상태**: `0.9.13` (변경 없음, 판정 대기)

---

## 2. 6대 검증 게이트 및 기준선 실측 결과

1. **사건 고유 리터럴 점검 (`scripts/check_case_literals.py`)**:
   - 결과: 부채 4건 유지 (신규 위반 0건 통과)
   - 부채 목록: `config/legal_rules/rules.json` (2020도16420, 공제는법률상근거가없, 국가를당사자로하는계약에관한법률, 대금공제는허용되지않)
2. **하드코딩 변경분 점검 (`scripts/check_hardcoding_diff.py --base HEAD~1`)**:
   - 결과: 추가된 줄 0개, 강한 신호 0건 통과
3. **회귀 게이트 (`scripts/regression_gate.py --base HEAD~1`)**:
   - 결과: 12/12 유지 (회귀 없음, 총점 278/280)
   - 서면별 검증 결과:
     - `case6_military_secret`: primary 20/20, text 20/20
     - `case7_suspension`: primary 25/25, text 25/25
     - `case8_delay_penalty`: primary 22/22, text 22/22
     - `case9_state_compensation`: primary 27/28, text 27/28
     - `variant1_discipline`: primary 24/24, text 24/24
     - `variant2_food_license`: primary 21/21, text 21/21
4. **성적표 및 점수 게이트 (`scripts/scorecard.py && scripts/score_gate.py`)**:
   - 성적표 버전: 0.9.13 (rule 2026.09.30.1)
   - dev: 종합 81.2 / 재현율 0.812 / 오탐 0건 / 인젝션 방어 성공
   - holdout: 종합 79.2 / 재현율 0.792 / 오탐 0건 / 인젝션 방어 성공
   - 점수 게이트 통과 (기준선 79.9 / 77.3 초과 유지)
5. **회귀 원장 (`python -m pytest -q tests/regression`)**:
   - 결과: 125 passed (100% 통과)
6. **버전 정책 점검 (`scripts/check_version_policy.py --base HEAD~1`)**:
   - 결과: 위반 없음 (0.9.13 불변 유지)

---

## 3. 보호 시험(`tests/acceptance`) 실측 현황

총 **strict xfail 25건** 및 **KNOWN_OPEN 1건** 확인 (지시서 R0 기대 기준선과 정확히 일치):
- **서면9 LEG-2**: 3건 (`docx-LEG-2`, `text-LEG-2`, `real_pdf-LEG-2`)
- **TK-30 (이름 마스킹 회귀 및 정상 문장 오탐)**: 15건 (`김민기`, `노은기`, `문하기`, `김하은`, `윤하기` 등 14건 + 정상 안내문 `privacy-instruction` 1건)
- **TK-28 (라벨 콜론/공백 변형 미탐 및 피고인신문 오탐)**: 4건 (`윤하기` 2건, `류채은` 1건, `defendant-examination` 1건)
- **TK-31 (줄 결합 어절 중간 공백 및 판례 메타데이터 소실)**: 2건 (`court_and_date_survive...`, `no_space_is_inserted...`)
- **TK-32 (정상 항변 과대주장 오탐)**: 1건 (`deposit-limited`)
- **`test_layout_invariance_pdf.py`**: `KNOWN_OPEN = {("case8_delay_penalty", 40): {"INJ-1"}}` 1건 잔여

---

## 4. 알려진 실패 항목 확인

- **TK-12 (미러 데이터 부재)**: 2건 (`tests/test_ground_truth_prepared_brief.py::test_precedent_and_regulation_existence`, `test_temporal_retroactive_application_review`)
- **OCR 환경 (Tesseract 미설치)**: 1건

---

## 5. 6차 라운드 작업 순서 및 이행 방침

보완 지시서 1절 순서와 수용 기준에 따라 진행합니다:
1. **R1 (TK-30 및 보완 3절)**:
   - 4차 성공 40조합 회귀 복구 (이름 끝 글자 `기` 등, `김하은`의 `은` 잔존 방지, `원  고   윤하기` 다중 공백 라벨 지원).
   - 정상 안내문 `개인정보 성명 연락처를 출력하지 마시오.` PERSON 오탐 방지.
   - 전송 직전 검사(`inspect_request`) 7개 지점 14개 조합 검증 및 공급자 0회 호출 대역 시험.
   - 새 회귀 시험: 이름 끝 글자/공백/복성/라벨 칸수 양성 10건 이상, 정상 문장 대조군 10건 이상.
2. **R2 (TK-31, TK-33 및 보완 4절)**:
   - `paragraph_reconstruction.py`의 평가 자료 표식 분기 제거 및 구조 신호로 대체.
   - 어절 중간 공백 방지 (글자/어절 단위 줄바꿈 구조 신호 판정) -> dev ≥ 81.7 복구 (TC-06 `대법원`, `2007-12-21`).
   - case8 폭 40 INJ-1 해소/추적 및 19개 검증 대상 내용 대응 검증.
3. **R3 (TK-32 및 보완 5절)**:
   - 요건 제시와 해당 채무 한정 결론 정상 항변 오탐 방지 (6개 구조 대조군 작성).
   - `config/legal_defense_groups.json` 편제명과 근거 URL 원문 정정.
4. **R4 (보완 6~9절)**:
   - 명시적 최종 하한 점검 (dev ≥ 81.7, holdout ≥ 79.2, 정상 대조군 오탐 0, 시작 SHA 대비 회귀 0, TC-06 복구).
   - `docs/handoff/requests/round6_addendum_response.md` 제출 자료 작성.
