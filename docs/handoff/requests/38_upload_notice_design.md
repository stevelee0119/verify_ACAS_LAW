# 설계 메모: 업로드 개인정보 안내·확인 및 보장 범위 명시 (38_upload_notice_design)

작성: Antigravity (구현 에이전트)  
일자: 2026-10-04  
근거: 사용자 결정(2026-10-04, handoff README), TK-56 3절, TK-57

---

## 1. 배경 및 원칙
- **정책**: 시스템 자동 마스킹은 연락처와 주민등록번호만 보장하며, 성명·주소 등 그 밖의 개인정보는 사용자가 업로드 전에 직접 가려야 한다.
- **방향**: 업로드 전 상시 안내 및 필수 확인 체크박스를 도입하고, 서버 측 검증(422)으로 API 우회를 차단하며, 확인 사실을 감사 기록에 남기고 보고서 머리에 보장 범위를 표시한다.

---

## 2. 안내문 문구 및 판(Version) 관리
- **관리 위치**: `packages/common/privacy_notice.py` (설정 상수)
- **판 번호**: `PRIVACY_NOTICE_VERSION = "1.0"` (문구 변경 시 상향)
- **상시 안내문 문구** (사용자 검토 대상):
  1. "자동으로 가리는 개인정보는 연락처와 주민등록번호뿐입니다."
  2. "성명·주소 등 그 밖의 개인정보는 업로드 전에 직접 가려 주세요."
  3. "성명 등 자동 가림은 보조 기능이며 모두 가려진다고 보장하지 않습니다."
- **확인 체크박스 문구**: "연락처·주민등록번호 외의 개인정보를 직접 처리했습니다"
- **보고서 머리 표시 문구**: "연락처·주민등록번호 자동 가림 보장, 그 밖의 개인정보는 사용자 처리"

---

## 3. 화면 흐름 및 접근성 (`apps/web/`)
1. **자료 패널 UI (`apps/web/index.html`)**:
   - '파일 추가' 버튼 인접 영역에 상시 보이는 안내 배너(`.privacy-notice`)를 배치.
   - 체크박스 (`#privacyAck`)와 라벨(`<label for="privacyAck">`)을 명시적으로 연결하고 키보드 포커스 가능하도록 구성.
   - 거절 사유 알림을 화면 낭독기가 읽을 수 있도록 `role="status"` 및 `aria-live="polite"` 안내 영역 제공.
2. **업로드 인터랙션 (`apps/web/static/app.js`)**:
   - 체크 상태는 세션(`sessionStorage`) 및 프로젝트 단위로 기억하되, 화면에 체크 상태를 표시하여 언제든 다시 볼 수 있게 함.
   - 파일 선택(`#fileInput`) 및 끌어 놓기(`#dropArea`) 시도시 체크 여부 검사:
     - 미체크 시: 업로드 작업을 중단하고, 안내 영역 및 토스트로 이유를 설명하며 체크박스로 포커스 이동.
     - 체크 시: `privacy_ack=true` 필드를 포함하여 서버로 멀티파트 전송.

---

## 4. API 계약 (`apps/api/routers/projects.py`)
- **엔드포인트**: `POST /api/projects/{project_id}/documents`
- **요청 폼 필드 추가**: `privacy_ack: bool = Form(False)`
- **검증 규칙**:
  - `privacy_ack`가 없거나 거짓(`False`)인 경우:
    - HTTP 422 Unprocessable Entity 반환.
    - 응답 본문: `{"code": "PRIVACY_ACK_REQUIRED", "message": "연락처·주민등록번호 외의 개인정보를 직접 처리했음을 확인해야 업로드할 수 있습니다."}`
    - 화면을 거치지 않는 API 직접 호출 우회 차단.

---

## 5. 감사 기록(Audit) 명세 (`packages/audit_engine`)
- **기록 시점**: 업로드 저장 완료 시점(`_store_document`).
- **기록 이벤트**: `AuditEventType.UPLOAD` 메타데이터 및 `AuditEventType.USER_OVERRIDE`.
- **기록 필드**:
  - `actor`: 업로드 사용자 식별자 (`actor_id()`)
  - `project_id`: 대상 프로젝트 ID
  - `document_id`: 등록된 문서 ID
  - `created_at`: 기록 시각 (UTC)
  - `payload`:
    - `privacy_ack`: `True`
    - `notice_version`: `PRIVACY_NOTICE_VERSION`
    - `notice_acknowledged_at`: ISO 8601 UTC 타임스탬프
  - **원문 개인정보 배제**: 서면 본문이나 개인정보 원문은 일체 감사 기록에 남기지 않음.

---

## 6. 보고서 머리 표시 (`packages/report_engine/`, 웹 보고서 화면)
- **웹 화면**: 보고서 패널 머리글 및 다운로드 영역 상단에 보장 범위 안내 문구 표시.
- **PDF 보고서 (`pdf_report.py`)**: 표지 / 1. 검증개요 표에 "개인정보 보장 범위" 항목으로 "연락처·주민등록번호 자동 가림 보장, 그 밖의 개인정보는 사용자 처리" 명시.
- **Word 보고서 (`docx_report.py`)**: 보고서 개요 상단에 동일 보장 범위 안내 문구 명시.
