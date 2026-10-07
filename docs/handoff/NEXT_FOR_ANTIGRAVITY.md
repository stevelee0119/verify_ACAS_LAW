# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-08 평가 측(F3 구현 보완 PR #34 54ac965 재판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-08 (23)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·점수는 실제 출력 원문과 측정 조건(Python·OCR)을 붙인다. 코드 사실은 코드에서 확인한 것만 적는다.

[A] F1·F2·TK-61·FT — 모두 병합·배포 완료(main 43d3132). 할 일 없음.

[B] F3 구현 보완 2차 — PR #34(54ac965) 재판정: 불승인(소규모 보완 2건). 같은 브랜치에서 고친다.
    평가 측 판정 원문: PR #34 코멘트 '평가 측 판정 — F3 구현 보완 54ac965'.
    1차 필수 6건 중 5건은 해소, 주장별 발췌는 로컬 점수 정렬로 실질 해소됐다. 남은 것:
    1) pipeline.py TK-09 가드: `or review.get("advisory_only", False)`를 지운다. review["advisory_only"]는 늘 True라
       지금은 문서 단위 의견까지 모두 빠져 LV_CANDIDATE_PROMOTION_ENABLED가 작동하지 않는다(평가 측 재현: 후보 검증 호출 1회 → 0회).
       주장 단위 의견의 advisory_only 표시로만 거른다. TK-09 기능 자체를 없애는 것은 사용자 결정 사항이다.
    2) Drive 본문 검색 죽은 경로 정리: ReferenceLibrary.sync가 끝나면 client.close()로 닫는다(library.py:178-179).
       보존한 self.client로 search_fulltext를 부르면 운영에서 RuntimeError(닫힘) 또는 SYNC_BUDGET_EXHAUSTED(기한 경과)가 난다.
       - self.client 보존과 리뷰 단계의 search_fulltext 호출을 지우고, 로컬 점수 정렬(이미 읽은 sources)을 주장별 발췌 경로로 확정한다.
       - tests/test_f3_claim_search.py: 닫히지 않는 가짜 클라이언트 주입 시험과 제품 루프를 시험 안에 재구현한 시험을 고친다.
         review_document를 통해 주장마다 관련 발췌가 골라짐을 확인한다.
       - Drive 검색을 꼭 유지하려면 별도 예산으로 새 클라이언트를 여닫는 설계를 먼저 평가 측과 맞춘다(권하지 않음).
    수용 기준: F3 보호 시험 strict XPASS 16(보고에 'XPASS(strict) 외 실패 0'), 같은 파일 통과 시험 전부 통과,
    점수 81.7/79.2/0(CI 표준 조건) 그대로, 새 rule_id·FindingType 0. 보호 경로는 고치지 않는다.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다.
```
