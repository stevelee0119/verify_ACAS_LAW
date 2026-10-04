# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-04 평가 측. 이전 전달문을 모두 대체한다.

```
[Codex 작업 — 통합 지시 2026-10-04]

[A] 버전 커밋 0.9.13 → 0.10.0 — 평가 측 판정서가 Steve_ACASiaLAW에 병합된 뒤에 시작한다(평가 측이 병합을 알린다).
 1) 최신 Steve_ACASiaLAW에서 새 브랜치 codex/version-0.10.0을 만든다.
 2) 커밋 1개만 만든다. 바꾸는 것은 다음 셋뿐이다(VERSION_POLICY 6절 3).
    - packages/common/config.py의 version = "0.10.0"
    - docs/releases.json 항목: 판정서(docs/scorecards/version_verdicts.json의 0.10.0)의 근거 수치와 포함 티켓
      (M1 dev 79.9→81.7·holdout 77.3→79.2, M3 TK-57 해소, 8차 TK-51 해소, 업로드 개인정보 안내 판 1.1)
    - `python scripts/update_readme.py`가 갱신하는 README 표
 3) 다른 변경을 섞지 않는다. 커밋 끝에 `Agent: implementer`.
 4) Steve_ACASiaLAW 대상 PR을 열고, CI가 끝나면 PR에 '검토 요청'을 남긴다.
```
