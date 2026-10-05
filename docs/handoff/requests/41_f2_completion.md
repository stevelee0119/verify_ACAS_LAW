# F2 완료 보고서 — 통합 '검토 항목' 단일 판정 객체(`review_items`) 및 4열 표 화면 구현 (TK-60 보완 완료)

- **작성**: 구현 담당 에이전트 (Antigravity)
- **일자**: 2026-10-05
- **브랜치**: `antigravity/f2-review-items`
- **시작 커밋**: `7f5399f` (PR #13 병합 커밋, F1 최종 머지)
- **대상**: 기능 라운드 F2 통합 '검토 항목' 탭 — 서버 단일 판정 객체(`documents[].review_items`) 구축 및 4열 통합 표 화면(행 안 워크플로우 실제 계약 연동, 복수 finding 벌크 저장, 필터·우선순위 정렬·체크박스 연동, RAG 보존) 구현

---

## 1. 원인·목적 및 변경 요약

### 1.1 목적 (한 줄 요약)
인용별 불일치를 해소하고 화면 간 단일 판정(Single Verdict) 및 순수 파생 심각도를 보장하기 위해 서버 `documents[].review_items` 단일 판정 배열을 생성하고, '확인할 항목' 탭을 4열 통합 표(위치/주장·인용/근거 확인/법리 타당성·대응)로 개편하여 실제 워크플로우 계약(`workflow_state`, `decision`, `priority`, `assignee`, `note`, `revision`)과 연동되는 행 안 워크플로우 조작(단일·복수 finding 개별 GET/PUT 저장 및 메타데이터 독립 보존) 및 필터·우선순위 정렬·체크박스를 구현함.

### 1.2 바꾼 파일 및 신규 파일 (총 16개 파일)
- **수정 파일 (12개)**:
  - `packages/common/schemas.py`: `OfficialConfirmationStatus`, `ReferenceSupportStatus`, `ReviewItemKind` Enum 및 `ReviewItem` dataclass 선언
  - `packages/verification_engine/pipeline.py`: `DocumentResult`에 `review_items` 필드 추가 및 파이프라인 수행 시점 생성 연동
  - `packages/report_engine/exporters.py`: `to_payload()` 문서 결과에 `"review_items"` 직렬화 필드 추가 (기존 키 100% 불변 보존)
  - `apps/web/index.html`: `data-panel="review"` 내 4열 통합 검토 표(`#reviewTable`, `tbody#aiVerificationRows`, 1열 전체 선택 체크박스 `#selectAllFindings`), `#hallucinationSection`, `#unverifiedScopeContainer`, `#reviewReferencesContainer` 구성 및 `#temporaryCitationSection` 제거
  - `apps/web/static/app.js`:
    - `d.review_items` 기반 4열 통합 표 렌더링
    - 행 안 인라인 워크플로우 컨트롤(검토 상태, 우선순위, 담당자) 배치
    - 실제 백엔드 워크플로우 계약 연동(`saveRowWorkflow`): 기존 메모·담당자·우선순위·revision 보존 및 바꾼 칸만 PUT `/findings/{id}/workflow`
    - 상태 매핑: 확인 전(`NOT_STARTED`/`UNDECIDED`), 지적 수용(`COMPLETED`/`AGREED`), 오탐(`COMPLETED`/`FALSE_POSITIVE`), 조치 완료(`COMPLETED`/`UNDECIDED`)
    - 복수 finding 연결 행은 각 finding마다 GET으로 현재 값·revision 조회 후 바꾼 칸만 덮어 개별 PUT 전송 (타 finding의 메모·담당자·우선순위 덮어쓰기 방지 및 100% 독립 보존, TK-60 7절)
    - 409 충돌/오류 발생 시 실패 건수 안내 및 `loadResults` 재조회, 성공 토스트는 전체 성공 시에만 노출
    - 필터(진행 상태 `workflowFilter`, 담당자 `assigneeFilter`, 중요도, 검토 상태, 검색어) 및 우선순위 정렬, 행 체크박스(`.row-checkbox`)·전체선택(`#selectAllFindings`)·일괄 검토(`#batchReview`) 재연결
    - RAG 참고문헌 및 추가 관련 법조문, 미확인 범위 하단 렌더링 보존 (정보 손실 0)
  - `apps/web/static/styles.css`: `.review-items-table`, `.inline-workflow-box`, `.inline-workflow-controls`, `.inline-field`, `.inline-workflow-select`, `.inline-priority-select`, `.inline-assignee-input`, `.inline-workflow-note`, `.row-checkbox`, `.review-references-wrap` 스타일 추가
  - `apps/web/static/workflow.js`: `workflowUI` 객체에 `selected`, `bulkEditor`, `renderReviewCount`, `workflows` getter 노출
  - `tests/test_f1_ai_security_tab_browser.py`: review 탭 locator를 `section[data-panel="review"]`로 수정 (단언 불변)
  - `tests/test_frontend_model_opinions.py`: 테스트 모의 서버에 `/api/finding-categories` 라우트 핸들러 추가
  - `tests/test_drive_rag_relevance.py`: F2 화면 구조에 맞추어 renderTemporaryCitationSection 대신 renderFindings 호출로 갱신 (단언 불변)
  - `tests/test_frontend_citation_groups.py`: F2 4열 표 locator `#aiVerificationRows tr`로 갱신 및 모의 서버에 `/api/finding-categories` 추가 (단언 불변)
  - `docs/handoff/requests/41_f2_completion.md`: 완료 보고서 작성 및 정정
- **신규 파일 (4개)**:
  - `packages/verification_engine/review_items.py`: 단일 판정 객체 생성 모듈 (`build_document_review_items`, 순수 파생 심각도 `derive_item_severity`, 사람 말 사유 변환 `humanize_unverified_reason`)
  - `tests/test_f2_review_items.py`: F2 핵심 불변 조건 단위 시험 (T1 단일 판정, T2 손실 없음, T4 배타성, 근거 사다리 2축 분리, 직렬화), 실제 API 기반 '오탐 저장 → FALSE_POSITIVE' 워크플로우 계약 검증 및 복수 finding 행 조작 시 각 finding별 개별 메타데이터(메모·담당자·우선순위) 보존 검증 시험 (TK-60 7절)
  - `tests/test_unverified_reasons.py`: 미확인 사유 사람 말 변환 단위 시험
  - `tests/test_f2_review_screen_browser.py`: F2 4열 표 화면, 행 안 실제 계약 조작(단일·복수 finding 개별 GET/PUT), 필터별 행 수 검증, 행/전체 체크박스 및 일괄 검토 검증, 파생 항목 묶음(`.derived-findings`) 검증, RAG/법조문 보존 검증 브라우저 시험

---

## 2. 주요 구현 상세 및 설계 원칙 준수

### 2.1 서버 단일 판정 및 순수 파생 (T1~T5 충족)
- **1인용 1행 원칙**: `citations` 순회 시 중복된 `citation_id` 없이 각 인용당 정확히 1개의 `ReviewItem(kind=CITATION)` 생성.
- **순수 파생 심각도**: 행 심각도는 연결된 `finding_ids`의 Finding 중 가장 높은 순위(`Severity.rank`)를 취하며, 연결된 Finding이 없는 경우 `Severity.INFO`로 설정.
- **결정적 `item_id`**: 인용 행은 `{doc_id}_CITATION_{cid}`, 개별 Finding 행은 `{doc_id}_FINDING_{fid}`로 고유성 및 결정적 생성 보장.
- **손실 없음**: 검토 대상 Finding(50종)을 전수 추적하여, 인용 행에 연결되지 않은 모든 Finding을 개별 검토 행(FACT, TEMPORAL 등)으로 100% 매핑.
- **AI·보안 배타성**: `ReviewItem`의 `finding_ids`에는 AI·보안 탭 소속 Finding(47종)을 일체 포함하지 않음.
- **기존 키 100% 불변 보존**: `findings`, `ai_hallucination_table`, `engine_data.rag` 등을 유지하고 `documents[].review_items`만 추가.
- **근거 사다리 2축 분리**: 공식 확인 상태(`official_status`)와 참고자료 지지 상태(`reference_status`)를 독립된 2축으로 선제 분리.

### 2.2 클라이언트 4열 통합 검토 화면 및 행 안 워크플로우 연동 (TK-60)
- **표 칼럼 구성 (4열)**:
  1. `위치` (10%): 전체선택 체크박스(`#selectAllFindings`), 행 체크박스(`.row-checkbox`), 파일명, 쪽수 표시, 쪽 보기 링크, 항목 유형 배지
  2. `문서 주장 및 인용 내용` (25%): 인용 판례/법령, 주장 문구, 파생 Finding 상세 모달 열기 버튼(`openFinding`), 복수 Finding 파생 묶음 아코디언(`.derived-findings`)
  3. `근거 확인 결과` (25%): 심각도 배지, 확인 결과 배지, 생성 근거 텍스트, 인용 취지·맥락 검토(AI 참고 의견) 블록
  4. `법리적 타당성 검토 및 반박 근거` (40% - 최대 너비): 법리 검토 상세 섹션(`reasoningBlock`), 대응 방안 박스, **행 안 인라인 워크플로우 컨트롤**
- **행 안 실제 워크플로우 계약 연동 (`saveRowWorkflow`)**:
  - 현재 값과 `revision`을 조회하여 바꾼 칸만 덮어쓰고 기존 메모·담당자·우선순위 보존.
  - 단일 및 복수 finding 연결 행: 각 finding마다 `GET /api/findings/{id}/workflow`로 현재 값과 revision을 읽고 바꾼 칸만 덮어 개별 `PUT /api/findings/{id}/workflow` 전송 (TK-60 7절, 일괄 API의 타 finding 메타데이터 덮어쓰기 문제 원천 해소).
  - 상태 매핑: 확인 전(`NOT_STARTED`/`UNDECIDED`), 지적 수용(`COMPLETED`/`AGREED`), 오탐(`COMPLETED`/`FALSE_POSITIVE`), 조치 완료(`COMPLETED`/`UNDECIDED`).
  - 일부 409 Conflict 또는 오류 발생 시 실패 건수를 안내하고 최신 데이터 재조회(`loadResults`).
  - 성공 안내 토스트는 모든 finding 저장이 성공했을 때만 노출.
- **필터·우선순위 정렬·체크박스 재연결**:
  - 진행 상태(`workflowFilter`), 담당자(`assigneeFilter`), 중요도, 검토 상태, 검색어 필터 즉각 반영.
  - 우선순위(1순위 우선 검토 -> 2순위 보통 -> 3순위 후순위) 및 심각도 역순 정렬.
  - 행 체크박스(`.row-checkbox`) 및 전체 선택(`#selectAllFindings`)으로 일괄 검토(`#batchReview`) 연동.
- **참고자료(RAG) 및 법조문, 미확인 범위 보존**:
  - 표 하단에 주요 참고문헌 검토(RAG), 추가 관련 법조문 검토, 미확인 범위 섹션을 온전히 보존하여 정보 손실 0 유지.

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
| **단위 및 보호 시험 묶음** | `pytest tests/test_workspace.py tests/test_f2_review_items.py tests/acceptance/test_f1_protected.py tests/acceptance/test_f1_screen_protected.py -v` | **PASS** | `21 passed in 67.29s (0:01:07)` |
| **F2 화면 브라우저 시험** | `pytest tests/test_f2_review_screen_browser.py -v` | **PASS** | `7 passed in 102.69s (0:01:42)` |
| **미확인 사유 단위 시험** | `pytest tests/test_unverified_reasons.py -v` | **PASS** | `3 passed in 5.73s` |
| **기존 브라우저 시험 전수 묶음** | `pytest tests/test_f1_ai_security_tab_browser.py tests/test_frontend_model_opinions.py tests/test_reasoning_layout.py tests/test_frontend_citation_groups.py tests/test_drive_rag_relevance.py tests/test_upload_privacy_notice_browser.py tests/test_frontend_upload.py -v` | **PASS** | `77 passed in 323.22s (0:05:23)` |
| **사건 고유 값 점검** | `python scripts/check_case_literals.py` | **PASS** | 코드베이스 내 사건 고유 값 및 서면 문구 신규 하드코딩 0건 (종료 코드 0) |
| **보호 경로 변경 점검** | `python scripts/check_protected_paths.py --base upstream/Steve_ACASiaLAW` | **PASS** | 보호 경로 점검: 바뀐 보호 경로 없음 (종료 코드 0) |
| **시험 삭제·약화 점검** | `python scripts/check_test_edits.py --base 158d6d4` | **PASS** | 시험 삭제·약화 점검 — 기준 158d6d4: 기존 시험의 삭제·표시 변경 없음 (종료 코드 0) |
| **버전 정책 점검** | `python scripts/check_version_policy.py --base upstream/Steve_ACASiaLAW` | **PASS** | 버전 정책: 위반 없음 (버전 변경 없음, 종료 코드 0) |

---

## 5. 확인하지 못한 것 (오프라인 환경 한계)

- **실제 외부 모델 대조 품질**: 오프라인 mock 환경에서 시험되었으며, 실제 상위 LLM을 통한 정밀 대조 품질은 온라인 실행 환경에서 확인 필요합니다.
- **Drive 연동 상태**: Google Drive API 실연동은 오프라인 환경에서 제외되었습니다.

---

## 6. 남은 미해결 사항 및 후속 계획

- **F2 (통합 검토 항목 탭 및 단일 판정)**: TK-60 보완 요구사항 전수 구현 및 브라우저/단위 시험 완료.
- **주장 행 (`ReviewItemKind.CLAIM`) 활성화**: PDF 청구 분할(TK-22) 후속 과제로 보류 유지.
- **FT (행위시법 검토 보강) 및 F3 (RAG 증강)**: F2 머지 후 후속 착수 예정.

---

- **버전 상태**: 변경 없음 (`0.10.0`)
- **커밋 작성자**: `Agent: implementer`
