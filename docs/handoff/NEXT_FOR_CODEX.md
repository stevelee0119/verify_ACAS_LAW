# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-09 평가 측(PR #57 TK-71 보완 재판정). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Codex 작업 — 통합 지시 2026-10-09 (7)]

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

[D] (높음, 지금) TK-71 표 형식 표준판례 — PR #57 보완(e2c4679·2eda6c4) 재판정 불승인(필수 3). 같은 브랜치에 보완 커밋을 올린다.
   자세한 내용은 PR #57 평가 측 코멘트 두 건과 docs/handoff/TK-71_structured_case_table_reference.md.
 - 해소(유지): 비인용 표 행은 기존 자료와 점수로 경쟁, 숨김 시트·흰 글꼴 검사·제외 상한·파일 격리·scan_findings 기록,
   사건 머리 앞, 표 행 캐시, 병합 사건번호·선고일 형식 시험. 보호 시험·문서 엔진·TK-71 시험 235개 통과.
 - 필수 보완
   1) 실제 표 색인: 지금은 격리 추출 30초에 하위 프로세스가 끝나 색인 0행이다(직전 848행). 상한 없이 99초, 87초가 find_pattern_hits_batch.
      법률 문장에는 사전 필터 단서가 흔해 거의 걸러지지 않는다. 일괄 검사 구간에도 시간 점검을 두고 부분 결과를 남긴다.
      주입 검사를 그대로 두고 30초 안에 넣기는 어렵다(기존 단건 검사로 3.6M자 약 120초). 권장: 동기화마다 이어 읽기(읽은 시트·행 범위 기록,
      끝까지 REFERENCE_PARTIALLY_READ) 또는 추출을 동기화 밖(작업자)으로. 크기 시험 입력은 단서 낱말이 섞인 실제 같은 합성 법률 문장으로.
   2) 주입 검사 약화 금지: 새 사전 필터·이어 붙인 일괄 검사가 단건 경로와 다르다(저장소 시험 주입 문장 18개 결과 상이, 행 격리 12 → 3).
      일괄 경로가 단건 경로와 같은 결과임을 INSTRUCTION_PATTERNS 전부·기존 적대 시험 문자열로 시험하거나, 사전 필터·이어 붙이기를 뺀다.
      packages/adversarial_engine/ 변경은 탐지 엔진 변경이다(평가 측이 verify_all·고정·은퇴·봉인 필요 여부를 다시 본다).
   3) 표가 있어도 INCOMPLETE_COVERAGE·NOT_RELEVANT 조기 반환을 유지하고 사건정보 대조 기록만 붙인다(review.py, 지난 판정 3 미반영). 시험 1건.
 - 소규모: 머리글 판별·행 분할 반복 입력 시간 시험, 사건 표가 아닌 안내 시트 행 제외.
 - 회귀 금지·시험 원칙은 티켓 2.6·2.7 그대로(합성 자료만, 사용자 Drive 파일 저장소 반입 금지).
 - 보고에 scripts/scorecard.py 전후 원문, 관련 pytest 요약 줄 원문, check_test_edits 출력을 붙인다(로컬에 pytest가 없으면 의존성 설치 뒤).
 - Antigravity TK-68(packages/rag_engine/review.py)은 이 PR 병합 뒤 시작한다. 수용 SHA에서 평가 측이 verify_all 전체 모드와 실제 표 격리 추출을 다시 잰다.

각 항목은 따로 Steve_ACASiaLAW 대상 PR로 올리고, CI가 끝난 뒤 '검토 요청'을 남긴다. 병합은 사용자가 한다.
```

## 평가 측 메모(전달하지 않는다)
- RAG-2(Drive 대조 모순을 finding 목록에 올림)는 Codex에 넘기지 않았다. 사용자가 D4를 '단계적 조건부 승격'으로 바꿨고(2026-10-09), 1단계 측정 충족 뒤 TK-70으로 Antigravity (40) [D]에 넘겼다.
- TK-45 잔여(요건 부정 변형 미탐)는 이번 결정 범위(LEG-2·PII-K6·RAG-2) 밖이라 넘기지 않았다.
