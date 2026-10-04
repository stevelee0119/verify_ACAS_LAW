# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-04 평가 측. 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-04]

0. 시작: 작업 브랜치마다 `git fetch origin evaluator/round8-promotion && git merge origin/evaluator/round8-promotion`(병합 커밋, 리베이스·강제 푸시 금지).
   규칙(AGENTS.md): 커밋 전에는 바꾼 부분의 시험만 돌린다. 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').

[A] PR #11 업로드 안내 — 수용 완료(41faa2e). 할 일 없음.

[B] PR #13 F1 보완 — 브랜치 antigravity/f1-review-screen
 1) app.js의 AI_SECURITY_FINDING_TYPES·SECURITY_CARD_FINDING_TYPES 하드코딩을 지우고 /api/finding-categories 응답으로 분류한다.
    받지 못하면 모든 항목을 '확인할 항목'에 표시(정보 손실 0)하고 AI 탭에 오류를 안내한다.
 2) '주요 참고문헌 검토(RAG)'·'추가 관련 법조문 검토'를 renderAIVerification()에서 빼서 '확인할 항목' 임시 섹션으로 옮긴다.
 3) 기존 브라우저 시험 갱신(평가 측 승인, 찾는 위치만): test_drive_rag_relevance.py, test_frontend_citation_groups.py,
    test_frontend_model_opinions.py, test_reasoning_layout.py 등 위 섹션·인용표(#aiVerificationRows)를 AI 탭에서 찾던 시험은
    탭 전환(switchTab('review') 등)·locator만 바꾼다. 내용 단언 변경·삭제·표시 추가 금지.
 4) 평가 측 보호 시험 tests/acceptance/test_f1_protected.py(T1~T5)가 통과해야 한다(특히 T4 두 건). 시험 파일은 수정하지 않는다.
 5) 보고 정정: 40_f1_completion.md와 19b 4.1의 배정 수치를 코드 기준으로 고친다
    — AI·보안 47(AI 진단 5·인젝션 17·보안 25) / 검토 50(사실 27·법률 인용 11·MM4 5·시간축 4·처리 3).
    없는 범주(CASE_SPECIFIC·PSEUDONYMIZATION 등)와 'RAG 완전 제거' 문장을 바로잡는다.
 6) 19b 정정(F2·FT 착수 전):
    - 7.5 없는 rule_id(AMBIGUOUS_LAW_VERSION·OUTDATED_PROVISION_CITED) 삭제. 새 rule_id(SUB_PROVISION_AMENDMENT·FT_MULTI_VERSION_AMBIGUITY)는 docs/handoff/requests/ 요청서로 승인받는다.
    - 7.3 판정 기준: 개정 성격만으로 HIGH 금지. '인용한 목의 문언이 행위 당시 시행본과 맞는가'로 판정하고, 두 버전 결과가 갈리면 확인 요청.
    - 6.1 inspect_request는 요청 전체를 지금처럼 검사하고, 키 허용 목록은 그 앞의 추가 관문으로 둔다.
    - 경로: 검토 상태 API는 /api/findings/{finding_id}/workflow, 모델 지적 생성은 packages/verification_engine/ai_document_detector.py.
 7) 로컬: 바꾼 파일의 시험과 tests/acceptance/test_f1_protected.py만 돌린다. 푸시 뒤 PR #13에 '검토 요청'.

[C] F2 — 아직 착수하지 않는다. [B] 수용 뒤 평가 측이 착수를 알린다.
```
