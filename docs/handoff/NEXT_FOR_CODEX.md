# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-09 평가 측(장기 미해결 과제 인계, 사용자 결정). 이전 전달문(2026-10-04)을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Codex 작업 — 통합 지시 2026-10-09]

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

[A] (보통, 먼저) TK-58 계좌번호가 주민등록번호(RRN)로 분류됨 — docs/handoff/TK-58_account_number_labeled_rrn.md (3·4절, 개정 1)
 - 증상: 서면9 PDF에서 '3-4-4-2' 꼴 계좌번호가 RRN으로 분류된다. 가림은 된다. 온라인 PII-K6이 0.10.0부터 8회 연속 실패했다.
 - 요구: 앞 6자리 안에 공백이 아닌 구분 기호가 있으면 RRN으로 분류하지 않고, 앞 문맥에 계좌 라벨이 있으면 ACCOUNT로 분류한다.
   날짜 유효성·검증 숫자로 거르지 않는다. 가림 구간·전송 차단 동작은 바꾸지 않는다.
 - 브랜치 codex/tk58-account-kind. 관련 시험(기준 85 passed, 고치지 않음):
   tests/test_pii_and_claims.py tests/regression/test_r8f_contact_rrn.py tests/regression/test_r8f1_rrn_linebreak.py
 - 수용: 서면9 PDF 오프라인 ACCOUNT 1·RRN 0, 고정 81.7/79.2/0.
   평가 측이 필수 게이트(연락처·주민등록번호 비공개 세트, 기준 RRN 0·PHONE 0·0·1/54·도달 0·오탐 0)와 verify_all 전체 모드를 잰다.

[B] (보통, 설계 메모 먼저) TK-24 소멸시효 등 법정 기간을 정의·유추로 일체 배제한다는 주장 미탐(LEG-2) — docs/handoff/TK-24_unreasonable_argument_statutory_period.md (요구·수용, 개정 1)
 - 증상: 10-01부터 온라인·오프라인 모두 LEG-2 실패. tests/acceptance/test_case9_state_compensation.py의 [docx-LEG-2]·[text-LEG-2]가 strict xfail.
 - 첫 커밋: docs/handoff/requests/에 1쪽 이내 설계 메모(방법, 일반화 근거, 과탐 위험, 시험 계획). 평가 측 회신 전에는 탐지 코드를 쓰지 않는다.
   틀: 적용 배제 대상(법정 기간·요건·면책 규정의 닫힌 집합, 조문 번호 열거 금지) + 배제 근거 유형(정의·형평·자연법·유추·준용·상위 규범)
       + 범주적 표현 + 요건 논의 부재. 법이 정한 예외(시효 중단·정지 사유 등)를 정확히 원용한 서면은 알리지 않는다(대조군).
       TK-45 원칙: 낱말 위치 일치 금지, 절·극성 구조로 판정.
 - 브랜치 codex/tk24-statutory-period-exclusion. 관련 시험 기준값(구현 전):
   tests/test_tk20_unreasonable_argument_cluster.py tests/test_v4_g4_reasoning_axis.py tests/test_verification_regressions.py
   tests/test_v2_phase1_verdicts.py tests/test_efficacy_round2.py tests/test_v5_claim_polarity.py tests/test_ground_truth_prepared_brief.py
   tests/acceptance/test_generalization_guards.py tests/acceptance/test_round5_regressions.py tests/acceptance/test_variant_generalization.py
   tests/acceptance/test_case9_state_compensation.py → 310 passed, 2 xfailed
   tests/acceptance/test_round7_findings.py → 105 passed, 5 xfailed
 - 수용: LEG-2 2건만 XPASS(strict)로 바뀌고 그 밖 실패 0(보고에 'XPASS(strict) 외 실패 0'으로 적는다. 표시는 평가 측이 지운다).
   양성 5건(대상·근거를 바꾼 변형)·대조 3건(법정 예외를 정확히 원용) 시험. 고정 81.7/79.2/0, 기존 무리한 주장 항목과 대조군 유지.

[C] (낮음, A·B 뒤) CodeQL 로그 주입 경보 정리 — apps/api/project_purge.py 63·73행(2026-10-04 지시 그대로, 아직 미착수)
 - 실제 위험은 없다(%r 기록, 값은 DB의 프로젝트 ID·PROJECT_ID_RE 검증). CodeQL이 repr을 정화로 인식하지 않아 경보가 남는다.
 - 기록용 값을 CodeQL이 정화로 인식하는 형태로 만든다:
   도우미 하나(예: _log_id(v) = str(v).replace("\r", "").replace("\n", "")[:40])를 63·73행과 routers/projects.py의 project_purge_retry 로그에 쓴다.
   동작·메시지 형식은 바꾸지 않는다.
 - 브랜치 codex/codeql-purge-log, 커밋 1개. 관련 시험: tests/test_project_lifecycle.py tests/test_storage_encryption.py.
   경보 해소는 릴리스 PR(main 대상)의 CodeQL에서 확인한다.

각 항목은 따로 Steve_ACASiaLAW 대상 PR로 올리고, CI가 끝난 뒤 '검토 요청'을 남긴다. 병합은 사용자가 한다.
```

## 평가 측 메모(전달하지 않는다)
- RAG-2(Drive 대조 모순을 finding 목록에 올림)는 넘기지 않았다. 사용자 결정 D4('참고자료 대조 의견은 승격하지 않는다', PROMPT_FOR_F3 1절)와 정면으로 충돌하기 때문이다. D4를 바꿀지 사용자 결정을 먼저 받는다.
- TK-45 잔여(요건 부정 변형 미탐)는 이번 결정 범위(LEG-2·PII-K6·RAG-2) 밖이라 넘기지 않았다.
