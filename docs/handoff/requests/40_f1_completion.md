# F1 완료 보고서 — AI 탭 축소 및 배정표 모듈 신설

브랜치: `antigravity/f1-review-screen`

---

## 1. 개요 및 목적

기능 라운드 F1은 기존 검토 화면의 역할을 명확히 재정의하고, 향후 F2(통합 검토 화면)로 안전하게 이행하기 위한 기반 단계입니다.
- **AI 탭의 역할 축소**: AI 모델의 거짓 주장(환각) 및 인용 오류 등 내용 검토 기능은 F2 '검토 항목' 탭으로 통합될 예정이므로, AI 탭은 순수하게 **'AI 작성·보안 진단'** 전용 화면으로 축소했습니다.
- **배정표 단일 소스(SSOT) 확립**: 전체 97개 `FindingType`에 대해 중복 및 누락 없이 AI 작성·보안 진단 탭과 검토 항목 탭으로 1:1 전수 매핑하는 모듈(`packages/common/finding_category_map.py`)을 신설했습니다.
- **정보 손실 방지 (Zero Information Loss)**: F2 통합 전까지 기존 판례 인용 검토 결과가 유실되지 않도록, '검토 항목' 탭 하단에 임시 섹션을 마련하여 온전히 보존했습니다.
- **HIGH 이상 보안 위험 알림**: 보안 및 인젝션 주의 항목이 발견될 경우 '검토 항목' 탭 상단에 고정 안내 배너를 노출하여 즉시 AI 작성·보안 진단 탭으로 이동할 수 있도록 안내합니다.

---

## 2. 주요 변경 사항

### 2.1 단일 배정표 모듈 신설 (`packages/common/finding_category_map.py`)
- 전체 97개 `FindingType` 열거형 항목을 전수 조사하여 1:1 매핑 정의 (누락 0, 초과 0, 합계 97).
- **회신서 3.2절 반영**: `MODEL_FACT_REMARK`를 '검토 항목' 탭의 `FACTS`(사실관계) 하위 범주로 재배정.
- **회신서 3.3절 반영**: `OCR_LOW_QUALITY`를 '검토 항목' 탭의 `PROCESSING`(처리 품질) 하위 범주로 재배정.
- **배정 현황 요약 (코드 기준)**:
  - **AI 작성·보안 진단 탭 (47건)**:
    - AI 진단 카드 (`AI_DIAGNOSIS`): 5건
    - 인젝션 검증 카드 (`INJECTION_DEFENSE`): 17건
    - 보안 카드 (`SECURITY_CARD`): 25건
  - **검토 항목 탭 (50건)**:
    - 사실관계 행 (`FACT_DISCREPANCY`): 27건 (`MODEL_FACT_REMARK` 포함)
    - 법률·판례 인용 행 (`LEGAL_CITATION`): 11건
    - MM4 권고 행 (`MM4_ADVISORY`): 5건
    - 시점·연표 검토 행 (`TEMPORAL_TIMELINE`): 4건
    - 처리 품질 행 (`PROCESSING_QUALITY`): 3건 (`OCR_LOW_QUALITY` 포함)
- `apps/api/routers/projects.py`에 `GET /api/finding-categories` 엔드포인트를 추가하여 프론트엔드와 외부 검증기에서 참조 가능하도록 구성.

### 2.2 화면 개편 및 프론트엔드 조정 (`apps/web/index.html`, `apps/web/static/app.js`, `styles.css`)
- **배정표 동적 분류 (하드코딩 제거)**:
  - `app.js`의 `AI_SECURITY_FINDING_TYPES`, `SECURITY_CARD_FINDING_TYPES` 하드코딩을 제거하고, `/api/finding-categories` API를 호출하여 동적으로 분류 기준을 취득.
  - 배정표 로드 실패 시 정보 손실 방지(Zero Information Loss) 원칙에 따라 모든 finding을 '확인할 항목'에 표시하고, AI 작성·보안 탭에는 오류 안내 상자를 표시.
- **탭 명칭 변경**: 기존 'AI 진단' 탭을 **'AI 작성·보안 진단'**으로 변경.
- **상단 안내 배너**: AI 탭 상단에 안내 배너 배치:
  > "AI 모델의 허위 주장·인용 왜곡 검토 결과는 '검토 항목' 탭에서 통합 제공됩니다."
- **AI 탭 3대 카드 유지 및 인용/RAG 섹션 완전 제거**:
  1. 문서 AI 생성 진단 카드 (`#aiGenerationCard`)
  2. 프롬프트 인젝션 검증 카드 (`#promptInjectionCard`)
  3. AI 관련 보안 진단 카드 (`#aiSecurityFindingsCard`)
  - 인용 오류, '주요 참고문헌 검토(RAG)', '추가 관련 법조문 검토' 섹션을 AI 탭에서 완전 제거.
- **상단 고정 안내 배너 (`#highSecurityAlertBanner`)**:
  - `CRITICAL` 또는 `HIGH` 심각도의 AI 작성·보안 항목이 존재할 경우 '검토 항목' 탭 최상단에 주황색 경고 배너 고정 노출.
  - 클릭 시 `AI 작성·보안 진단` 탭으로 즉시 탭 전환.
- **임시 판례 인용 및 RAG 검토 섹션 (`#temporaryCitationSection`)**:
  - F2 통합 검토 화면 구현 전까지 정보 유실을 방지하기 위해, '검토 항목' 탭 하단에 기존 판례 인용 검토표, '주요 참고문헌 검토(RAG)', '추가 관련 법조문 검토'를 임시 섹션으로 온전히 이전 및 렌더링.

---

## 3. 화면별 변경 전/후 비교

| 화면 요소 | 변경 전 | 변경 후 (F1 보완) | 비고 |
| :--- | :--- | :--- | :--- |
| **AI 탭 명칭** | AI 진단 | **AI 작성·보안 진단** | 역할 명확화 |
| **AI 탭 상단 안내** | 없음 | **통합 안내 배너** 노출 | 검토 항목 탭 안내 |
| **AI 탭 인용/RAG/법조문** | AI 탭 내부 테이블 및 섹션 노출 | **AI 탭에서 완전 제거 (0건)** | F2 이관 준비 (T4 충족) |
| **AI 탭 보안 진단 카드** | 단순 보안 목록 | **AI 관련 보안 진단 전용 카드** | 25개 보안 유형 |
| **검토 항목 탭 상단** | 단순 항목 필터 | **HIGH 이상 보안 주의 배너** | 클릭 시 AI 탭 점프 |
| **판례 인용 및 RAG 검토표** | AI 탭에 존재 | **검토 항목 탭 하단 임시 섹션 보존** | 정보 손실 0 |

---

## 4. Diff Stat

`git diff upstream/Steve_ACASiaLAW..HEAD --stat -- apps/ packages/ tests/`:

```text
 apps/api/routers/projects.py              |  13 ++
 apps/web/index.html                       |   6 +-
 apps/web/static/app.js                    | 259 +++++++++++++++++--------
 apps/web/static/styles.css                |  67 +++++++
 packages/common/finding_category_map.py   | 221 ++++++++++++++++++++++
 tests/acceptance/test_f1_protected.py     | 153 +++++++++++++++
 tests/fixtures/f1_json_keys_baseline.json |  78 ++++++++
 tests/test_check_test_edits.py            |  28 +++
 tests/test_drive_rag_relevance.py         |   6 +-
 tests/test_f1_ai_security_tab_browser.py  | 304 ++++++++++++++++++++++++++++++
 tests/test_finding_categories.py          | 110 +++++++++++
 tests/test_frontend_citation_groups.py    |   2 +-
 tests/test_frontend_model_opinions.py     |   6 +-
 tests/test_frontend_summary_compact.py    |   2 +-
 tests/test_reasoning_layout.py            |   2 +-
 15 files changed, 1171 insertions(+), 86 deletions(-)
```

---

## 5. 검증 결과

| 검증 항목 | 실행 명령 | 결과 | 상세 내용 |
| :--- | :--- | :---: | :--- |
| **평가 측 보호 시험 (T3, T4, T5)** | `pytest tests/acceptance/test_f1_protected.py` | **PASS** | 4 passed, 3 skipped (T3 1, T4 2, T5 1 통과, T1·T2·T4 검토 행은 review_items 없음으로 건너뜀) |
| **배정표 단위 시험** | `pytest tests/test_finding_categories.py` | **PASS** | 8 passed (전수 97건 매핑, 무결성, API 응답 검증) |
| **F1 브라우저 기능 시험** | `pytest tests/test_f1_ai_security_tab_browser.py` | **PASS** | 5 passed (배너 노출, 탭 전환, 하단 임시 섹션 렌더링 검증) |
| **기존 브라우저 시험 위치 이전** | `pytest tests/test_drive_rag_relevance.py tests/test_frontend_citation_groups.py tests/test_frontend_model_opinions.py tests/test_frontend_summary_compact.py tests/test_reasoning_layout.py` | **PASS** | 61 passed (locator 및 탭 전환 조정, 내용 단언 불변) |
| **보호 경로 점검** | `python scripts/check_protected_paths.py --base a04826f` | **PASS** | 보호 경로 23건 모두 평가 측 커밋 또는 승인 확인 |
| **사례 리터럴 점검** | `python scripts/check_case_literals.py` | **PASS** | 신규 하드코딩 없음 (기존 부채 4건 유지) |
| **하드코딩 변경 점검** | `python scripts/check_hardcoding_diff.py --base a04826f` | **PASS** | 신규 코드 내 사건 값/조문 번호 없음 |
| **버전 정책 점검** | `python scripts/check_version_policy.py --base a04826f` | **PASS** | 버전 불변 (`0.9.13` 유지) |
| **시험 편집 점검** | `python scripts/check_test_edits.py --base a04826f` | **PASS** | 시험 삭제·약화 0건 (승인된 탭 전환·locator만 변경) |
| **성적표 및 점수 게이트** | `python scripts/scorecard.py && python scripts/score_gate.py` | **PASS** | dev 81.7 / holdout 79.2 (기준선 유지 및 게이트 통과) |

---

## 6. 미확인 사항 및 향후 과제

1. **실제 LLM/외부 Drive 연동**: 이번 F1 화면 축소 및 배정표 작업은 정적 구조 개편이므로 모의 데이터 기반으로 검증되었습니다.
2. **F2 진행 계획**: F2 단계에서는 '검토 항목' 탭 하단에 임시 배치된 판례 인용 검토표를 단일 통합 검토 테이블로 승격하고, 상태 변경 워크플로우를 신규 테이블 구조로 통합할 예정입니다.
