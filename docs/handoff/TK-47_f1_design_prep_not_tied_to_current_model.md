# TK-47 F1 설계 준비 문서(R6)가 현행 FindingType·워크플로 모델과 연결되지 않음 (P2, 산출물 미완)
- 유형: 산출물 미완(문서, P2) · 기준: 7차 최종 4da3910 `docs/handoff/requests/22_f1_design_prep.md` · 작성: evaluator 2026-10-03 · 근거: 독립 감사 Astra A7-04 + 평가 측 재현([AUDIT_REVIEW_ROUND7](AUDIT_REVIEW_ROUND7.md))
- 코드·DB·API를 바꾸지 않은 제한은 지켰다. 문제는 **요청한 선행 설계가 현행 모델에서 출발하지 않았다**는 것이다(신규 테이블·필드를 구현하라는 뜻이 아니다).

## 증거(평가 측 재현)
- `packages/common/enums.py`의 `FindingType`은 **97개**. 문서가 '7종 화면 배정안'에 쓴 `TIMELINE_DISCREPANCY`·`TEMPORAL_STATUTORY_PERIOD`·`OVERCLAIM_WITHOUT_REQUIREMENTS`·`UNREASONABLE_ARGUMENT`·`REFERENCE_MISMATCH`·`REFERENCE_MISSING`·`PII_UNMASKED_CANDIDATE`는 **enum 이름·값 어디에도 없다(0/7)**. 현행 목록 대응 0/97.
- 문서가 제시한 `finding_reviews`·`reviewer_status`·`version`·`FindingRow`는 현행과 다르다. 현행은 `apps/api/workspace.py`의 `FindingWorkflow`(`finding_workflows`: `workflow_state`·`decision`·`priority`·`assignee`·`note`·`revision`)·`ReviewDraft`·`ReviewRevision`과 기존 `/workflow` API다(`migrations/versions/20260918_d14ac2_review_workspace.py`).
- 빠진 것: 기존 필드·revision·검토 이력을 보존하는 비교안, 기존 JSON ↔ 실제 화면 대응, 모든 타입의 미배정 검출 시험 제안, F3 청구 단위 검색·대조의 호출 수·상한·예산 초과·실패 처리, 현행 클래스·함수(`detect()`·`PIIEngine` 마스킹·`inspect_request`·`LLMRouter.run`)와의 정확한 연결(※ 평가 측 초판이 `PIIDetector`로 적은 것은 평가 측 오기 — 코드에 없는 이름), `LOCAL_ONLY` 외부 호출 0 시험 위치. 참고자료 원문 열람 분기(`ADMIN`)는 지시서가 요구하지 않은 새 권한 설계다.

## 요구(보완 지시서 R7-F)
현행 코드에서 출발해 문서를 다시 쓴다: ① `FindingType` 97개 전수 목록과 화면 배정(미배정 시 실패하는 시험 제안) ② 기존 JSON·화면 필드 대응과 보존 경로 ③ 검토 상태 저장 비교(현행 `FindingWorkflow` 확장 vs 별도 모델, 기존 revision·이력 보존) ④ F3 호출 수·상한·캐시·중복 제거·실패·예산 초과 처리 ⑤ 참고자료 발췌가 현행 마스킹·전송 전 검사·라우터 경로를 그대로 지나는 정확한 클래스·함수·입력 필드 ⑥ `LOCAL_ONLY` 시험 위치 제안. 새 원문 열람 권한을 임의로 설계하지 않는다.

## 수용
평가 측과 독립 감사가 문서의 모든 타입 이름이 현행 enum에 있고 모든 모델·경로가 현행 코드에 있음을 대조로 확인한다(F1 착수 판정 때 함께 검토).

## 9506481 재측정(2026-10-03, 7차 보완 R7-F)
재작성본(`22_f1_design_prep.md`)은 `FindingWorkflow`·`ReviewDraft`·`ReviewRevision`을 인용하고 가공 모델(`finding_reviews`)을 걷어냈으나 **다음이 남았다**(평가 측 코드 대조): ① 1절의 타입 이름 85개 중 **83개만 enum에 있고** `OVERCLAIM_WITHOUT_REQUIREMENTS`·`PII_UNMASKED_CANDIDATE` 2개는 **없다**; 패널별 목록은 '예시'·'등'으로 끝나 enum 97개 중 **14개가 언급되지 않는다**(전수 목록 아님) ② 3절 상태값 `UNREVIEWED·CONFIRMED·DISMISSED·ESCALATED`는 `apps/api/workspace.py`에 없다(현행 `workflow_state`는 `NOT_STARTED`…, `decision`은 `UNDECIDED`…) ③ `PIIDetector`·`anonymize_text`는 코드에 없는 이름이다(탐지는 `packages/pii_engine/detector.py`의 `detect()`, 전송 전 검사는 `packages/llm_router/privacy.py`의 `inspect_request`) ④ `tests/acceptance/test_llm_router_local_only.py`는 존재하지 않는 파일이다 ⑤ 프런트엔드를 `React/Vue`라 썼으나 현행은 순수 JS(`apps/web/static/*.js`) ⑥ F3 설계는 호출 수 `N회(예: 3회)`·Redis LRU 등 현행 코드 근거 없는 가정이다. 요구는 그대로(현행 코드 대조로 모든 이름 실재 확인).
