# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-06 평가 측(PR #24 FT 설계 보충 개정 1 조건부 승인 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-06 (16)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전·점수는 실제 출력 그대로 적는다. 코드 사실(함수·rule_id·오류 문구)은 코드에서 확인한 것만 적는다.

[A] F1·F2 — 병합·배포 완료(main 67a87ba). 할 일 없음.

[B] FT 2단계: 구현 — 설계(PR #24 ffe5d47) 조건부 승인. 판정 원문: PR #24의 평가 측 코멘트(개정 1 판정).
    선행요건: PR #24 병합 — **충족(2026-10-06, Steve c206386).** 지금 착수한다.
    1) 브랜치 antigravity/ft-temporal-review에 Steve_ACASiaLAW 최신을 병합한 뒤 구현하고, 새 PR(base Steve_ACASiaLAW)을 연다.
    2) 설계 메모(42_ft_design.md 개정 1)대로 구현하되, 다음 조건 2건을 반드시 지킨다.
       ① 목 글자는 명시 집합 [가나다라마바사아자차카타파하]로 쓴다. [가-하]는 유니코드 범위(10,585음절)라
          '제2호 품목'을 '품'목으로 읽는다(평가 측 실행). 목 인식·목 분할 정규식 모두에 적용한다.
       ② 같은 시행일 판별은 예외 문구를 파싱하지 않는다. official_versions에서 연혁 행을 effective_from으로 묶어 직접 구하고,
          그 밖의 차단(법령 식별 모호·공포일>기준일·폐지 경계·중복 충돌)은 후보마다 유지한다. select_version은 고치지 않는다.
          (메모에 적힌 'Multiple versions share the same effective date'는 실제 문구와 다르다. 실제: legal_history.py:106)
    3) 시험
       - 보호 시험(고치지 않는다): T10 양성 tests/acceptance/test_prepared_brief_mirror_official.py::test_new_data_ka_cited_for_2020_act_is_flagged와
         T11 strict xfail 3개(tests/acceptance/test_ft_protected.py)가 XPASS가 되어야 한다. 이 4건의 strict XPASS 실패는 예정된 것이다.
         보고에 'XPASS(strict) 외 실패 0'으로 적는다. 표시는 평가 측이 수용 때 지운다.
       - T10 오탐 대조 4개, T11 구조 확인, tests/test_legal_completion.py(fail-closed), tests/test_unverified_reasons.py,
         tests/test_v4_p3_temporal.py, tests/test_v4_review_temporal.py는 계속 통과해야 한다.
       - 새 시험: 메모 5절 추가 대조군 4건. 대조군 1에 '제N호 품목'·'제N호 과목' 사례를 포함한다. 입력은 공식 원문 미러로 짓는다.
    4) 보고(PR 3줄 코멘트 + 본문)
       - 변경 전후 python scripts/scorecard.py(dev·holdout) 출력을 그대로 싣는다. 점수가 내려가면 안 된다.
       - 위 시험의 pytest 요약 줄을 그대로 싣는다.
    5) 금지: 보호 경로(tests/acceptance/**·tests/fixtures/**·scripts/ 평가 도구·docs/scorecards/**) 수정, skip·xfail 표시 변경,
       사건 고유 값(법령명·조문 번호·목 글자·날짜) 하드코딩, 버전 변경, FT 외 기능 커밋 섞기.

[C] TK-61 — 수용·병합 완료(Steve b12bea4). 할 일 없음.

[D] F3 — 아직 착수하지 않는다(FT 뒤).
```
