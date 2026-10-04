# 7차 보완 작업 지시서 — 7차 독립 측정에서 확인된 회귀·미해결만 고친다 (구현 담당 에이전트)

> **갱신(2026-10-03):** 이 지시서의 후속은 [PROMPT_FOR_STABILIZATION_ROUND7C.md](PROMPT_FOR_STABILIZATION_ROUND7C.md)다. 이 문서의 R7-C ①('완화를 성명 표지에 한정')은 반대 방향(유출) 시험 없이 적은 평가 측 오류여서 7C가 정정한다. 7C는 이 지시서의 0.2 보고 규칙·CI 기준을 이어받는다.

작성: 평가 에이전트(claude-code) 2026-10-03 · 근거: [f1_gate_verdict.md](../scorecards/f1_gate_verdict.md), [HISTORY 12절](../scorecards/HISTORY.md), 티켓 TK-42~45. 아래 전체를 붙여 넣어 쓴다. 7차 지시서(`PROMPT_FOR_STABILIZATION_ROUND7.md`)의 0.3 보고 규칙·3절 설계 원칙·4절 금지 행위·5절 검증 명령은 **그대로 유효**하다.

## 0. 성격
**새 기능·새 규칙·새 `rule_id`·새 설정 파일 동결.** 고치는 곳은 R7-A~R7-E뿐이다. 시험에 맞추려고 **낱말 목록·분기를 더하지 않는다**(이번에 확인된 문제의 원인이 그것이다). 평가 측 비공개 변형(저장소 밖)으로 다시 측정한다 — 보호 시험의 입력에만 맞으면 통과하지 못한다.

### 0.1 시작
1. 구현 브랜치 `4da3910`에서 시작해 `Steve_ACASiaLAW` 최신을 **구현 브랜치에 병합**한다(평가 측 새 보호 시험·티켓을 받기 위한 것이며 충돌은 `docs/`뿐일 것으로 예상한다). `git config core.autocrlf input`, 강제 푸시 금지.
2. 알려진 시작 상태(병합 직후): `tests/acceptance`에서 **51건이 XPASS(strict)로 실패**(6차 회귀 40·보안 11 — 평가 측이 표시를 지울 몫이라 이번에도 그대로 둔다), `tests/acceptance/test_round7_findings.py` 일반 시험 **23건 실패**(TK-42 1·TK-43 12·TK-46 6·TK-45 3·TK-44 불변성 1)와 strict xfail 18건(TK-44 5·TK-43 어휘 8·TK-45 미탐 4·TK-37 동작 1), `tests/regression` 원장 **2건 실패**, 브라우저 시험 다수 실패. 이 목록 밖의 새 실패는 만들지 않는다.

### 0.2 이번 라운드의 보고 규칙 (7차 0.3에 더해)
1. **전체 시험을 끝까지** 돌린다 — `pytest -q --ignore=tests/acceptance`에 **브라우저 시험이 포함**된다(Playwright). 로컬(Windows)에서 못 돌리면 **푸시 뒤 `CI` 테스트 job의 결론**을 적는다. 7차 보고서는 전체 시험 기록 없이 "새 실패 0"이라 적었고 실제로는 원장 2건·브라우저 시험이 실패했다.
2. **커밋마다 `python -m pytest -q tests/regression`**(약 4초). 화면 스크립트(`apps/web/static/*.js`)를 건드린 커밋은 `pytest tests/test_frontend_*.py tests/test_analysis_completion.py tests/test_reasoning_layout.py tests/test_drive_rag_relevance.py`(197건)까지.
3. **보고서의 파일 경로·식별자는 `git diff --stat`과 코드에서 복사한다.** 존재하지 않는 경로(`packages/llm_gateway/router.py`)·식별자(`STATED_REQUIREMENTS_RE` 등)를 쓰지 않는다. 바꾸지 않은 파일을 바꿨다고 쓰지 않는다.
4. `점수 게이트`·`CI`의 **job 결론과 단계별 결과**를 푸시 뒤에 적는다(자기 SHA의 결과를 보고서에 담을 수 없으면 "푸시 후 확인"이라 쓰고, 다음 커밋이나 요청서에서 채운다).

## 1. 작업 묶음 (묶음마다 커밋. **P1 먼저**: R7-A → R7-C의 TK-46 → R7-D → R7-B → R7-C의 TK-43 → R7-E → R7-F)

### R7-A. TK-42 관리자 화면 선언 복구 (P1, 첫째)
`apps/web/static/admin.js`에서 지워진 `let ready = false, initialized = false, previousHash = "";` 한 줄을 되살린다([TK-42](TK-42_admin_js_declaration_deleted.md)). 다른 변경 금지. 이 예외는 `app.js` 끝의 순차 `init()` 호출 전체와 프로젝트 조회를 막으므로(독립 감사 A7-06) 관리자 화면만의 문제가 아니다. 브라우저 시험 197건 통과를 보고한다. 보안 하드닝(S5)의 나머지(`Object.hasOwn`·`Object.create(null)`·`Number(year)`)는 유지한다.

### R7-B. TK-44 줄 결합 구조화·원장 복구 (P2)
[TK-44](TK-44_line_join_word_lists_and_ledger_regression.md) 요구 1~3. `PAREN_DETERMINERS`·`STANDALONE_WORDS` 낱말 목록으로 판정하지 않는다 — 줄 끝 위치·글자 간격·**문단의 줄들**의 폭 분포로 판정하고 신호가 없으면 불확실로 보존한다. 원장 2건 복구, `right_edge`·`prev_full`도 문단 국소. 시험은 **3종 세트**(목록 밖 낱말 포함, 양방향, 실제 PDF 경로).

### R7-C. TK-46(P1) 명시 성명 stem 제외 + TK-43 라벨 완화 범위·어휘 확대
**먼저 [TK-46](TK-46_explicit_name_stem_stopword_exclusion.md)(P1):** `성명: 임용은`처럼 끝 음절이 조사로 보이고 앞부분이 일반 불용어인 명시 성명이 통째로 제외된다. 명시 성명 후보 전체를 stem 불용어 검사 전에 보존하고(이름 하나를 예외로 넣지 않는다), 마스킹과 전송 전 검사가 같은 구조 결과를 쓴다. 이어서 [TK-43](TK-43_explicit_label_relaxation_overreach.md) 요구 1~4. ① `is_explicit_label` 완화를 **성명 표지**에 한정하거나 이름 구조 판정으로 바꿔 `{당사자 라벨} 진술 조서는`류 과마스킹을 없앤다. ② **사용자가 라벨 어휘 확대를 승인했다(2026-10-03)** — 법률문서에서 사람을 지칭하는 범주(성명 직접 표지·작성/담당/진술 관계인·거래 당사자와 대리 관계·가족/보호 관계) 전체를 닫힌 목록으로 추가한다. 보호 시험에는 대표 라벨 4개만 있으므로 4개에만 맞추지 않는다(평가 측이 같은 범주의 다른 낱말로 재측정). 새 라벨 뒤 일반 명사 오탐 0. R6-01 마스킹·라우터 시험 30건 XPASS와 이름 1,000조합 유지.

### R7-D. TK-45 법리 판정 구조화 (**P1**)
[TK-45](TK-45_defense_negation_by_word_match.md) 요구 1·2. 요건 충족 서술의 부정어(`지체하지 않고` 등)를 요건 부정으로 읽지 않고, 요건을 `~한 적/사실이 없으나`로 부정한 한정 결론(독립 감사 A7-02)에서 경고를 유지한다. 시험은 **요건 부정·인용·상대방 주장·재반박 각 2건 이상**(현재 원장의 '재반박'은 라벨뿐이다)과 반대 방향·이전 성공 대조, 실제 TXT → `VerificationPipeline.run` 경로까지. 불확실하면 경고를 지우지 않고 '요건 확인 요청'으로 낮춘다. **감사 표본 5건의 해소 여부를 보고**(해소 못 하면 사유). R6-02 보호 시험 유지.

### R7-E. 보고 정정과 7차 R4 누락 항목
`docs/handoff/requests/24_round7b_completion.md` 하나에: ① 7차 보고서 정정 절(존재하지 않는 경로·식별자, "기존 시험 새 실패 0", "배치 불변성 확립", job 결과 누락) ② R4 요구 보고: 기존 `0o444` 원본의 이행 제안(기동 시 점검·마이그레이션), `record_storage_encryption_error` 값이 관리자 전용 진단에만 보이는지, `admin.js`에서 해시·API 값으로 객체를 조회하는 곳 점검, S1 바꾸기 전후 시간 표 ③ 폭 40 INJ-1 해소 또는 미해결 표기 ④ 7차 보고서의 '완전 방어'(표본 입력 통과를 일반화)와 6차 표현 '전수 보존'·'공급자 0회 보장'의 정정(검증한 입력 집합·경로를 적는다) ⑤ 정규식은 평가 측이 Linux에서 지수 증가 0건을 실측했으나 증명은 아니라는 점을 반영(Windows에서 `probe_regex_complexity.py`는 `SIGALRM`이 없어 못 돈다 — 평가 측 몫).

### R7-F. TK-47 F1 설계 문서를 현행 모델에서 다시 작성 (P2, 문서만)
[TK-47](TK-47_f1_design_prep_not_tied_to_current_model.md). `docs/handoff/requests/22_f1_design_prep.md`를 현행 코드에서 출발해 다시 쓴다(코드·DB·API 변경 금지): `FindingType` **97개 전수 목록**과 화면 배정(미배정 시 실패하는 시험 제안), 기존 JSON·화면 필드 대응과 보존 경로, 현행 `FindingWorkflow`(`apps/api/workspace.py`)·`ReviewDraft`·`ReviewRevision`·기존 `/workflow` API를 보존하는 검토 상태 비교안, F3 청구 단위 호출 수·상한·캐시·실패·예산 초과 처리, 참고자료 발췌가 현행 `packages/pii_engine/detector.py::detect`·`PIIEngine`(`packages/pii_engine/engine.py`) 마스킹·`packages/llm_router/privacy.py::inspect_request`·`LLMRouter.run`을 지나는 정확한 경로(※ 이 지시서 초판의 `PIIDetector`는 평가 측이 잘못 적은 이름이며 코드에 없다 — 7C 지시서에서 정정), `LOCAL_ONLY` 외부 호출 0 시험 위치. 가공의 타입 이름·새 원문 열람 권한을 쓰지 않는다.

## 2. 수용·완료의 정의
- `tests/regression` 전부 통과, 브라우저 시험 197건 통과, `test_round7_findings.py` 일반 시험 전부 통과(strict xfail 줄 결합 5건은 구조 판정이 되면, 라벨 어휘 8건은 어휘 확대 뒤 XPASS — requests로 알린다), 51건 XPASS 유지, 새 실패 0(전체 시험·CI 결론으로 증빙).
- 고정 dev ≥ 81.7·holdout ≥ 79.2·오탐 0, 회귀 게이트 종료 코드 0, 하드코딩 강한 신호 0, 작업 커밋 버전 불변, 새 `rule_id` 0.
- **CI 기준 정정(독립 감사 Astra 지적 수용):** `점수 게이트`의 수용 시험 단계와 `CI`의 `pytest -q`는 `tests/acceptance`를 포함하므로 strict xfail 표시가 남아 있는 동안 완료된 제품도 XPASS(strict)로 실패한다. 구현 측의 완료는 **'XPASS(strict) 외 실패 0'** — 같은 SHA에서 두 workflow의 모든 단계를 적고 실패는 XPASS뿐임을 로그로 보인다. `CI` 테스트 job은 20분 안에 끝나야 한다. 평가 측이 독립 검증 뒤 표시를 승격한 커밋에서 같은 코드로 전 단계 초록을 확인한다(7차 지시서 8절의 '같은 SHA 전 단계 성공'은 이 정정으로 대체).
- Docker OCR readiness 성공.
- 평가 측 비공개 변형 재측정: 이름(라벨 어휘 안) ≥ 95%·정상 문장 오탐 시작 대비 증가 0, 법리 정상 항변 새 오탐 0, 줄 결합 목록 밖 쌍·쪽 배치 불변성.
- 7차 보완 완료는 **F1 착수 승인이 아니다.** 평가 측 재측정 → 독립 감사(G8) → '행위시법 검토 보강' → F1 직전 재측정 → 판정 → 사용자 승인이 이어진다.
