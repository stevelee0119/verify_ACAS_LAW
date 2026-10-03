# F1 착수 기준 합의 및 화면·참고자료 통합 설계 준비 (R6)

- 작성: 구현 담당 에이전트 (Antigravity)
- 날짜: 2026-10-03
- 목적: 7차 작업 지시서 R6에 따른 F1 착수 게이트 합의 및 F1(화면 중복 해소·검토 항목 통합·참고자료 부합성) 기술 설계 선행 준비

---

## 1. F1 구현 착수 기준(G1~G10)에 대한 구현 측 확인 및 합의

구현 측은 지시서 2절에 명시된 F1 착수 기준 및 원칙에 전적으로 동의하며, 다음과 같이 확인합니다:

1. **착수 순서 준수**:
   - 사용자 결정(2026-10-03)에 따라 작업 순서는 `7차 안정화` → `행위시법 검토 보강(요청 16 + TK-34)` → `F1(화면·참고자료 기능 라운드)` → `TK-24(소멸시효 배제)` 순서로 진행됨을 확인합니다.
2. **평가 측·독립 감사 고유 소관 존중**:
   - G1~G10 게이트의 충족 판정은 오직 평가 측의 실측과 독립 감사의 검증, 그리고 최종 사용자의 승인에 의해서만 결정되며, 구현 측은 자체 보고서로 게이트 충족을 단독 선언하지 않습니다.
3. **게이트 기준 준수 합의**:
   - **G1 (회귀 0)**: 6차 회귀 시험(`test_round6_regressions.py`) 전체 XPASS 및 기존 시험 새 실패 0.
   - **G2 (개인정보 경계)**: 이름 1,000조합 보존, 라우터 경계 가짜 공급자 호출 0회, 비공개 변형 ≥95%(F3 착수 시 ≥98%), 정상 문장 PERSON 오탐 0.
   - **G3 (법리)**: 요건 부정 자인 및 타 책임 확장 경고 유지, 정상 한정 항변 오탐 0.
   - **G4 (문단 복원)**: 양방향 줄 결합 및 문단 배치 불변성 보장.
   - **G5 (점수 유지)**: dev ≥ 81.7, holdout ≥ 79.2, 오탐 0, A등급 0, 인젝션 방어 유지.
   - **G6 (CI 초록)**: 점수 게이트, CI test job, Docker OCR readiness 모두 성공.
   - **G7 (보안 보강)**: 보안 시험 11건 XPASS, 정규식 지수 증가 0건, 조작 입력 < 1초.
   - **G8 (독립 재검증)**: 독립 감사 신규 P1 0건.
   - **G9 (보고 투명성)**: 모든 job 단계 성공/실패/건너뜀 완전 공개.
   - **G10 (평가 도구)**: 평가 측 비공개 변형 및 라우터 경계 확장 시험 구비.

---

## 2. 화면 필드 — API 모델 — DB 스키마 1:1 대응표

F1에서 구현될 검토 항목 상태 저장 및 표시를 위한 각 계층 간 필드 매핑 설계입니다.

| 화면 필드 (UI) | API 요청/응답 모델 (`FindingReviewUpdate` / `FindingReviewResponse`) | DB 스키마 (`FindingRow` / `finding_reviews` 테이블) | 데이터 타입 / 제약 | 설명 및 비고 |
|---|---|---|---|---|
| `finding_id` | `finding_id: str` | `finding_id: String(64), PrimaryKey/FK` | UUID v4 / Not Null | 진단 결과 고유 식별자 |
| `project_id` | (URL Path 파라미터) | `project_id: String(64), FK` | UUID v4 / Not Null | 프로젝트 격리 스코프 |
| `reviewer_status` | `reviewer_status: ReviewStatus` | `reviewer_status: Enum(ReviewStatus)` | `UNREVIEWED`, `CONFIRMED`, `DISMISSED`, `ESCALATED` | 검토자 판정 상태 (기본값: UNREVIEWED) |
| `comment` | `comment: Optional[str]` | `comment: Text` | 최대 2,000자, Nullable | 검토자 메모/사유 (XSS 방지 텍스트 정규화) |
| `reviewer_id` | `reviewer_id: str` (서버 주입) | `reviewer_id: String(64)` | Not Null (Principal.user_id) | 최종 검토 작업자 ID (클라이언트 위조 불가) |
| `version` | `version: int` | `version: Integer` | Not Null, Default 1 | 낙관적 잠금(Optimistic Locking) 동시성 제어용 |
| `modified_at` | `modified_at: datetime` | `modified_at: DateTime(timezone=True)` | Not Null, Server UTC Now | 최종 수정 일시 |
| `created_at` | `created_at: datetime` | `created_at: DateTime(timezone=True)` | Not Null, Server UTC Now | 최초 검토 일시 |

---

## 3. FindingType 7종 검토 화면 배정안

화면 상의 혼선과 중복을 해소하기 위해 7종의 `FindingType`을 3개의 탭/패널에 명확히 분류하고 시각화 뱃지를 정의합니다.

| FindingType | 소속 패널/탭 | 뱃지 라벨 | 시각 스타일 (색상/아이콘) | 표시 정보 및 사용자 조치 |
|---|---|---|---|---|
| `TIMELINE_DISCREPANCY` | 시간축 / 날짜 검토 | 날짜 모순 | 붉은색 경고 (`text-rose-600`, `alert-triangle`) | 서면 내 일자 간 모순, 증거서류 일자 불일치 |
| `TEMPORAL_STATUTORY_PERIOD` | 시간축 / 소멸시효 | 제척·시효 검토 | 주황색 주의 (`text-amber-600`, `calendar-x`) | 소멸시효 경과 가능성 및 기산점 확인 요청 |
| `OVERCLAIM_WITHOUT_REQUIREMENTS` | 법리 / 항변 검토 | 요건 미소명 | 보라색 안내 (`text-purple-600`, `scale`) | 요건 부정 자인, 타 책임 확장, 소명 없는 단정 |
| `UNREASONABLE_ARGUMENT` | 법리 / 항변 검토 | 무리한 법리 | 자주색 경고 (`text-fuchsia-600`, `shield-alert`) | 공금 유용에 긴급피난 원용 등 성립 불가 주장 |
| `REFERENCE_MISMATCH` | 참고자료 부합성 | 참고자료 불일치 | 노란색 주의 (`text-yellow-600`, `file-diff`) | 인용 조문·판례와 서면 기재 문구 간 불일치 |
| `REFERENCE_MISSING` | 참고자료 부합성 | 인용 출처 누락 | 회색 안내 (`text-zinc-500`, `file-question`) | 서면에서 인용한 판례/조문의 출처 미비 |
| `PII_UNMASKED_CANDIDATE` | 개인정보 보호 | 개인정보 잔존 | 빨간색 위험 (`text-red-700`, `eye-off`) | 마스킹되지 않은 성명·식별자 후보 발견 |

---

## 4. 동시 수정 충돌(409) 및 낙관적 잠금(Optimistic Locking) 처리 방안

복수의 검토자가 동일한 사건 서면을 검토할 때 발생할 수 있는 덮어쓰기(Lost Update)를 방지하는 설계입니다.

1. **DB 레벨 낙관적 잠금 메커니즘**:
   - `finding_reviews` 테이블에 `version` (정수형) 컬럼을 유지합니다.
   - 클라이언트는 수정 요청(`PUT /api/projects/{p_id}/findings/{f_id}/review`) 시 자신이 마지막으로 조회했던 `version` 값을 본문에 실어 전송합니다.
   - UPDATE 쿼리:
     ```sql
     UPDATE finding_reviews
     SET reviewer_status = :status,
         comment = :comment,
         reviewer_id = :user_id,
         version = version + 1,
         modified_at = NOW()
     WHERE finding_id = :f_id AND version = :client_version;
     ```
   - 갱신된 행의 수(`rowcount`)가 0이면 다른 검토자가 이미 먼저 수정한 상태이므로 트랜잭션을 롤백하고 `409 Conflict` 예외를 발생시킵니다.
2. **API 응답 및 HTTP 409 처리 규격**:
   ```json
   {
     "detail": {
       "message": "다른 검토자가 이미 검토 내용을 수정했습니다. 최신 내용을 확인 후 다시 시도해주세요.",
       "code": "REVIEW_CONFLICT",
       "current_version": 3,
       "current_reviewer_id": "reviewer_b",
       "current_status": "CONFIRMED",
       "current_comment": "소명 자료 확인 완료하여 수용함."
     }
   }
   ```
3. **UI 단 충돌 해결 UX**:
   - 409 응답 수신 시 토스트 알림으로 충돌 사실을 안내합니다.
   - 검토 패널 상단에 "다른 사용자의 최신 수정 내역"과 "내 수정 시도 내용"을 나란히 표시하여 검토자가 차이점을 확인하고 다시 반영할 수 있는 인터페이스를 제공합니다.

---

## 5. 참고자료 발췌 시 마스킹 경로 및 권한 분기 설계

F3에서 도입될 참고자료(조문, 판결문 등) 발췌 텍스트의 외부 모델 전송 및 화면 노출 시 정보보안 요구사항을 만족하는 경로 설계입니다.

1. **발췌 텍스트 마스킹 파이프라인 (불변 원칙)**:
   - 참고자료 DB(`legal_references` 또는 외부 조회 결과)에서 서면 대비용으로 텍스트를 발췌할 때, 반드시 제품 내 `PIIDetector` 및 마스킹 파이프라인(`anonymize_text`)을 통과한 후 캐시/저장됩니다.
   - 외부 LLM 라우터(`LLMRouter.run`)로 전송되는 모든 프롬프트는 전송 직전 `inspect_request`를 강제하여 미마스킹 토큰이 포함된 경우 외부 네트워크 전송을 즉시 차단(Fail-closed)합니다.
2. **화면 노출 시 권한 분기 (원문 대조 모드)**:
   - **기본 열람 모드 (일반 검토자/MEMBER/VIEWER)**:
     * 화면에는 항상 가명화(마스킹)된 발췌문(`홍○○`, `OO부대`)만 표시됩니다.
   - **원문 대조 모드 (ADMIN 또는 사건 담당 변호사)**:
     * 사건 실무상 정밀한 조문/판례 대조를 위해 실명 원문 확인이 필요한 경우, `권한 검증(Principal.role == 'ADMIN')` 및 `보안 감사 로그(AuditEventType.UNMASK_VIEW)`를 DB에 필수 기록한 뒤에만 별도 모달에서 일시적으로 원문을 표시합니다.
     * 원문 대조 화면은 브라우저 세션 스토리지에만 존재하며, 복사/외부 내보내기 시에는 자동으로 마스킹된 텍스트가 적용됩니다.
   - **`LOCAL_ONLY` 격리**:
     * 외부 클라우드 공급자 연동 없이 순수 온프레미스/로컬 모델만 사용하는 환경에서는 외부 전송 시도 자체가 0회(소켓 미생성)로 격리됩니다.
