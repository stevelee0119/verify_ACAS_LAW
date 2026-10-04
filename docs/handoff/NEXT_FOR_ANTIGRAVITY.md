# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-04 평가 측(F1 병합 게이트 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-04 (3)]

0. 규칙(AGENTS.md): 커밋 전에는 바꾼 부분의 시험만 돌린다. 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청'). 리베이스·강제 푸시 금지(병합 커밋).

[A] PR #13 F1 — 병합 게이트 판정: 코드는 충족, 절차 3개 남음(G6·G8·G9). 코드는 고치지 않는다.
 1) 보고서 정정(G9) — docs/handoff/requests/40_f1_completion.md 검증 표의 시험 건수를 실제 출력으로 고친다.
    - tests/acceptance/test_f1_protected.py: '4 passed, 3 skipped'(T3 1·T4 2·T5 1 통과, T1·T2·T4 검토 행은 review_items 없음으로 건너뜀)
    - 기존 브라우저 5개 파일: '61 passed'
    - 앞으로 보고서의 시험 건수는 pytest 마지막 요약 줄을 그대로 옮긴다.
 2) 평가 측 PR(버전 정책 점검 도구 보완)이 Steve_ACASiaLAW에 병합됐다는 알림을 받은 뒤:
    `git fetch upstream Steve_ACASiaLAW && git merge upstream/Steve_ACASiaLAW`(병합 커밋). 충돌은 없어야 한다(평가 측이 같은 병합을 미리 해 봄).
    이 병합 전에는 PR #13의 CI가 버전 정책 단계에서 평가 도구 오판으로 실패할 수 있다(구현 측 결함 아님).
 3) 로컬: tests/acceptance/test_f1_protected.py, tests/test_finding_categories.py만 돌린다. 푸시 뒤 PR #13에 '검토 요청'(병합 head SHA를 적는다).
    평가 측이 그 head의 CI(G6)와 트리를 확인하고, Codex 독립 감사(G8)가 끝나면 병합한다.

[B] F2 통합 '검토 항목' 탭 — 착수 허용(이미 시작했다면 계속).
 - 범위·수용 기준: docs/handoff/PROMPT_FOR_FEATURE_ROUND_F1.md 1절 F2와 19b 설계(정정본).
 - 브랜치: antigravity/f2-review-items. [A] 2)의 병합 head를 F2 브랜치에도 병합 커밋으로 받는다.
   PR은 base를 antigravity/f1-review-screen으로 열고, F1이 Steve_ACASiaLAW에 들어가면 base를 Steve_ACASiaLAW로 바꾼다.
 - 필수:
   · 서버가 documents[].review_items를 만든다. 인용 하나에 행 하나, 행 심각도는 연결된 finding 중 가장 높은 값(연결 없으면 INFO).
   · AI·보안 탭 배정 유형은 검토 행에 넣지 않는다. 그 밖의 finding은 모두 어느 검토 행에 연결한다(HIGH 이상 포함).
   · 기존 JSON 키(findings, ai_hallucination_table, engine_data.rag, 보고서 필드)는 지우거나 이름을 바꾸지 않는다. 추가만 한다.
   · 심각도 규칙·rule_id를 새로 만들지 않는다. 점수·probe 결과는 전후 같아야 한다(점수 하락 게이트).
   · 주장 행은 켜지 않는다(TK-22 해결 전).
 - 평가 측 보호 시험 T1·T2·T4(검토 행)가 F2에서 처음 돈다. 건너뜀 없이 통과해야 한다.
 - 묶음이 끝나면 docs/handoff/requests/에 보고서(지시서 5절 형식) 1개, PR에 '검토 요청'. 시험 건수는 pytest 요약 줄 그대로.

[C] FT·F3 — 아직 착수하지 않는다. F2 수용 뒤 평가 측이 T10·T11(FT)을 고정하고 알린다.
```
