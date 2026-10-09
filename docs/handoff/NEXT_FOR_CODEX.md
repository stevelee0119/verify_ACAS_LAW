# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-09 평가 측(PR #52·#53·#54 판정 반영). 이전 전달문(2026-10-04)을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Codex 작업 — 통합 지시 2026-10-09 (2)]

0. 규칙(AGENTS.md)
 - 시작: 평가 측 기록 PR #51이 Steve_ACASiaLAW에 병합된 뒤, 최신 Steve_ACASiaLAW에서 작업 브랜치를 만든다(티켓 개정이 거기 들어 있다).
 - 리베이스·강제 푸시 금지(병합 커밋). 커밋 메시지 끝에 'Agent: implementer'와 게이트 출력의 점수 변화를 적는다.
 - 보호 경로(tests/acceptance/**, tests/fixtures/**, scripts/의 평가 도구, docs/scorecards/**) 수정 금지, skip·xfail 표시 변경 금지.
 - 서면의 문장·당사자·사건번호·금액·조문 번호에 맞춘 규칙 금지. 새 규칙마다 양성 3건 이상·대조 3건 이상 시험(합성임을 시험 설명에 적음).
 - 커밋 전에는 바꾼 파일과 아래 관련 시험만 돌린다. 푸시 뒤 CI가 실패하면 job 로그 끝 '실패 시험 목록'으로 고친다.
 - 정규식을 새로 넣거나 바꾸면 반복 입력(수천 번) 시간 시험을 함께 둔다(0.1초 이내).
 - 보고: PR 코멘트 3줄(바꾼 것·남은 것·'검토 요청') + `python scripts/scorecard.py` 전후 출력 원문 + 관련 시험 pytest 요약 줄 원문.
   푸시 전 `python scripts/check_test_edits.py --base origin/Steve_ACASiaLAW` 출력을 붙인다.
 - 다른 구현 담당(Antigravity)이 같은 시기에 packages/claim_engine/evidence_consistency.py, packages/legal_engine/temporal_review.py,
   packages/rag_engine/review.py를 고친다(TK-67·69·68). 이 세 파일은 건드리지 않는다.

[A] TK-58 — PR #52(f2033e1) 수용. 병합은 사용자가 한다. 할 일 없음.
 - 참고(후속 후보, 지금 하지 않음): 판단이 안 되는 번호의 새 종류 'PII'는 화면·보고서에 한글 이름이 없다.

[B] (보통, 지금) TK-24 — PR #53 설계 메모 승인. 같은 브랜치(codex/tk24-statutory-period-exclusion)에 구현 커밋을 이어 올린다.
 - 평가 측 회신(PR #53 코멘트)의 보완 5개를 반영한다.
   1) 결론절에 당위·청구 형태('~되어야 한다', '~되어서는 안 된다', '적용을 배제하여 달라')를 포함
   2) 범주적 한정어가 없어도 무조건적 적용 부정이면 같은 판단. 양성 1건(한정어 없음)·대조 1건(한정어 있으나 법정 예외 정확 원용) 시험 추가
   3) 출력: LEGAL_ARGUMENT_INVALID(또는 OVERCLAIM)·SUSPICIOUS·MEDIUM 이하, 근거 발췌는 배제 결론 문장 구간, 새 rule_id, 기존 NO_BASIS_REMEDY와 별개
   4) 평가 측 비공개 법리 세트의 정상 항변 오탐 없음 8/8 유지(평가 측이 잰다)
   5) 수용: LEG-2 두 건만 strict XPASS·그 밖 실패 0, 관련 310 passed·2 xfailed / round7 105 passed·5 xfailed 기준, 고정 81.7/79.2/0, 은퇴 세트 하락 없음, 새 정규식이면 반복 입력 시간 시험
 - 탐지 엔진 변경이므로 수용 SHA에서 평가 측이 verify_all 전체 모드를 돌리고, 릴리스 전 새 봉인 세트로 봉인 시험을 한다.

[C] CodeQL 로그 정리 — PR #54 수용·병합(Steve 5d7ac6c). 할 일 없음. 경보 해소는 다음 릴리스 PR의 CodeQL에서 평가 측이 확인한다.

각 항목은 따로 Steve_ACASiaLAW 대상 PR로 올리고, CI가 끝난 뒤 '검토 요청'을 남긴다. 병합은 사용자가 한다.
```

## 평가 측 메모(전달하지 않는다)
- RAG-2(Drive 대조 모순을 finding 목록에 올림)는 Codex에 넘기지 않았다. 사용자가 D4를 '단계적 조건부 승격'으로 바꿨고(2026-10-09), 1단계 측정 충족 뒤 TK-70으로 Antigravity (40) [D]에 넘겼다.
- TK-45 잔여(요건 부정 변형 미탐)는 이번 결정 범위(LEG-2·PII-K6·RAG-2) 밖이라 넘기지 않았다.
