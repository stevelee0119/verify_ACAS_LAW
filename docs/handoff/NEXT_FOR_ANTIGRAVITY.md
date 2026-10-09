# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-09 평가 측(TK-64 봉인 기준 충족, 버전 0.11.0 판정). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-09 (35)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   푸시 전 python scripts/check_test_edits.py --base origin/Steve_ACASiaLAW 출력을 보고에 붙인다.

[A] TK-63·TK-65 배포 완료(main 4c18528). TK-64 Steve 병합 완료(34e1c9a), 봉인 기준 충족. 할 일 없음.

[B] 버전 커밋 0.10.0 → 0.11.0 (VERSION_POLICY 6절 3)
    착수 시점: 평가 측 판정서(docs/scorecards/version_verdicts.json의 0.11.0 항목)가 Steve_ACASiaLAW에 들어간 뒤.
               평가 측 PR이 병합되면 사용자가 알린다. 그 전에는 시작하지 않는다(판정서 없는 상향은 점검 실패).
    브랜치: Steve_ACASiaLAW 최신에서 antigravity/version-0.11.0
    1. 커밋 1개만 만든다. 바꾸는 것은 아래 셋뿐이다. 다른 변경을 섞지 않는다.
       - packages/common/config.py 의 version: "0.10.0" → "0.11.0"
       - docs/releases.json 에 0.11.0 항목 1개(date 2026-10-09). changes에는 판정서 근거 수치와 포함 티켓을 적는다:
         TK-64(번호 붙은 입증방법 제목 인식, 목록 구역 번호의 본문 언급 중복 제외 — 봉인 sealed_20261009 오탐 3→1·A등급 2→0,
         은퇴 sealed_20261008b 24.6→29.6), TK-63(주장 선별 규칙·예산형 상한), TK-65(응답 최상위 형식·빈 예외 문구·비용 기록 분리).
         봉인·은퇴 세트의 문장·사건 값은 쓰지 않는다(이름과 수치만).
       - python scripts/update_readme.py 가 갱신하는 README 표
    2. 보고: python scripts/check_version_policy.py --base origin/Steve_ACASiaLAW 출력 원문,
       git show --stat HEAD 출력(바뀐 파일이 위 셋뿐인지), check_test_edits 출력.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다. 착수 시점은 평가 측이 따로 지시한다.
```
