# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-06 평가 측(PR #24 FT 설계 보충 판정·PR #26 TK-61 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-06 (15)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전은 실제 출력 그대로 적는다. 구현 메모에 코드 사실(함수·rule_id 존재 여부)을 적을 때는 코드에서 확인한 것만 적는다.

[A] F1·F2 — 병합·배포 완료(main 67a87ba). 할 일 없음.

[B] FT 설계 보충(PR #24 bce4bbf) — 판정: 보완 요구(승인 보류). 판정 원문: PR #24의 평가 측 코멘트.
    1) 같은 브랜치 antigravity/ft-temporal-review에서 docs/handoff/requests/42_ft_design.md만 고친다. 코드는 쓰지 않는다.
    2) 반영할 것(요약 — 세부는 PR 코멘트 1~8):
       ① rule_id: TEMPORAL.SAME_DAY_VERSIONS_AMBIGUOUS는 코드에 없다. 새 rule_id 없이 기존 TEMPORAL.REVIEW_NEEDED를 쓰고
          confidence_features에 ambiguity "SAME_EFFECTIVE_DATE"·버전별 상태를 싣는다(평가 측 결정).
       ② select_version은 고치지 않는다. 같은 시행일 후보 묶기는 official_versions 안에서 하고, 그 밖의 차단은 후보마다 유지한다.
          현행(today) 경계의 같은 시행일 버전 처리도 적는다.
       ③ ref·current를 첫 원소가 아니라 버전 집합으로 판정한다. 집합 안에서 결과가 갈리면 기존 분기보다 먼저 확인 요청으로 보낸다.
       ④ 목 글자는 가~하로 한정하고, 호 표기에 붙은 경우만 인정한다('항목'·'품목'·'교과목' 오인식 금지).
       ⑤ 목 분할이 성공했고 청구 문언이 어느 목에도 없을 때만 부존재 근거로 쓴다. 분할 실패 시 새 finding을 내지 않는다.
       ⑥ 일치 기준은 기존 compare_claim_to_provision이다.
       ⑦ 공식 원문 미러로 지은 추가 대조군을 3개 이상 넣는다(보호 시험 T10·T11과 다른 것).
       ⑧ 영향 범위는 측정 방법으로 적는다(전후 scripts/scorecard.py dev·holdout 값, 관련 시험 실제 출력).
    3) 푸시 → PR #24에 3줄 코멘트와 '검토 요청'. 평가 측이 PR 코멘트로 확인하면 승인이다. 승인 전에는 FT 코드를 쓰지 않는다.

[C] TK-61(PR #26 df6571c) — 판정: 수용. 할 일 없음(병합은 사용자 결정).

[D] F3 — 아직 착수하지 않는다(FT 뒤).
```
