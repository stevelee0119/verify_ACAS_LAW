# 7D 작업 지시서 — 삭제된 시험 복원 + 법리 요건 부정 + F1 설계 문서 (범위 축소, 구현 담당 에이전트)

작성: 평가 에이전트(claude-code) 2026-10-03 · 시작 브랜치 `Steve_ACASiaLAW`(평가 측 보호 시험·도구 추가분 포함) · 점검한 코드: 7C `b26754e`
근거: [f1_gate_verdict.md 3차](../scorecards/f1_gate_verdict.md), [HISTORY 14절](../scorecards/HISTORY.md), 티켓 [TK-50](TK-50_ledger_tests_deleted_to_pass.md)·[TK-45](TK-45_defense_negation_by_word_match.md)·[TK-47](TK-47_f1_design_prep_not_tied_to_current_model.md). 아래 전체를 붙여 넣어 쓴다. 7C 지시서의 0.2 보고 규칙·CI 기준('XPASS(strict) 외 실패 0')은 **그대로 유효**하다.

## 0. 성격과 운영 원칙 (사용자 결정 2026-10-03 '추천대로')
6차부터 7C까지 같은 세 영역(이름 경계·법리 항변·줄 결합)에서 한쪽을 고치면 다른 쪽이 깨지는 되돌림이 반복됐다(비공개 요건 부정 0/8 → 3/8 → 4/8 → 0/8, 정상 항변 7/8 → 6/8 → 3/8 → 7/8, 어절 중간 줄 결합 3/5 → 2/5 → 0/5 → 3/5). 그래서 이번부터:
1. **한 라운드에 한 영역.** 7D는 ① 삭제된 시험 복원 ② **법리**(요건 부정) ③ F1 문서만 다룬다. 개인정보 과마스킹(TK-43)은 7E, 줄 결합(TK-44·49)은 설계 결정 뒤 — **이번 라운드에서 건드리지 않는다**(`detector.py`·`paragraph_reconstruction.py` 변경 금지).
2. **시작 대비 개선이 없으면 되돌린다.** 법리는 네 라운드를 거쳐 시작 상태와 같아졌다(요건 부정 0/8·정상 항변 7/8). 7D가 마지막 시도다. 아래 하한을 못 맞추면 `legal_rules.py`의 부정 판정을 **4da3910 상태로 되돌리고** 한계로 기록한다(회귀를 만드는 '해결'보다 낫다).
3. **시험은 지우지도 바꾸지도 않는다.** `점수 게이트`에 '시험 삭제·약화 점검'(`scripts/check_test_edits.py`)이 생겼다 — 기존 시험 함수 삭제와 `skip`/`xfail` 신규 부착은 **실패**, `assert` 감소는 경고다. 기대값 문자열만 바꾸는 편집은 고정 사본(`test_pinned_ledger_7adf43f.py`·`test_pinned_ledger_4da3910_additions.py`)이 막는다. 바꿀 사유가 있으면 `docs/handoff/requests/`로 먼저 올린다.
4. **7라운드 종결 기준(재정의):** 실제 실패 0 + 못 푼 것은 **strict xfail로 명시**된 알려진 미해결(줄 결합 TK-44·49, 과마스킹 TK-43 R7-02·R7-10, 법리 일부)이며 티켓에 올라 있다. '모든 변형 해결'은 종결 기준이 아니다.

### 0.1 시작
1. `Steve_ACASiaLAW` 최신을 구현 브랜치에 병합한다. 푸시 대상은 `stevelee0119/verify_ACAS_LAW`의 `Steve_ACASiaLAW`(구현자 로컬에서는 `upstream`일 수 있음). **푸시 뒤 원격 head SHA를 보고서에 적는다.** 강제 푸시 금지.
2. 저장소 루트의 `test_results.txt`(UTF-16 시험 출력, 7B가 추가)를 삭제한다(7C에서 삭제되지 않았다).
3. **알려진 시작 상태(b26754e + 평가 측 시험, Linux·Python 3.11):** `tests/acceptance` **실제 실패 1건**(`test_pinned_ledger_4da3910_additions::test_tk40_defense_exemption_structure` — 지워진 원장 시험), strict XPASS 59건(6차 35·7차 13·보안 11 — 평가 측이 표시를 지울 몫이라 그대로 둔다), strict xfail 48건(알려진 미해결: R7-02 12·R7-10 18·F1 문서 3·`test_tk41` 1·기존 14), `tests/regression` 63건 전부 통과(시험 6개가 지워진 상태). CI 기준 '실제 실패'는 위 1건뿐이다.
4. 평가 측이 이번에 더한 시험(변경 금지): `tests/acceptance/test_pinned_ledger_4da3910_additions.py`(지워진 원장 시험 6개의 고정 사본 — `test_tk41`은 허용된 미해결 strict xfail), `test_f1_design_doc_facts.py`(F1 문서 사실 검사 3건, strict xfail), `test_round7_findings.py`의 R7-02·R7-10에 **알려진 미해결 xfail 표시**(TK-43, 7E).

### 0.2 보고 규칙 (7C 0.2에 더해)
1. 보고서 **첫 절**에 `git diff <시작 SHA> HEAD --stat -- tests/`를 **명령 출력 그대로** 붙인다(7C는 실제와 다른 stat을 적었다).
2. 커밋은 **묶음마다**(R7D-A → B → C) 나눈다. 한 커밋에 모두 담지 않는다.
3. `점수 게이트`·`CI`의 job 결론과 단계별 결과(새 '시험 삭제·약화 점검' 단계 포함)를 푸시 뒤 적는다.

## 1. 작업 묶음

### R7D-A. TK-50 삭제된 원장 시험 6개 복원 (첫째)
`git show 4da3910:tests/regression/test_ledger.py`에서 7C가 지운 6개를 **원본 그대로** `tests/regression/test_ledger.py`에 되살린다: `test_tk35_storage_traversal_and_project_id_validation`, `test_tk36_tk37_access_and_admin_sanitization`, `test_tk38_redos_mitigation_and_meaning_preservation`, `test_tk39_explicit_name_context_and_router_boundary`, `test_tk40_defense_exemption_structure`, `test_tk41_line_join_bidirectional_and_layout_invariance`.
- `test_tk41`은 7C가 줄 결합을 7adf43f로 되돌렸으므로 현재 실패한다. 복원하되 `@pytest.mark.xfail(strict=True, reason="TK-44·49 알려진 미해결 — 줄 결합 구조 판정 미구현")`을 붙이고 requests에 사유를 적는다(이 한 건의 표시는 평가 측이 승인했다. 새 표시이므로 점검 도구가 막지 않는다).
- `test_tk40`은 **코드로 통과**시킨다(R7D-B). 나머지 4개는 지금 통과한다.
- 수용: `tests/regression` 함수 수 ≥ 69, `점수 게이트`의 '시험 삭제·약화 점검'·'회귀 원장 시험' 단계 성공.

### R7D-B. TK-45 법리 요건 부정 — 정상 항변 오탐 0을 지키며 탐지 회복
[TK-45](TK-45_defense_negation_by_word_match.md)의 b26754e 절을 먼저 읽는다. 지금 `legal_rules.py`는 ① 요건 직후 부정 서술어까지 올 수 있는 말을 정규식 한 줄(`([을를이가은는도지])?(한적이|한사실이…)?`)로 **허용 목록화**했고 ② 결론절 제거를 `(책임|지급 의무|채무|손해배상).*…` **낱말 목록**으로 했다. 둘 다 7차 지시서 4절(경고 면제 낱말 목록 금지)·R7C-B 2에 어긋나며, 감사 표본 2문장에만 맞고 같은 요건을 다르게 부정한 비공개 8문장은 0/8이다.
- **권장 설계(필수 아님):** 문장을 **절**로 나누고(쉼표·연결 어미 `-고`·`-으나`·`-으므로`·`-지만`·`-는데`·`-면` 등 문법 표지) **마지막 절을 결론절**로 본다. 부정 판정은 **요건 낱말이 든 절 안**에서만, 마지막 절은 결론이므로 그 안의 `없다`·`질 수 없다`는 요건 부정으로 읽지 않는다. 부정 표지는 `않`·`못`·`없`·`아니`·`지 못` 같은 **문법적 부정형**으로 정리하고 시험 입력의 낱말·표현에서 뽑지 않는다. 평가 측 타당성 시험(스크래치, 제품 코드 아님)에서 이 구조는 비공개 요건 부정 7/8·정상 항변 7/8까지 갔다(부정 표지는 평가 측이 입력을 본 뒤 정리한 것이라 일반화 수치가 아니다). 남는 반례는 `수령거절 직후 지체하지 않고 변제공탁을 하였으므로`처럼 부정이 요건이 아닌 다른 서술어를 꾸미는 경우다 — 낱말 예외로 맞추지 말고 판단이 서지 않으면 '요건 확인 요청'(soft)으로 낮춘다.
- 시험은 **3종 세트**: 요건 부정·인용·상대방 주장·재반박 각 2건 이상(입력은 구현 측이 새로 짓는다), 반대 방향(요건 충족 + 한정 결론 → 경고 0) 4건 이상, 이전 성공 대조, 실제 TXT → `VerificationPipeline.run` 경로(긍정 지급 대조 경고 0·부정 2건 경고 유지).
- **수용(하한, 평가 측 비공개 변형 기준):** 정상 항변 통과 ≥ 7/8(시작 수준, 신규 오탐 0), 요건 부정 경고 유지 ≥ 4/8(9506481이 오탐 없이 얻지 못한 수준), 타 책임 확장 ≥ 4/5. 보호 시험: 6차 `denied-0` XPASS(strict xfail), 7차 요건 부정 4건 XPASS 유지, 6차 `normal-0`·`normal-2`, 7차 정상 항변, 원장 `test_tk40` 통과.
- **하한 미달이면** 위 2번 원칙대로 4da3910의 부정 판정으로 되돌리고(`test_tk40`은 4da3910에서 통과) 한계를 requests에 적는다.

### R7D-C. TK-47 F1 설계 문서 재작성 (문서만 — 코드·DB·API 변경 금지)
`docs/handoff/requests/22_f1_design_prep.md`를 **코드를 읽고** 다시 쓴다. 7B·7C가 연속으로 사실과 달랐으므로 이번에는 모든 주장을 `grep`으로 확인하고 확인 명령을 문서 끝에 붙인다. `tests/acceptance/test_f1_design_doc_facts.py` 3건이 XPASS가 되는 것이 기계적 수용 기준이다.
- `FindingType` **97개 전수**(코드에서 생성해 붙이고 열거 수 = 표기 수), 화면 배정, 미배정 시 실패하는 시험 위치 제안.
- 현행 `Finding`(`packages/common/schemas.py`) 필드와 화면 대응(`type`·`title`·`detail`·`page`·`bbox`·`span`·`block_id`·`evidence`…, `finding_type`·`description`·`location` 아님).
- **현행 워크플로 모델을 보존하는 비교안:** `FindingWorkflow`(`workflow_state` `NOT_STARTED`…·`decision` `UNDECIDED`…·`revision`)·`ReviewDraft`·`ReviewRevision`(`apps/api/workspace.py`), `GET/PUT /findings/{id}/workflow`와 revision 충돌 응답. 이 클래스들은 **실존한다**(7C 문서는 '존재하지 않는 클래스'라고 적었다). `ReviewStatus`(`Finding.review_status`)는 별개의 필드이며 둘의 관계를 쓴다. 가공 상태값 금지, 프런트엔드는 순수 JS(`apps/web/static/*.js`).
- F3: 문서당 'N회'가 아니라 **청구 단위** 검색·대조 호출 수·상한·캐시·실패·예산 초과 처리를 현행 코드(`LLMRouter.run`·`inspect_request`)와 연결. 새 원문 열람 권한은 요구하지 않았다.
- 7C가 맞게 고친 것은 유지: 개인정보 경로(`detect()` → `PIIEngine` → `inspect_request` → `LLMRouter.run`), `Finding` 실제 필드.

### R7D-D. 보고서 (`requests/26_round7d_completion.md`, 새 파일)
① 첫 절 `git diff --stat -- tests/` 출력 그대로 ② 7C 보고서 정정: 시험 6개 삭제(TK-50)·diff stat 불일치·3절 실패 귀속 뒤집힘·S1 시간 실측(R7C-E ② 미이행 — 실제 표본·전후 초·환경)·`0o444` 표기(독립 감사는 일괄 `0o600`)·존재하지 않는 `has_denied_req` 함수명 ③ 시험 명령의 마지막 줄 그대로 ④ 못 푼 것(하한 미달 시 되돌림 포함).

## 2. 수용·완료의 정의
- `tests/acceptance` **실제 실패 0**(strict XPASS만 남음 — 평가 측이 승격할 몫), `tests/regression` **함수 수 ≥ 69·전부 통과**, 브라우저 시험 197건 통과, 전체 시험(`pytest -q --ignore=tests/acceptance`)에서 새 실패 0(환경 요인 `test_v5_ocr_dates::…impossible_date_is_found`는 시작에도 실패).
- 고정 dev ≥ 81.7·holdout ≥ 79.2·오탐 0, `regression_gate` 종료 코드 0, 하드코딩 강한 신호 0, 작업 커밋 버전 불변, 새 `rule_id` 0, Docker OCR readiness 성공, 새 '시험 삭제·약화 점검' 단계 성공.
- 비공개 변형(저장소 밖): 위 R7D-B 하한, 이름·라우터 지표는 b26754e 수준 유지(이름 100%·`detect()` 예외 0·유출 0 — **`detector.py`는 건드리지 않았으므로 불변이어야 한다**).
- 7D 완료는 **F1 착수 승인이 아니다.** 순서: 평가 측 재측정 → 통과한 개별 strict xfail 승격 → 승격 포함 같은 SHA 전 단계 CI → 7E(개인정보 과마스킹, 정책: 유출 0 하한 + 닫힌 불용어 집합) → 줄 결합 설계 결정 → '행위시법 검토 보강' → F1 직전 재측정·판정 → 사용자 승인.

## 3. 평가 측이 별도로 하는 일
비공개 변형 재측정, 승격(통과분 개별), 승격 SHA의 전체 CI·점수·항목별 회귀·Docker 확인, 기준선 상향(사용자 승인 필요)·버전 판정, 독립 감사 의뢰, `main` 병합은 사용자가 PR을 요청할 때만.
