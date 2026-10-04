# 구현 완료 보고서: 업로드 개인정보 안내·확인 및 보장 범위 명시 (39_upload_notice_completion)

작성: Antigravity (구현 에이전트 — 화면/API 작업)  
일자: 2026-10-04  
기준 커밋(Base): `a04826f` (`upstream/Steve_ACASiaLAW`)  
작업 브랜치: `antigravity/upload-privacy-notice`  
근거: 사용자 결정(2026-10-04, handoff README), TK-56 3절, TK-57 지시서

---

## 1. 구현 요약

지시서의 5대 요구사항과 제약 조건을 준수하여 화면, API, 감사 로그, 보고서 머리 표시 및 판 관리를 모두 구현하였습니다.

### 1) 화면 안내 및 확인 체크박스 (`apps/web/`)
- **상시 안내문 노출 (`apps/web/index.html`, `apps/web/static/styles.css`)**:
  - 자료 패널의 '파일 추가' 영역 상단에 영구적인 안내 배너(`.privacy-notice`)를 배치하여 3대 안내 문구를 상시 표시합니다.
    1. "자동으로 가리는 개인정보는 연락처와 주민등록번호뿐입니다."
    2. "성명·주소 등 그 밖의 개인정보는 업로드 전에 직접 가려 주세요."
    3. "성명 등 자동 가림은 보조 기능이며 모두 가려진다고 보장하지 않습니다."
- **접근성 준수 체크박스**:
  - `<input type="checkbox" id="privacyAck">`와 `<label for="privacyAck">`를 명시적으로 연결하고 키보드(Tab, Space)로 조작 가능하도록 구성하였습니다.
  - 미체크 시 안내 문구는 `role="status" aria-live="polite"` 속성이 적용된 `#privacyAckError` 영역에 출력되어 스크린 리더로 전달됩니다.
- **업로드 차단 및 상태 기억 (`apps/web/static/app.js`)**:
  - 파일 선택(`#fileInput`) 및 드래그 앤 드롭(`#dropArea`) 시도시 체크 여부를 사전 검증(`checkPrivacyAck()`)하여, 체크되지 않은 경우 업로드를 즉시 중단하고 오류 메시지 표시 및 체크박스로 포커스를 이동합니다.
  - 체크 상태는 `sessionStorage`를 통해 프로젝트/세션 단위로 기억되며, 사용자가 페이지를 이동하거나 다시 돌아왔을 때도 체크 상태를 시각적으로 확인할 수 있습니다.
  - 파일 업로드 멀티파트 요청 시 `privacy_ack=true` 필드를 함께 전송합니다.

### 2) 서버 측 확인 및 API 우회 차단 (`apps/api/routers/projects.py`)
- **폼 필드 검증**:
  - `POST /api/projects/{project_id}/documents` 엔드포인트에서 `privacy_ack: bool = Form(False)`를 수신합니다.
  - 값이 없거나 `False`인 경우 HTTP 422 (`PRIVACY_ACK_REQUIRED`) 상태 코드와 함께 화면과 동일한 거절 사유("연락처·주민등록번호 외의 개인정보를 직접 처리했음을 확인해야 업로드할 수 있습니다.")를 반환하여 API 직접 호출을 통한 우회를 원천 차단합니다.

### 3) 감사 기록(Audit) (`apps/api/routers/projects.py`)
- 업로드 성공 시 `AuditEventType.UPLOAD` 메타데이터 및 `AuditEventType.USER_OVERRIDE` 감사 이벤트를 함께 발행합니다.
- 감사 페이로드: 사용자(`actor`), 프로젝트 ID, 문서 ID, 시각, 안내문 판(`notice_version: "1.0"`), 확인 여부(`privacy_ack: true`)를 기록합니다.
- **원문 개인정보 보호**: 본문 내용이나 개인정보 원문은 일체 감사 기록에 남기지 않습니다.

### 4) 보고서 머리 표시
- **웹 보고서 화면 (`apps/web/index.html`)**: 보고서 탭 머리글 및 다운로드 영역 상단에 안내 배너(`.report-privacy-notice`)를 표시합니다.
- **PDF 보고서 (`packages/report_engine/pdf_report.py`)**: 표지 및 1. 검증개요 표 상단에 "개인정보 보장 범위: 연락처·주민등록번호 자동 가림 보장, 그 밖의 개인정보는 사용자 처리"를 명시합니다.
- **Word(DOCX) 보고서 (`packages/report_engine/docx_report.py`)**: 문서 상단 개요 첫 단락에 동일한 보장 범위 안내 문구를 명시합니다.

### 5) 안내문 판(Version) 관리 (`packages/common/privacy_notice.py`)
- 안내 문구, 체크박스 라벨, 에러 메시지, 보고서 머리 표시 문구 및 버전 상수(`PRIVACY_NOTICE_VERSION = "1.0"`)를 단일 모듈에서 중앙 관리합니다.

---

## 2. 변경 파일 및 Diff Stat

기준 커밋 `a04826f` 대비 변경 내역:

```
 apps/api/routers/projects.py                     |  25 ++-
 apps/web/index.html                              |   4 +-
 apps/web/static/app.js                           |  61 ++++++++
 apps/web/static/styles.css                       |  63 ++++++++
 docs/handoff/requests/38_upload_notice_design.md |  70 +++++++++
 packages/common/privacy_notice.py                |  29 ++++
 packages/report_engine/docx_report.py            |   2 +
 packages/report_engine/pdf_report.py             |   3 +
 tests/test_upload_privacy_notice_api.py          | 175 +++++++++++++++++++++
 tests/test_upload_privacy_notice_browser.py      | 190 +++++++++++++++++++++++
 10 files changed, 619 insertions(+), 3 deletions(-)
```

- **제약 준수 확인**:
  - `packages/pii_engine/`, `packages/llm_router/privacy.py` (Codex 8F 작업 대상) 일체 수정 없음.
  - 보호 경로(`tests/acceptance/**`, `scripts/**`, `docs/scorecards/**`) 일체 수정 없음.
  - 기존 시험 삭제/수정 없음.

---

## 3. 신규 시험 결과 (100% 통과)

신규 작성된 API 및 브라우저 시험은 완전히 새로운 합성 입력을 사용하여 작성되었으며, 모두 정상 통과하였습니다.

### 1) API 신규 시험 (`tests/test_upload_privacy_notice_api.py`) — 3 passed
- `test_upload_without_privacy_ack_rejected_422`: 확인 체크 없이 업로드 시 422 거절 및 미저장 검증
- `test_upload_with_privacy_ack_succeeds_201_and_audited`: 확인 체크 시 201 성공 및 감사 기록(`notice_version`, `privacy_ack` 포함, 원문 개인정보 없음) 검증
- `test_audit_log_contains_no_case_raw_pii`: 감사 기록에 원문 개인정보가 일체 포함되지 않음을 검증

```
tests/test_upload_privacy_notice_api.py ... [100%]
3 passed in 11.79s
```

### 2) 브라우저 신규 시험 (`tests/test_upload_privacy_notice_browser.py`) — 4 passed
- `test_privacy_notice_visible_and_accessible`: 상시 안내문 3대 문구 노출 및 접근성(aria-live, label) 검증
- `test_upload_blocked_without_privacy_ack`: 체크박스 미체크 상태에서 파일 선택 차단 및 에러 메시지 표시 검증
- `test_upload_proceeds_with_privacy_ack_and_persists`: 체크 후 파일 업로드 성공 및 세션 스토리지 기억 기능 검증
- `test_report_header_shows_guarantee_scope`: 보고서 패널 머리에 개인정보 보장 범위 문구 노출 검증

```
tests/test_upload_privacy_notice_browser.py .... [100%]
4 passed in 38.24s
```

---

## 4. 기존 시험 영향 및 평가 측 인계 사항

지시서 2절 제약사항:
> *"기존 브라우저 시험 197건이 그대로 통과해야 한다. 기존 업로드 시험이 확인 값 없이 업로드하는 경우, 시험을 고치지 말고 평가 측에 알린다. 평가 측이 보호 시험 갱신 여부를 정한다."*

### 1) 기존 업로드 시험 관련 인계
- 서버 API가 `privacy_ack` 누락 시 422로 거절하고 화면에서 미체크 업로드를 차단함에 따라, `privacy_ack` 없이 직접 업로드를 시도하는 기존 업로드 테스트들이 실패하게 됩니다:
  - 브라우저 시험: `tests/test_frontend_upload.py` (7건) — 미체크 상태에서 파일 투입하여 업로드 진행이 차단됨. (브라우저 시험 197건 중 업로드 외 190건은 정상 통과)
  - 단위/통합 시험: `tests/test_api.py`, `tests/test_upload_resilience.py`, `tests/test_user_management.py` 등의 업로드 관련 테스트 케이스.
- **조치**: 지시서 지침에 따라 구현 에이전트는 기존 보호 시험을 임의로 수정하거나 xfail 처리하지 않았으며, 평가 측(claude-code)에서 보호 시험 갱신(테스트 픽스처/요청에 `privacy_ack=True` 또는 체크 조작 추가) 여부를 판단하여 처리할 수 있도록 인계합니다.

### 2) Windows 로컬 실행 환경과 CI 환경 차이
- **실행 환경**: Windows 11, Python 3.14.6, Tesseract 미설치(None), Google Chrome 채널 (`LV_TEST_BROWSER_CHANNEL="chrome"`).
- **영향**:
  - `environment`: Python 버전 불일치 및 Tesseract 부재로 인해 `--allow-env-mismatch` 옵션 필요.
  - OCR 관련 테스트(`tests/test_ocr_readiness.py`)는 로컬 Tesseract 부재로 실패 (CI Linux tesseract 5.3.4 환경에서는 정상).
  - 콘솔 인코딩: Windows 기본 cp949 인코딩으로 인해 `verify_all.py` 및 일부 진단 도구의 em-dash(`\u2014`) 콘솔 print 시 `UnicodeEncodeError` 발생 (CI Linux UTF-8 환경에서는 영향 없음).
  - `score_gate`: 점수 게이트 자체는 통과(`향상: [dev] 종합 79.9 → 81.7`, `향상: [holdout] 종합 77.3 → 79.2`, 점수 게이트 통과).

---

## 5. `verify_all.py` 전체 실행 결과 (`artifacts/verify_all.json`)

명령: `$env:LV_TEST_BROWSER_CHANNEL = "chrome"; python scripts/verify_all.py --base upstream/Steve_ACASiaLAW --allow-env-mismatch`

```json
{
 "head": "7ea64d0",
 "base": "upstream/Steve_ACASiaLAW",
 "env": {
  "python": "3.14.6",
  "os": "Windows-11-10.0.26340-SP0",
  "tesseract": null,
  "matches_ci": false
 },
 "steps": {
  "environment": {
   "ok": true,
   "matches_ci": false,
   "tail": [
    "python 3.14.6, tesseract None — CI와 다름 (--allow-env-mismatch)"
   ]
  },
  "acceptance": {
   "passed": 868,
   "strict_xpass": 0,
   "seconds": 584.7
  },
  "regression_ledger": {
   "passed": 224,
   "real_failures": [],
   "strict_xpass": 0,
   "ok": true,
   "seconds": 27.5
  },
  "score_gate": {
   "code": 0,
   "tail": [
    "향상: [dev] 종합 79.9 → 81.7  (기준선 갱신은 평가 에이전트가 요청하고 사용자가 승인한다)",
    "향상: [holdout] 종합 77.3 → 79.2  (기준선 갱신은 평가 에이전트가 요청하고 사용자가 승인한다)",
    "점수 게이트 통과"
   ],
   "seconds": 0.6
  },
  "full_tests": {
   "passed": 2883,
   "seconds": 616.9
  },
  "browser_tests": {
   "passed": 190,
   "real_failures": [
    "tests/test_frontend_upload.py::test_registration_outcome_and_no_blind_post_retry[success-REGISTERED] (call)",
    "tests/test_frontend_upload.py::test_registration_outcome_and_no_blind_post_retry[lost_saved-REGISTERED] (call)",
    "tests/test_frontend_upload.py::test_registration_outcome_and_no_blind_post_retry[network-UNCONFIRMED] (call)",
    "tests/test_frontend_upload.py::test_registration_outcome_and_no_blind_post_retry[bad_json-UNCONFIRMED] (call)",
    "tests/test_frontend_upload.py::test_registration_outcome_and_no_blind_post_retry[http_error-UNCONFIRMED] (call)",
    "tests/test_frontend_upload.py::test_unreadable_local_file_is_not_sent (call)",
    "tests/test_frontend_upload.py::test_upload_status_responsive_and_project_scoped (call)"
   ],
   "seconds": 917.7
  }
 },
 "mode": "full"
}
```

---

## 6. 결론 및 PR 대상 안내

- 구현 목표인 업로드 전 개인정보 안내, 필수 확인 체크박스(접근성 준수 및 기억), 서버 측 422 거절 검증, 원문 배제 감사 기록, 보고서 머리 표시 및 판 관리가 모두 완료되었습니다.
- 신규 API 및 브라우저 테스트 7건 모두 정상 통과되었습니다.
- 변경 내역은 `Steve_ACASiaLAW` 브랜치를 대상으로 PR을 생성하여 평가 측 승인 및 CI 검증을 진행할 준비가 되었습니다.
