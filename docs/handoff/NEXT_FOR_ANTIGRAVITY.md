# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-08 평가 측(TK-63 개정 1: 사용자 결정 (나)안). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-08 (27)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').

[A] F1·F2·TK-61·FT·F3 — 모두 병합·배포 완료(main 9192b44, release-20261008). 할 일 없음.

[B] TK-63(P2) — F3 주장 단위 대조를 '선별 규칙 + 예산형 상한'으로 바꾼다(사용자 결정 (나)안).
    티켓: docs/handoff/TK-63_f3_claim_budget_document_order.md (요구 3절, 사전 점검 4절, 수용 5절)
    1. Steve_ACASiaLAW 최신(평가 측 PR #38 병합 뒤)에서 새 브랜치 antigravity/tk63-claim-selection을 만든다.
    2. 설계: requests/43_f3_design.md에 '5.2 개정(TK-63)' 절을 더한다(같은 PR).
    3. 선별 규칙(3.1): 인용 연결 → 법률효과·요건(LEGAL_RULE·LEGAL_ARGUMENT, 금액·날짜) → FACT → 그 밖 → 15자 미만 형식 문장. 같은 순위는 문서 순서.
    4. 예산형 상한(3.2): Settings 필드 3개와 환경변수
       LV_RAG_CLAIM_MAX_PER_DOCUMENT(기본 30), LV_RAG_CLAIM_BUDGET_SECONDS(기본 240), LV_RAG_CLAIM_BUDGET_USD(기본 1.00, 0이면 끔).
       다음 주장을 보내기 전에 확인한다. 고정 상수 CLAIM_LIMIT_PER_DOCUMENT는 지운다.
       예산 밖 주장은 REASON_BUDGET_EXCEEDED로 분모에 남긴다. 주장당 요청 3회·발췌 4,000자·요청 검사는 그대로 둔다.
    5. 기록(3.3): claim_coverage에 selection_rule과 budget(적용값, 멈춘 원인 COUNT·TIME·COST)을 더한다.
    6. 시험(3.4) 5종: 선별, 형식 문장, 시간 예산(가짜 시계), 비용 예산(가짜 비용, 0이면 끔), 설정값 적용.
       평가 측 보호 시험(tests/acceptance/test_f3_protected.py)은 고치지 않는다. 평가 측이 하네스에서 상한 10으로 고정해 두었다.
    7. 서면9 문장·특정 규정명에 맞춘 규칙을 넣지 않는다.
    8. 보고: 전후 scorecard 출력 원문과 측정 조건, 관련 시험 pytest 요약 줄 원문.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다. 착수 시점은 평가 측이 따로 지시한다.
```
