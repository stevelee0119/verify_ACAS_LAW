# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-05 평가 측(FT 보호 시험 고정·FT 지시서 작성 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-05 (13)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전은 실제 출력 그대로 적는다.

[A] F1·F2 — 병합 완료(Steve 7f5399f, 8b70497). 할 일 없음.

[B] FT(행위시법 검토 보강) — 1단계: 설계 보충만. 지시서: docs/handoff/PROMPT_FOR_FT.md
    선행요건: 평가 측 PR(보호 시험 T10·T11·FT 지시서)이 Steve_ACASiaLAW에 병합되어야 한다(사용자가 알린다). 그 전에는 착수하지 않는다.
    충족되면:
      1) Steve 최신에서 브랜치 antigravity/ft-temporal-review를 만든다.
      2) docs/handoff/requests/42_ft_design.md만 작성해 PR을 올린다(base Steve_ACASiaLAW). 코드는 쓰지 않는다.
         담을 것은 지시서 3절 1~6. 특히 2절 범위(행위시법 검토 경로만, resolve_statute의 fail-closed 유지)를 따른다.
      3) PR에 3줄 코멘트와 '검토 요청'.
    평가 측 회신 전에는 FT 코드를 쓰지 않는다.

[C] F3 — 아직 착수하지 않는다(FT 뒤).
```
