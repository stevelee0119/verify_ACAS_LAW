# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-05 평가 측(릴리스 F1·F2 배포·온라인 점검 뒤, TK-61 추가). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-05 (14)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전은 실제 출력 그대로 적는다. [B]와 [C]는 브랜치·PR을 따로 한다(섞지 않는다).
   공통 선행요건: 평가 측 PR #22(FT 보호 시험·FT 지시서·TK-61)가 Steve_ACASiaLAW에 병합되어야 한다(사용자가 알린다).

[A] F1·F2 — 병합·배포 완료(main 67a87ba). 할 일 없음.

[B] FT(행위시법 검토 보강) — 1단계: 설계 보충만. 지시서: docs/handoff/PROMPT_FOR_FT.md
    1) Steve 최신에서 브랜치 antigravity/ft-temporal-review.
    2) docs/handoff/requests/42_ft_design.md만 작성해 PR(base Steve_ACASiaLAW). 코드는 쓰지 않는다.
       지시서 3절 1~6을 담고, 2절 범위(행위시법 검토 경로만, resolve_statute의 fail-closed 유지)를 따른다.
    3) PR에 3줄 코멘트와 '검토 요청'. 평가 측 회신 전에는 FT 코드를 쓰지 않는다.

[C] TK-61 화면 배치(P3) — docs/handoff/TK-61_review_table_whitespace_and_finding_list_layout.md
    1) Steve 최신에서 브랜치 antigravity/tk61-layout.
    2) styles.css만 고친다(1절 3줄 + 2절 3줄). 선택 항목(내부 코드의 사람 말 표기, 긴 AI 의견 접기)은 넣어도 되나 문구·데이터는 바꾸지 않는다.
    3) 새 브라우저 시험 1개 이상(긴 판정 문구가 있어도 열 비율 유지, 세부 항목 위·아래 배치).
    4) 로컬: 기존 브라우저 시험 전부(tests/test_*browser*.py, tests/test_frontend_*.py, tests/test_drive_rag_relevance.py,
       tests/test_reasoning_layout.py, tests/acceptance/test_f1_screen_protected.py).
    5) PR(base Steve_ACASiaLAW)에 3줄 코멘트와 '검토 요청'.

[D] F3 — 아직 착수하지 않는다(FT 뒤).
```
