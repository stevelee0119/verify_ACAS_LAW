# 5차 안정화 라운드 U4 완료 및 U7/U8 보고서 (요청 19)

- 작성: 구현 담당 에이전트 (Antigravity)
- 대상 커밋: `fab8967` (브랜치: `super_cosmos_surges_19h47`)
- 기준 커밋: `17ad6b3` (U9 커밋 직후) / 시작 기준 커밋: `838d964` (`Steve_ACASiaLAW`)
- 측정 환경:
  - 로컬: Windows 11 (PowerShell, `$env:PYTHONUTF8=1`), python 3.14.6, OCR 없음, 오프라인 (`LV_ALLOW_NETWORK=0`)
  - GitHub Actions: Ubuntu, python 3.11, OCR 있음 (Run ID: `37020810650`)
- 버전 상태: **0.9.13 변경 없음 (판정 대기)**

---

## 1. U4 (TK-22) 입력 계층 문단 복원 및 형식 불변성 해결 요약

### 1.1 근본 원인 분석
1. **마크다운 헤더 오인에 따른 블록 삼킴 결함**:
   - `get_unclosed_delimiter`가 마크다운 제목 표지(`### 청구취지`)를 `DELIMITER_PAIRS`의 `("##", "##")` 인젝션 구분자로 오인하여, 다음 헤더(`### 청구원인`)까지 청구취지 전체 항을 미닫힌 인젝션 블록으로 묶어버림.
   - 이로 인해 청구취지 내 인용·법리 검증이 누락되는 사태 발생.
2. **독립 줄 패턴 누락에 따른 날짜/호증 뭉개짐**:
   - 단독 날짜 줄(`2026. 9. 5.`), 호증 목록(`갑 제O호증`), 헤더(`증 거 설 명 서`), 서명·날인란(`(인)`, `(서명 생략)`)이 독립 줄로 보호되지 못하고 일반 본문과 합쳐져 타임라인 역전 미탐 및 호증 0건 인식 결함 유발.
3. **어절 결합 규칙 미비**:
   - `MID_WORD_STARTS`에 `"니다"`, `"습니다"`, `"임"`, `"임을"` 등이 누락되어 `"드리겠습 니다"`, `"무효 임을"`로 분리되어 AIGEN 및 OVR 정규식 미탐 발생.
4. **특수 공백(`\xa0`) 미정규화**:
   - 서면 내 NBSP(`\xa0`)로 인해 정규식 매칭이 깨지는 현상 발생.

### 1.2 조치 내용
- `packages/document_engine/paragraph_reconstruction.py`:
  - `_norm_s` 도입: 유니코드 공백 정규화로 특수 공백(`\xa0`) 문제 전수 해결.
  - 마크다운 헤더(`^#{1,6}\s`)를 인젝션 구분자 검사 대상에서 명시적 제외.
  - `STANDALONE_LINE_PATTERNS` 완비: 날짜, 서명, 호증, 증거설명서 헤더, 대괄호 플레이스홀더, AI 인사말, 바닥글 정밀 독립 줄 보호.
  - `MID_WORD_STARTS` 확장: 조사/어미(`니다`, `습니다`, `임`, `임을`, `이며`, `이고`, `이라`, `이라는` 등) 완비.
  - `segments` 속성을 가진 블록(무괘선 표 등) 단독 유지 및 세로 간격 기반 문단 분리 유지.
- 파서 통합:
  - `pdf_parser.py`, `docx_parser.py`, `hwp_parser.py` 모두 `reconstruct_page_blocks`를 호출하도록 통합.
  - 블록 `text`는 문단 복원, 물리적 줄(`lines`), 좌표(`bbox`), 쪽 번호 속성은 안전하게 보존.
- 회귀 시험 추가 (`tests/regression/test_ledger.py`):
  - TK-22 필수 시험 4건 추가 (txt·pdf·docx 3종 형식 간 줄 폭 변형 불변성, 숨은 텍스트 PDF 보존, 표 블록 보존, 쪽 경계 문단 복원).

---

## 2. 입력 방식별 해결 현황 표 (지침 0.2 준수)

| 결함 항목 | txt (텍스트) | PDF | docx | 비고 |
|---|---|---|---|---|
| 줄바꿈/하드랩 문단 복원 | 해결 | **해결** (`reconstruct_page_blocks` 호출 통합) | **해결** | 전 파서 단일 복원기 사용 |
| 줄 폭 변형 불변성 (36/40/44/48/56/64자) | 해결 | **해결** (KNOWN_OPEN 10건 전수 해소) | **해결** | 배치 불변성 입증 |
| 특수 공백(`\xa0`) 포함 서면 요소 복원 | 해결 | **해결** | **해결** | `_norm_s` 유니코드 정규화 |
| 표(Table) / 무괘선 표 블록 격리 보존 | 해결 | **해결** (`segments` 단독 유지) | **해결** | 본문 병합 방지 |
| 마크다운 헤더 인젝션 오인 방지 | 해결 | **해결** | **해결** | 구분자 제외 처리 |
| 서면9 실제 PDF 원본 청구 분할 및 법령명 | 해당없음 | **해결** (xfail 3건 XPASS) | 해결 | docx와 동일 결과 달성 |

> **소비자별 줄 결합(`_join_hard_wrapped_citations` 등) 잔여 이유**:
> `tests/test_tk07_hard_wrapped_citation.py` 등 기존 단위 테스트에서 해당 함수를 직접 import하여 테스트하고 있으며, 파서를 거치지 않고 직접 문자열을 넘기는 경로에 대한 방어적 안전망(defense-in-depth)을 위해 유지함.

---

## 3. 검증 게이트 및 시험 실측 결과

### 3.1 로컬 검증 (Windows, Python 3.14.6, OCR 없음)
1. **사건 고유 리터럴 점검 (`scripts/check_case_literals.py`)**: 통과 (부채 4건 유지, 신규 위반 0건)
2. **하드코딩 변경분 점검 (`scripts/check_hardcoding_diff.py --base 17ad6b3`)**: 통과 (추가 줄 91개, 시험 입력값/새 rule_id 0건)
3. **회귀 게이트 (`scripts/regression_gate.py --base 17ad6b3`)**: **회귀 없음** (12/12 유지)
4. **성적표 및 점수 게이트 (`scripts/scorecard.py && scripts/score_gate.py`)**:
   - **dev: 81.2** (기준선 79.9 대비 **+1.3** 향상)
     - TC-02: 0.682, TC-03: 1.000, TC-04: 0.906, TC-05: 0.932, TC-06: 0.321
   - **holdout: 79.2** (기준선 77.3 대비 **+1.9** 향상)
     - HO-02: 0.833, HO-03: 0.909, HO-04: 0.844, HO-05: 0.841, HO-06: 0.357
   - 오탐: 0건, A등급 오탐: 0건, 인젝션 방어: 통과
   - **점수 게이트 통과** (종료 코드 0)
5. **회귀 원장 (`pytest -q tests/regression`)**: **125/125 PASSED** (새 시험 4건 포함 전원 통과)
6. **버전 정책 점검 (`scripts/check_version_policy.py --base 17ad6b3`)**: 위반 없음 (0.9.13 유지)

### 3.2 GitHub Actions 점수 하락 게이트 (`Run ID: 37020810650`)
- **성적표 작성 및 점수 게이트**: **성공 통과**
- **수용 시험(Acceptance Test)**:
  - 실패 원인: 구현 성공으로 인한 **`[XPASS(strict)]` 19건** 및 **`KNOWN_OPEN` 해소(`AssertionError: 풀렸다...`) 10건** 발생
  - 즉, 모든 보호 시험의 결함이 성공적으로 해결되어 평가 에이전트의 표기 갱신을 대기 중인 상태임.

---

## 4. 해결되어 평가 측 갱신이 필요한 시험 목록 (XPASS 및 KNOWN_OPEN)

### 4.1 `test_layout_invariance_pdf.py` (KNOWN_OPEN 10건 전수 해소)
- `test_pdf_results_do_not_depend_on_line_width[case6_military_secret-40]` (풀림: CIT-6)
- `test_pdf_results_do_not_depend_on_line_width[case6_military_secret-48]` (풀림: INJ-1)
- `test_pdf_results_do_not_depend_on_line_width[case7_suspension-40]` (풀림: CIT-6)
- `test_pdf_results_do_not_depend_on_line_width[case8_delay_penalty-40]` (풀림: CIT-6)
- `test_pdf_results_do_not_depend_on_line_width[case8_delay_penalty-48]` (풀림: INJ-1)
- `test_pdf_results_do_not_depend_on_line_width[case9_state_compensation-40]` (풀림: INJ-1)
- `test_pdf_results_do_not_depend_on_line_width[case9_state_compensation-48]` (풀림: INJ-1)
- `test_pdf_results_do_not_depend_on_line_width[variant1_discipline-40]` (풀림: INJ-1b)
- `test_pdf_results_do_not_depend_on_line_width[variant1_discipline-48]` (풀림: INJ-1b)
- `test_pdf_results_do_not_depend_on_line_width[variant2_food_license-40]` (풀림: INJ-1a)

### 4.2 `test_case9_real_pdf.py` (실제 PDF strict xfail 3건 전수 XPASS)
- `test_regulation_sentence_is_one_claim`
- `test_citation_law_name_matches_docx`
- `test_claim_count_close_to_docx`

### 4.3 기타 라운드 5 기해결 XPASS 목록 (평가 측 xfail 제거 대기)
- `test_pii_label_variants.py`: 13건 XPASS (U2 기해결)
- `test_reference_match_guard.py`: 3건 XPASS (U1 기해결)

---

## 5. U8 `main` 브랜치 보호 설정 점검 결과

- **완료 여부**: **권한 없음 (GitHub Free Private Repository 제약)**
- **확인 결과**:
  - `gh api repos/stevelee0119/verify_ACAS_LAW/branches/main/protection` 실행 시:
    ```json
    {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","status":"403"}
    ```
  - `gh api repos/stevelee0119/verify_ACAS_LAW/rulesets` 실행 시:
    ```json
    {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","status":"403"}
    ```
  - GitHub 비공개(private) 무료 개인 저장소에서는 Branch Protection 및 Ruleset 설정 API가 GitHub Pro 이상 구독 또는 공개(public) 저장소 전환 시에만 지원됩니다.
- **사용자 조치 안내**:
  - 사용자가 추후 저장소를 Public으로 전환하거나 GitHub Pro로 업그레이드할 경우, GitHub UI 화면에서 아래와 같이 설정하실 수 있습니다:
    1. 저장소 Settings → Branches (또는 Rules) → `main`
    2. **Require status checks to pass before merging**: 체크
    3. 필수 확인 항목에 **`점수 하락 게이트`** (잡 이름)만 지정 (`CI` 및 `Docker OCR readiness`는 제외)
    4. **Do not allow force pushes** (강제 푸시 금지): 체크
    5. **Do not allow deletions** (브랜치 삭제 금지): 체크
    6. "Require a pull request before merging"은 켜지 않음 유지.

---

## 6. 확인하지 못한 항목 (투명성 보고)
- **CI (`ci.yml`) 실행 결과**: `ci.yml`은 `main`, `claude/**`, `codex/**` 푸시 및 PR에서만 실행되도록 설정되어 있어, 작업 브랜치(`super_cosmos_surges_19h47`) 푸시로는 실행되지 않음 (실패가 아닌 **실행되지 않음**).
- **온라인 환경에서 서면9 원본의 Drive 대조 복구**: Google Drive 및 외부 네트워크가 차단된 오프라인 테스트 환경이므로, 사용자의 실제 온라인 환경 실행에서 최종 확인 필요.

---

## 7. 버전 상태
- 현재 버전: `0.9.13` (변경 없음, 평가 에이전트의 5차 안정화 판정 대기)
