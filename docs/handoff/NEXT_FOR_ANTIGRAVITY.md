# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-07 평가 측(F3 설계 보충 PR #32 96a4f47 조건부 승인 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-07 (21)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전·점수는 실제 출력 그대로 적는다. 코드 사실(함수 이름·위치·동작)은 코드에서 확인한 것만 적는다.
   선행요건(둘 다 사용자가 병합): ① PR #32(설계 메모) ② 평가 측 PR(F3 보호 시험·fail-closed 단위 시험을 Steve에 반영).
   둘 다 병합된 뒤 Steve_ACASiaLAW를 작업 브랜치에 병합(merge)하고 구현을 시작한다.

[A] F1·F2·TK-61·FT — 모두 병합·배포 완료(main 43d3132). 할 일 없음.

[B] F3 2단계 — 구현. 설계: docs/handoff/requests/43_f3_design.md(96a4f47), 지시서: docs/handoff/PROMPT_FOR_F3.md
    평가 측 판정 원문: PR #32 코멘트 '평가 측 판정 — F3 설계 보충 96a4f47: 조건부 승인'.
    1) 브랜치 antigravity/f3-reference-review에서 구현한다. F3 커밋은 다른 기능 커밋과 섞지 않는다.
    2) 구현 조건(메모 재개정 불요)
       a. 검사 함수는 하나: packages/rag_engine/review.py의 validate_claim_request_payload(payload) -> bool.
          예외를 내지 않고, 어떤 위반이든 False를 반환한다(dict 아님, 목록 아님, 중첩 항목 키, 길이 한도).
          실패한 주장은 전송하지 않고 unreviewed 사유 REASON_SCHEMA_VALIDATION_FAILED를 기록한다.
       b. 주장–인용 연결은 Claim.citation_ids(packages/common/schemas.py:395)로 한다. Citation에는 claim_id가 없다.
       c. 마스킹은 packages/pii_engine(PIIEngine.mask_text)이 한다. 보고서에 바로잡아 적는다.
    3) 수용 기준(지시서 5절)
       - tests/acceptance/test_f3_protected.py의 strict xfail 16건(T6~T9·스키마·fail-closed 10)이 XPASS가 된다.
         CI에서 strict XPASS가 실패로 나오는 것은 예정된 것이다. 보고에 'XPASS(strict) 외 실패 0'으로 적는다.
         표시는 평가 측이 지운다. 이 파일은 고치지 않는다.
       - 고정 시험 dev 81.7 / holdout 79.2 / 오탐 0, probe·회귀 게이트 회귀 0, 새 rule_id·FindingType 0.
       - 같은 파일의 통과 시험 9건, T1~T5·T2r·T6a·T10·T11은 계속 통과한다.
    4) 보고: 전후 python scripts/scorecard.py 출력 원문과 관련 시험 pytest 요약 줄 원문을 붙인다.
       확인하지 못한 것(실제 Drive 연동·모델 대조 품질·화면 사용성)은 못 했다고 적는다.
    5) 금지: 보호 경로(tests/acceptance/**·tests/fixtures/**·scripts/ 평가 도구·docs/scorecards/**) 수정,
       skip·xfail 표시 변경, 작업 커밋에서 버전 변경, 참고 의견의 심각도·finding 승격.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다.
```
