# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-10 평가 측(PR #53 TK-24 0ad4fac 수용). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Codex 작업 — 통합 지시 2026-10-10 (10)]

0. 규칙(AGENTS.md)
 - 시작: 평가 측 기록 PR #51이 Steve_ACASiaLAW에 병합된 뒤, 최신 Steve_ACASiaLAW에서 작업 브랜치를 만든다(티켓 개정이 거기 들어 있다).
 - 리베이스·강제 푸시 금지(병합 커밋). 커밋 메시지 끝에 'Agent: implementer'와 게이트 출력의 점수 변화를 적는다.
 - 보호 경로(tests/acceptance/**, tests/fixtures/**, scripts/의 평가 도구, docs/scorecards/**) 수정 금지, skip·xfail 표시 변경 금지.
 - 서면의 문장·당사자·사건번호·금액·조문 번호에 맞춘 규칙 금지. 새 규칙마다 양성 3건 이상·대조 3건 이상 시험(합성임을 시험 설명에 적음).
 - 커밋 전에는 바꾼 파일과 아래 관련 시험만 돌린다. 푸시 뒤 CI가 실패하면 job 로그 끝 '실패 시험 목록'으로 고친다.
 - 문장·문서마다 도는 새 분석 경로(정규식뿐 아니라 반복·재탐색 로직 포함)는 반복 입력(수천 번) 시간 시험을 함께 둔다(0.1초 이내).
 - 보고: PR 코멘트 3줄(바꾼 것·남은 것·'검토 요청') + `python scripts/scorecard.py` 전후 출력 원문 + 관련 시험 pytest 요약 줄 원문.
   푸시 전 `python scripts/check_test_edits.py --base origin/Steve_ACASiaLAW` 출력을 붙인다.
 - 다른 구현 담당(Antigravity)이 같은 시기에 packages/claim_engine/evidence_consistency.py, packages/legal_engine/temporal_review.py,
   packages/rag_engine/review.py를 고친다(TK-67·69·68). 이 세 파일은 건드리지 않는다.

[A] TK-58 — PR #52(f2033e1) 수용·병합(Steve 3daf7b6). 할 일 없음.
 - 참고(후속 후보, 지금 하지 않음): 판단이 안 되는 번호의 새 종류 'PII'는 화면·보고서에 한글 이름이 없다.

[B] TK-24 — PR #53(0ad4fac) 수용. 할 일 없음. 이 PR은 직접 병합하지 않는다.
 - 확인: 제곱 시간 해소(합성 56KB 한 문장 exclusion_clauses 20.8초 → 0.07초 이하, classify_claims 1.17초 → 0.023초, 반복 단위 9종 4,000회까지 선형),
   LEG-2 3건 strict XPASS·그 밖 실패 0, 비공개 정상 항변 8/8 유지, Steve 0bf4ccc와 충돌 없음.
 - 다음(평가 측): 0.12.0 릴리스 병합 뒤 평가 측 브랜치에서 병합 → LEG-2 strict xfail 3개 삭제 → verify_all 전체 모드 → 평가 측 PR.
   그때까지 PR #53 브랜치에 커밋을 더 올리지 않는다(올리면 재판정이 필요하다).

[C] CodeQL 로그 정리 — PR #54 수용·병합(Steve 5d7ac6c). 할 일 없음. 경보 해소는 다음 릴리스 PR의 CodeQL에서 평가 측이 확인한다.

[D] TK-71 표 형식 표준판례 — PR #57(7aecc51) 수용·병합(Steve 3c89a4e). 할 일 없음.
 - 확인: 실제 표 6회 이어 읽기로 3,555행 모두 색인, 주입 검사 엔진 복원, verify_all 전체 종료 0, 관련 239 passed.
 - 참고(후속 후보, 지금 하지 않음): 사건 표가 아닌 안내 시트 행 1개가 기록으로 들어간다(조회 영향 없음).

각 항목은 따로 Steve_ACASiaLAW 대상 PR로 올리고, CI가 끝난 뒤 '검토 요청'을 남긴다. 병합은 사용자가 한다.
```

## 평가 측 메모(전달하지 않는다)
- RAG-2(Drive 대조 모순을 finding 목록에 올림)는 Codex에 넘기지 않았다. 사용자가 D4를 '단계적 조건부 승격'으로 바꿨고(2026-10-09), 1단계 측정 충족 뒤 TK-70으로 Antigravity (40) [D]에 넘겼다.
- TK-45 잔여(요건 부정 변형 미탐)는 이번 결정 범위(LEG-2·PII-K6·RAG-2) 밖이라 넘기지 않았다.
