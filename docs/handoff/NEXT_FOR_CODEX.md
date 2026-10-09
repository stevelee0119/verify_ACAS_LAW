# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-09 평가 측(PR #57 TK-71 구현 판정). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Codex 작업 — 통합 지시 2026-10-09 (6)]

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

[D] (높음, 지금) TK-71 표 형식 표준판례 — PR #57(3423668) 불승인(필수 5·소규모 3). 같은 브랜치(codex/tk71-structured-case-table)에 보완 커밋을 올린다.
   자세한 내용은 PR #57 평가 측 코멘트와 docs/handoff/TK-71_structured_case_table_reference.md.
 - 충족(유지): 일반 자료 SUPPORTED 불변, reference_case_match 별도 필드, 공식 DB 추가 호출 없음, 머리글 자동 판별, 실패 사유 보존.
   보호 시험 등 10개 파일 209 passed(203 + 신규 6), tests/test_document_engine.py 21 passed.
 - 필수 보완
   1) 실제 규모 색인: 실제 표(3,555행)를 격리 추출(256MB·30초)에 넣으면 25초 상한에서 멈춰 848행만 색인되고 INDEXED_PARTIAL로 캐시된다.
      상한 없이 130초이고 98%가 행마다 부르는 AdversarialScanner.scan이다(행 읽기는 0.8초).
      방법은 설계 재량: 동기화에 걸친 이어 읽기(읽은 범위 기록, 끝까지 REFERENCE_PARTIALLY_READ) / 추출을 동기화 밖으로 / 스캐너 속도 개선(탐지 결과 불변 증명 필요).
      주입 검사를 생략·축소하지 않는다. 티켓 2.7 크기 시험(합성 4,000행·400만 자, 제한 안 색인)을 둔다.
   2) 주장 요청에서 기존 Drive 자료를 밀어내지 않는다: 정렬 키가 표 행을 점수와 무관하게 앞에 둔다.
      인용 판례 정확 일치 행만 우선하고, 그 밖 표 행은 기존 자료와 같은 점수로 경쟁(최소 점수·슬롯 상한).
      시험: 인용 없는 주장에 관련 일반 자료가 남음, 인용 판례 요지는 그 주장 요청에만 들어감.
   3) 표가 있어도 INCOMPLETE_COVERAGE·NOT_RELEVANT 조기 반환을 유지하고 사건정보 대조 기록만 붙인다. 시험 1건.
   4) 보안: 빼는 행 상한(설정값), 넘으면 파일 전체 REFERENCE_QUARANTINED. 숨김 시트·흰 글꼴 행도 검사·기록·상한에 포함.
      scan_findings 근거 3건까지 파일 기록에 남김. 시험: 흰 글꼴 지시문, 숨김 시트 지시문, 상한 초과 격리 각 1건.
   5) 요청 본문 text 맨 앞에 짧은 사건 머리(시트·법원·선고일·사건번호), 나머지는 요지 우선(지금 실제 848행 중 324행은 사건번호가 잘려 빠짐).
 - 소규모: 표 행을 문서당 한 번 읽고 사건번호 사전으로 조회(지금 호출마다 전체 재적재 0.13~0.28초), 주장 단계 시간 소모 보고.
   시험 보충(선고일 형식 차이 일치·병합 사건번호·머리글 판별과 행 분할 반복 시간), 사건 표가 아닌 안내 시트 행 제외.
 - 회귀 금지·시험 원칙은 티켓 2.6·2.7 그대로(합성 자료만, 사용자 Drive 파일 저장소 반입 금지).
 - 보고에 scripts/scorecard.py 전후 원문, 관련 pytest 요약 줄 원문, check_test_edits 출력을 붙인다(로컬에 pytest가 없으면 의존성 설치 뒤).
 - Antigravity TK-68(packages/rag_engine/review.py)은 이 PR 병합 뒤 시작한다. 수용 SHA에서 평가 측이 verify_all 전체 모드와 실제 표 격리 추출을 다시 잰다.

각 항목은 따로 Steve_ACASiaLAW 대상 PR로 올리고, CI가 끝난 뒤 '검토 요청'을 남긴다. 병합은 사용자가 한다.
```

## 평가 측 메모(전달하지 않는다)
- RAG-2(Drive 대조 모순을 finding 목록에 올림)는 Codex에 넘기지 않았다. 사용자가 D4를 '단계적 조건부 승격'으로 바꿨고(2026-10-09), 1단계 측정 충족 뒤 TK-70으로 Antigravity (40) [D]에 넘겼다.
- TK-45 잔여(요건 부정 변형 미탐)는 이번 결정 범위(LEG-2·PII-K6·RAG-2) 밖이라 넘기지 않았다.
