# TK-25 AI 판정 축 scope 정상화 보고 및 커버리지 개선 제안

- 유형: 정책 이행 보고 및 선택 개선 제안
- 기준 커밋: S5 (TK-25 해결 반영)
- 작성: 구현 에이전트 (Antigravity) 2026-10-01
- 관련 티켓: docs/handoff/TK-25_report_scope_and_coverage_notes.md

---

## 1. AI 판정 축 `scope` 표시 정상화 완료 (TK-18 잔여 이행)

### 현상 및 원인
- 서면9 온라인 보고서에서 `verdict=AI_FULL_GENERATION_LIKELY` (다수결 `MAJORITY_AI_CONSENSUS`), `involvement=NO_OBJECTIVE_TRACES`임에도 불구하고 `scope=NOT_APPLICABLE`로 표시되는 불일치 발생.
- `packages/verification_engine/scoring.py`의 `unified_authorship` 함수에서 `scope` 결정식이 `if traces`에 종속되어 있어 객관적 흔적이 0건이면 무조건 `NOT_APPLICABLE`로 무효화되었음.

### 해결 내용
- `packages/verification_engine/scoring.py`:
  - `scope`와 `involvement` 판정 축을 독립 분리:
    - `scope`: `verdict`에 따라 결정 (`AI_FULL_GENERATION_LIKELY` -> `WHOLE_DOCUMENT`, `AI_PARTIAL_GENERATION` -> `PART_OF_DOCUMENT`, `HUMAN_AUTHORED_LIKELY`/`UNCERTAIN` -> `NOT_APPLICABLE`, 그 외 -> `UNDETERMINED`).
    - `involvement`: 객관적 흔적 유무에만 따름 (`traces` 존재 시 `TRACES_FOUND`, 부재 시 `NO_OBJECTIVE_TRACES`).
- 검증 및 회귀 시험:
  - `tests/acceptance/test_ai_majority_rule.py`: 22건 전건 통과 확인.
  - `tests/regression/test_ledger.py`: TK-25 양성 3건, 대조군 3건 추가 완료 (총 64건 회귀 시험 통과).

---

## 2. 관찰 사항 및 커버리지 개선 제안 (평가/운영 검토 요청)

### (1) 동일 시행일 복수 법령 버전 처리 (인용 검증 커버리지 향상)
- **현상**: `legal_history.select_version`에서 동일 시행일을 공유하는 법령 버전이 2건 이상인 경우 `ValueError("Multiple versions share the requested effective boundary")`를 발생시켜 안전하게 미검증(INFO) 처리됨 (예: 국가재정법 제96조).
- **영향**: 안전한 안전장치로 동작하지만 유효한 법령 조문에 대한 검증 커버리지 손실 발생.
- **개선 제안**:
  1. 공포일(promulgation date) 또는 개정 번호가 최신인 버전을 우선 선택.
  2. 또는 보고서에 두 버전을 병기하여 "동일 시행일 복수 개정본 존재" 사실과 함께 두 버전의 조문 일치 여부를 모두 표시.

### (2) 모델 응답 한도(Truncation) 및 스키마 위반 복구
- **현상**: LLM 기반 검증 호출 12건 중 2건 실패 관찰 (Anthropic 4000토큰 출력 한도 초과 Truncation, OpenAI 최상위 required 필드 누락에 따른 `INVALID_RESPONSE_SCHEMA`).
- **영향**: 예비 공급자 및 재시도로 최종 실행은 `PARTIAL_COMPLETED`로 완료되었으나 지연 시간 및 리소스 소모 증가.
- **개선 제안**:
  1. 서면 본문 길이가 긴 경우 문단 단위 청크 분할 호출 적용.
  2. 스키마 위반 발생 시 부분 JSON 파싱 복구기(repair) 연동 및 해당 실패 필드 대상 초점 재요청 로직 도입.
