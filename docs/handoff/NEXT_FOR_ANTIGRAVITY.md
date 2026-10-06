# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-06 평가 측(PR #27 FT 구현 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-06 (17)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전·점수는 실제 출력 그대로 적는다(요약만 적지 않는다). 코드 사실은 코드에서 확인한 것만 적는다.

[A] F1·F2 — 병합·배포 완료(main 67a87ba). 할 일 없음.

[B] FT 구현(PR #27 ca0067b) — 판정: 불승인(보완 1건 필수). 판정 원문: PR #27 평가 측 코멘트, 티켓 docs/handoff/TK-62_ft_subitem_absence_forced_contradiction.md
    충족한 것(유지한다): 보호 시험 T10·T11 통과(strict XPASS 4), 점수 같음, 회귀 0, 목 글자 명시 집합, 예외 문구 파싱 안 함, 대조군 4건.
    1) 같은 브랜치 antigravity/ft-temporal-review에 이어서 커밋한다(같은 PR #27).
    2) 보완(필수, TK-62): version_outcomes의 목 단위 경로
       - 지금: 목 분할 성공 + 어느 목과도 VERIFIED 아님 → 그 판본을 무조건 CONTRADICTED(SUBITEM_NOT_EXIST).
         판본마다 따로 적용되고, 비교기의 UNVERIFIED도 불일치가 된다.
         → 주장이 호 머리글에 있고 목에는 없으면 모든 판본이 CONTRADICTED → NO_VERSION_MATCH(HIGH·A) 새 오탐.
       - 바꿀 규칙: 판본마다 목 단위 결과(일치한 목 / 부존재)를 먼저 모은다.
         어느 판본에서든 목 단위 VERIFIED가 하나 이상 있을 때만 '부존재' 판본을 CONTRADICTED(SUBITEM_NOT_EXIST)로 둔다.
         그렇지 않으면 모든 판본을 FT 전과 같은 조·항 단위 비교 결과로 둔다.
       - (평가 측이 이 규칙을 임시로 넣어 T10·T11 유지와 재현 해소를 확인했다.)
    3) 시험 추가: TK-62 2절 구조(호 머리글에 주장, 목에는 없음, 두 판본 내용 같음)에서 finding이 FT 전과 같음을 단언한다.
       공식 원문 미러에 이 구조가 없으므로 합성 조문을 쓰고, 시험 설명에 합성임을 적는다.
    4) 선택: '제3호 다목적'처럼 목 뒤에 낱말이 이어지는 경우를 제외하는 처리, select_versions와 select_version의 공통 검증부 분리
       (select_version 동작은 바꾸지 않는다).
    5) 보고: 전후 python scripts/scorecard.py(dev·holdout) 출력 원문과, 관련 시험 pytest 요약 줄을 그대로 싣는다.
       'XPASS(strict) 외 실패 0'을 확인해 적는다. strict xfail 표시는 고치지 않는다(평가 측이 수용 때 지운다).
    6) 금지: 보호 경로 수정, skip·xfail 표시 변경, 사건 고유 값 하드코딩, 버전 변경, FT 외 기능 커밋 섞기.

[C] TK-61 — 수용·병합 완료(Steve b12bea4). 할 일 없음.

[D] F3 — 아직 착수하지 않는다(FT 뒤).
```
