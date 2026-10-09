# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-09 평가 측(PR #53 판정, TK-71 신설). 이전 전달문(2026-10-04)을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Codex 작업 — 통합 지시 2026-10-09 (5)]

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

[B] (보통, 지금) TK-24 — PR #53(dc79563) 불승인(소규모 1). 같은 브랜치에 보완 커밋을 올린다. 자세한 내용은 PR #53 평가 측 코멘트.
 - 충족(유지): LEG-2 3건 strict XPASS·그 밖 실패 0, 비공개 정상 항변 8/8, 출력 형식(LEGAL_ARGUMENT_INVALID·SUSPICIOUS·MEDIUM·C, 결론 문장 발췌).
 - 보완: packages/legal_engine/statutory_exclusion.py의 처리 시간이 문장 길이에 대해 제곱이다(합성 56KB 한 문장 20.8초, 기준 경로는 선형).
   1) 문장 하나의 작업이 길이에 비례하도록(서술어 주변 유한 창, 문장 단위 계산 1회, 논항 위치 사전 계산 등). 동작은 바꾸지 않는다.
   2) 시간 시험: '소멸시효는 정의에 따라 적용이 배제되어야 하므로, '와 '소멸시효의 적용을 ' 각 2,000회 반복 + 배제 결론 1문장 입력에서
      exclusion_clauses·classify_claims 각 0.1초 이내(CI에서 흔들리지 않게 넉넉히).
   3) 보고에 위 두 입력의 전후 시간을 적는다.
 - 수용되면 평가 측이 평가 측 브랜치에서 병합해 LEG-2 strict xfail 3개를 지우고 verify_all 전체 모드 뒤 평가 측 PR로 들인다. 이 PR은 직접 병합하지 않는다.

[C] CodeQL 로그 정리 — PR #54 수용·병합(Steve 5d7ac6c). 할 일 없음. 경보 해소는 다음 릴리스 PR의 CodeQL에서 평가 측이 확인한다.

[D] (보통, 설계 메모 지금 · 구현은 아래 선행 조건 뒤) TK-71 표 형식 표준판례 참고자료 활용 — docs/handoff/TK-71_structured_case_table_reference.md
 - 배경: 사용자가 Drive 참고자료 폴더에 표준판례 표(xlsx, 7개 분야 시트·3,555행: 번호|제목|판례 정보|쟁점|선정이유|판결요지)를 넣었다.
   목적은 ① 서면의 법리 주장과 관련된 표준판례 찾기 ② 인용된 사건정보(법원·선고일·사건번호) 대조 ③ 판결요지가 그 주장을 뒷받침하는지 확인이다.
 - 현재(평가 측 재현): 이 파일은 색인되지 않는다.
   본문 3,657,114자가 MAX_CHARS 3,000,000을 넘어 REFERENCE_TEXT_LIMIT인데 기록에는 REFERENCE_PARSE_FAILED로 남는다.
   상한을 풀어도 추출 132초로 제한 시간 30초를 넘는다.
   색인되더라도 한 쪽으로 이어 붙인 고정 창 조각이라 사건번호와 요지가 갈리고 판례가 섞인다(3,883조각 중 섞임 678, 사건 머리 없음 966).
   사건번호는 검색에 쓰이지 않고(숫자 제거), 대조는 문자열 존재 여부뿐이다. 판결요지는 인용 주장에 전달되지 않는다.
 - 요구(티켓 2절): 행 단위 기록 색인(사건 머리를 각 조각에), 크기·시간 예산 안 색인과 정확한 실패 사유, 인용 사건번호 정확 조회,
   법원·선고일·사건번호 대조(reference_status 새 값, official_status·finding 불변 — D4·T6), 인용 주장 요청에 요지 우선 전달(기존 상한·허용 키 안).
 - 회귀 금지(티켓 2.6): 보호 시험 T6~T9·TK-29 가드, Drive·관련도·조각 창·TK-09·TK-65 시험, 문서 엔진 시험을 고치지 않고 통과.
   기준값: 보호 시험 등 10개 파일 203 passed, tests/test_document_engine.py 21 passed.
   TK-63 예산·TK-65 형식 불변, 발췌 마스킹·inspect_request 경유, 요청 허용 키 확장은 설계 메모로 평가 측 회신 뒤.
   고정 81.7/79.2/0·은퇴 세트·개인정보 게이트 유지.
 - 시험(티켓 2.7)은 합성 자료만 쓴다. 사용자 Drive 파일과 그 내용은 저장소에 넣지 않는다. 새 분석 경로마다 반복 입력 시간 시험을 둔다.
 - 순서
   1) 설계 메모를 지금 docs/handoff/requests/에 첫 커밋으로 낸다(브랜치 codex/tk71-structured-case-table). 평가 측 회신 전에는 코드를 쓰지 않는다.
   2) (사용자 결정 2026-10-09로 변경) 구현은 지금 진행한다. TK-71을 먼저 받고, Antigravity TK-68은 TK-71 병합 뒤 시작한다.
      TK-70(pipeline.py·candidate_verifier.py·gate.py)과 겹치면 먼저 병합된 쪽을 병합 커밋으로 받아 맞춘다.
 - 수용 SHA에서 평가 측이 verify_all 전체 모드를 돌리고, 배포 뒤 평가 측 비공개 온라인 세트로 잰다.

각 항목은 따로 Steve_ACASiaLAW 대상 PR로 올리고, CI가 끝난 뒤 '검토 요청'을 남긴다. 병합은 사용자가 한다.
```

## 평가 측 메모(전달하지 않는다)
- RAG-2(Drive 대조 모순을 finding 목록에 올림)는 Codex에 넘기지 않았다. 사용자가 D4를 '단계적 조건부 승격'으로 바꿨고(2026-10-09), 1단계 측정 충족 뒤 TK-70으로 Antigravity (40) [D]에 넘겼다.
- TK-45 잔여(요건 부정 변형 미탐)는 이번 결정 범위(LEG-2·PII-K6·RAG-2) 밖이라 넘기지 않았다.
