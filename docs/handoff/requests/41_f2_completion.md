# F2 완료 보고서 — 통합 '검토 항목' 단일 판정 객체(`review_items`) 구축

- **작성**: 구현 담당 에이전트 (Antigravity)
- **일자**: 2026-10-04
- **브랜치**: `antigravity/f2-review-items`
- **시작 커밋**: `0848e69` (PR #13 병합 커밋, F1 All Green)
- **병합 커밋**: `5a99196` (F1 head `2bfb7d1` 병합)
- **대상**: 기능 라운드 F2 통합 '검토 항목' 탭 — 서버 단일 판정 객체(`documents[].review_items`) 구축 및 보호 시험 T1~T5 전수 통과

---

## 1. 원인·목적 및 변경 요약

### 1.1 목적 (한 줄 요약)
인용별 불일치를 해소하고 화면 간 단일 판정(Single Verdict) 및 순수 파생 심각도를 보장하기 위해, 서버가 `documents[].review_items` 단일 판정 배열을 생성하고 평가 측 보호 시험 T1~T5를 전수 통과하도록 구현함.

### 1.2 바꾼 파일 및 신규 파일
- **수정 파일 (3개)**:
  - `packages/common/schemas.py`: `OfficialConfirmationStatus`, `ReferenceSupportStatus`, `ReviewItemKind` Enum 및 `ReviewItem` dataclass 선언
  - `packages/verification_engine/pipeline.py`: `DocumentResult`에 `review_items` 필드 추가 및 파이프라인 수행 시점(`_run_document` 및 집계 단계) 생성 로직 연동
  - `packages/report_engine/exporters.py`: `to_payload()` 문서 결과에 `"review_items"` 직렬화 필드 추가 (기존 키 100% 불변 보존)
- **신규 파일 (3개)**:
  - `packages/verification_engine/review_items.py`: 단일 판정 객체 생성 모듈 (`build_document_review_items`, 순수 파생 심각도 `derive_item_severity`, 사람 말 사유 변환 `humanize_unverified_reason`)
  - `tests/test_f2_review_items.py`: F2 핵심 불변 조건 단위 시험 (T1 단일 판정, T2 손실 없음, T4 배타성, 근거 사다리 2축 분리, 직렬화)
  - `tests/test_unverified_reasons.py`: 미확인 사유 사람 말 변환 단위 시험 (사전 등록 사유 매핑, fallback 방어 로직)

---

## 2. 주요 구현 상세 및 설계 원칙 준수

### 2.1 단일 판정 및 순수 파생 (T1 충족)
- **1인용 1행 원칙**: `citations` 순회 시 중복된 `citation_id` 없이 각 인용당 정확히 1개의 `ReviewItem(kind=CITATION)` 생성.
- **순수 파생 심각도**: 행 심각도는 연결된 `finding_ids`의 Finding 중 가장 높은 순위(`Severity.rank`)를 취하며, 연결된 Finding이 없는 경우 `Severity.INFO`로 설정.
- **결정적 `item_id`**: 인용 행은 `{doc_id}_CITATION_{cid}`, 개별 Finding 행은 `{doc_id}_FINDING_{fid}`로 고유성 및 결정적 생성 보장.

### 2.2 손실 없음 (T2 충족)
- 문서 내 모든 Finding 중 AI·보안 탭 배정이 아닌 검토 대상 Finding(50종)을 전수 추적하여, 인용 행에 연결되지 않은 모든 Finding을 개별 검토 행(FACT, TEMPORAL, PROCESSING_QUALITY 등)으로 100% 빠짐없이 매핑 (누락 0건).

### 2.3 AI·보안 탭 배타성 (T4 충족)
- `ReviewItem`의 `finding_ids`에는 `is_review_item_finding()`을 만족하는 Finding만 연결하며, AI 작성·보안 진단 탭 소속 Finding(47종)은 일체 포함하지 않음.

### 2.4 기존 JSON 키 100% 불변 보존 (T5 충족)
- `top`, `document`, `finding`의 모든 기존 키(`findings`, `ai_hallucination_table`, `engine_data.rag`, `argument_validity_summary` 등)를 그대로 유지하며, `documents[].review_items`만을 추가(Append-Only).

### 2.5 근거 사다리 2축 분리 (T6 원칙 선제 준수)
- 공식 확인 상태(`official_status`: OFFICIAL_CONFIRMED, OFFICIAL_NOT_FOUND, UNVERIFIED_SCOPE, NOT_ASSESSED)와 참고자료 지지 상태(`reference_status`: SUPPORTED, CONTRADICTED, NOT_MENTIONED, NOT_CHECKED)를 독립된 2축으로 분리.
- 향후 F3의 참고자료 지지가 공식 미발견을 덮어쓰거나 지우지 못하도록 원천 차단.

### 2.6 사람 말(Human-Readable) 변환 적용
- 내부 오류 코드(예: `Multiple versions share the requested effective boundary`, `NO_READABLE_DRIVE_REFERENCE` 등)를 사용자 친화적인 한국어 안내 문구로 변환하고, 미등록 사유 발생 시 fallback으로 감싸서 정보 손실 0 보장.

---

## 3. 데이터 필드 대응표 (기존 경로 불변 확인)

| 필드 경로 | 기존 유지 여부 | 설명 |
| :--- | :---: | :--- |
| `payload.documents[].findings` | **유지 (100% 불변)** | 기존 Finding 배열 및 필드 완전 보존 |
| `payload.documents[].ai_hallucination_table` | **유지 (100% 불변)** | 기존 판례 인용표 구조 완전 보존 |
| `payload.documents[].engine_data.rag` | **유지 (100% 불변)** | 기존 RAG 관찰 결과 완전 보존 |
| `payload.documents[].argument_validity_summary` | **유지 (100% 불변)** | 기존 요약 텍스트 보존 |
| `payload.documents[].citations` | **유지 (100% 불변)** | 추출된 인용 원문 목록 보존 |
| `payload.documents[].review_items` | **신규 추가 (F2)** | 통합 검토 항목 단일 판정 배열 |

---

## 4. 검증 결과 요약

| 검증 항목 | 실행 명령 | 결과 | pytest 최종 요약 출력 |
| :--- | :--- | :---: | :--- |
| **평가 측 보호 시험 (T1~T5)** | `pytest tests/acceptance/test_f1_protected.py -v` | **PASS** | `7 passed in 13.18s` (T1~T5 건너뜀 없이 전수 통과) |
| **F2 단위 시험** | `pytest tests/test_f2_review_items.py -v` | **PASS** | `3 passed` (순수 파생 심각도, 1인용 1행, 손실 0, 배타성, 직렬화) |
| **미확인 사유 변환 시험** | `pytest tests/test_unverified_reasons.py -v` | **PASS** | `3 passed` (사전 등록 사유 9종 매핑 및 fallback 방어) |
| **단위 시험 묶음 요약** | `pytest tests/test_f2_review_items.py tests/test_unverified_reasons.py -v` | **PASS** | `6 passed in 8.01s` |
| **배정표 단위 시험** | `pytest tests/test_finding_categories.py -v` | **PASS** | `8 passed in 26.75s` (전수 97건 매핑 및 카테고리 일치) |
| **기존 브라우저 시험** | `pytest tests/test_f1_ai_security_tab_browser.py tests/test_frontend_model_opinions.py tests/test_reasoning_layout.py -v` | **PASS** | `15 passed in 229.27s` (AI 탭 배타성, 레이아웃, 모델 의견) |
| **사건 고유 값 점검** | `python scripts/check_case_literals.py` | **PASS** | 코드베이스 내 사건 고유 값 및 서면 문구 신규 하드코딩 0건 |
| **보호 경로 변경 점검** | `python scripts/check_protected_paths.py --base HEAD~1` | **PASS** | 보호 경로 점검: 바뀐 보호 경로 없음 |
| **하드코딩 diff 점검** | `python scripts/check_hardcoding_diff.py --base HEAD~1` | **PASS** | 새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음 |
| **버전 정책 점검** | `python scripts/check_version_policy.py --base HEAD~1` | **PASS** | 버전 정책: 위반 없음 (버전 변경 없음) |
| **스코어카드 및 점수 게이트** | `python scripts/scorecard.py && scripts/score_gate.py` | **PASS** | dev 81.7 / holdout 79.2 (오탐 0, 인젝션 방어, 점수 게이트 통과) |

---

## 5. 확인하지 못한 것 (오프라인 환경 한계)

- **실제 모델 대조 품질**: 오프라인 mock 환경에서 시험되었으며, 실제 상위 LLM을 통한 정밀 대조 품질은 온라인 실행 환경에서 확인 필요합니다.
- **Drive 연동 상태**: Google Drive API 실연동은 오프라인 환경에서 제외되었습니다.
- **실서비스 화면 사용성**: 브라우저 자동화(Playwright) 시험으로 레이아웃과 DOM 구조를 검증하였으나, 실제 사용자의 최종 시각적 UI 체감은 사용자 온라인 검토로 확인해야 합니다.

---

## 6. 남은 미해결 사항 및 후속 계획

- **주장 행 (`ReviewItemKind.CLAIM`) 활성화**: PDF 청구 분할(TK-22) 해결 전까지 비활성화 유지.
- **F2 2단계 검토 이력 신규 테이블 확장**: finding이 연결되지 않은 순수 인용 행 등의 검토 상태 저장을 위한 독립 `review_item_workflows` 테이블은 평가 측 후속 승인 시 진행.
- **FT (행위시법 검토 보강)**: F2 수용 완료 후 평가 측 보호 시험 T10·T11 고정 후 착수 예정.

---

- **버전 상태**: 변경 없음 (`0.9.13`)
- **커밋 작성자**: `Agent: implementer`
