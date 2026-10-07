# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-08 평가 측(F3 구현 PR #34 5abb84e 불승인 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-08 (22)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·점수는 실제 출력 원문을 붙인다. 측정 조건(Python·OCR)을 함께 적고, 다른 조건의 값을 '유지'라고 적지 않는다.
   코드 사실(함수·속성·경로)은 코드에서 확인한 것만 적는다.

[A] F1·F2·TK-61·FT — 모두 병합·배포 완료(main 43d3132). 할 일 없음.

[B] F3 구현 보완 — PR #34(5abb84e) 판정: 불승인. 같은 브랜치 antigravity/f3-reference-review에서 고친다.
    평가 측 판정 원문: PR #34 코멘트 '평가 측 판정 — F3 구현 5abb84e'.
    선행: 평가 측 PR(T7 보강 시험)이 병합되면 Steve_ACASiaLAW를 작업 브랜치에 병합(merge)해 받는다.
    필수 보완
    1) claim_coverage 이중 계산: linked는 대상 주장 id와의 교집합, 미대조 = 대상 주장 − linked(사유는 맵에서),
       all_claims_verified도 같은 기준. 새 보호 시험 test_t7_claim_linked_by_document_level_review_is_not_also_unreviewed가 통과해야 한다.
    2) 주장 단위 검색이 실제로 돌게 한다. ReferenceLibrary에는 client 속성이 없어 지금은 search_fulltext가 한 번도 불리지 않는다.
       이미 읽은 색인 안에서 주장별 관련 발췌를 고른다(ReferenceLibrary.search 같은 기존 함수 또는 라이브러리가 관리하는 클라이언트).
       주장당 검색 2회 이하. 원문 앞 800자를 기계적으로 자르지 않는다. 이 경로가 실행됨을 보이는 단위 시험을 붙인다.
    3) evidence_sources에 Drive URL(https://drive.google.com/file/d/{file_id}/view)을 넣는다(설계 1.2·2.1).
    4) pipeline.py 후보 승격(TK-09) 필터에서 참고 의견(advisory_only)을 뺀다(D4, 설계 4.1).
    5) 요청 본문의 '두 인용을 대조한다'(평가 측 시험의 합성 값)를 제품 코드에서 없앤다. 제품 상수로 정하거나 키를 쓰지 않는다.
    6) 보고: 전후 python scripts/scorecard.py 출력 원문(조건 포함)과 관련 pytest 요약 줄 원문.
       '83.5/81.0 유지'는 표준 조건 측정값(81.7/79.2)과 다르다.
    수용 기준(지시서 5절): F3 보호 시험 strict xfail 16건 XPASS(보고에 'XPASS(strict) 외 실패 0'), 같은 파일 통과 시험 전부 통과,
    점수 81.7/79.2/0 그대로, 새 rule_id·FindingType 0. 보호 경로(tests/acceptance/** 등)는 고치지 않는다.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다.
```
