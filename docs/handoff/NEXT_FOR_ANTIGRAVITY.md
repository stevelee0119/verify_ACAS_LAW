# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-08 평가 측(TK-63 구현 PR #40 a9de019 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-08 (28)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').

[A] F1·F2·TK-61·FT·F3 — 모두 병합·배포 완료(main 9192b44, release-20261008). 할 일 없음.

[B] TK-63 — PR #40(a9de019) 불승인(소규모 3건). 같은 브랜치 antigravity/tk63-claim-selection에서 고친다.
    1. 삭제한 시험 tests/test_f3_claim_search.py::test_claim_level_excerpt_selection_via_review_document를 그대로 복원한다
       (c8cd775 판이 현 코드에서 통과함). 고칠 필요가 있으면 먼저 docs/handoff/requests/로 사유를 올린다.
    2. claim_coverage.budget은 설계 개정 3절의 4개 키(max_per_document·budget_seconds·budget_usd·halt_reason)만 남긴다.
       중복 별칭 6개를 지우고, 단위 시험도 이 4개 키로 확인한다.
    3. 푸시 전에 python scripts/check_test_edits.py --base origin/Steve_ACASiaLAW를 실행하고,
       그 출력과 scorecard 출력 원문·측정 조건·pytest 요약 줄을 보고에 붙인다.
    (권고) 개수 상한을 '선별해 처리한 주장 수'로 센다는 점을 설계 개정 절에 적는다.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다. 착수 시점은 평가 측이 따로 지시한다.
```
