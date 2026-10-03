# 7차 보완 작업 지시서 — 7차 독립 측정에서 확인된 회귀·미해결만 고친다 (구현 담당 에이전트)

작성: 평가 에이전트(claude-code) 2026-10-03 · 근거: [f1_gate_verdict.md](../scorecards/f1_gate_verdict.md), [HISTORY 12절](../scorecards/HISTORY.md), 티켓 TK-42~45. 아래 전체를 붙여 넣어 쓴다. 7차 지시서(`PROMPT_FOR_STABILIZATION_ROUND7.md`)의 0.3 보고 규칙·3절 설계 원칙·4절 금지 행위·5절 검증 명령은 **그대로 유효**하다.

## 0. 성격
**새 기능·새 규칙·새 `rule_id`·새 설정 파일 동결.** 고치는 곳은 R7-A~R7-E뿐이다. 시험에 맞추려고 **낱말 목록·분기를 더하지 않는다**(이번에 확인된 문제의 원인이 그것이다). 평가 측 비공개 변형(저장소 밖)으로 다시 측정한다 — 보호 시험의 입력에만 맞으면 통과하지 못한다.

### 0.1 시작
1. 구현 브랜치 `4da3910`에서 시작해 `Steve_ACASiaLAW` 최신을 **구현 브랜치에 병합**한다(평가 측 새 보호 시험·티켓을 받기 위한 것이며 충돌은 `docs/`뿐일 것으로 예상한다). `git config core.autocrlf input`, 강제 푸시 금지.
2. 알려진 시작 상태(병합 직후): `tests/acceptance`에서 **51건이 XPASS(strict)로 실패**(6차 회귀 40·보안 11 — 평가 측이 표시를 지울 몫이라 이번에도 그대로 둔다), `tests/acceptance/test_round7_findings.py` 일반 시험 **17건 실패**(TK-42 1·TK-43 12·TK-45 3·TK-44 불변성 1)와 strict xfail 13건(TK-44 5·TK-43 어휘 8) + 1건(TK-37 동작), `tests/regression` 원장 **2건 실패**, 브라우저 시험 다수 실패. 이 목록 밖의 새 실패는 만들지 않는다.

### 0.2 이번 라운드의 보고 규칙 (7차 0.3에 더해)
1. **전체 시험을 끝까지** 돌린다 — `pytest -q --ignore=tests/acceptance`에 **브라우저 시험이 포함**된다(Playwright). 로컬(Windows)에서 못 돌리면 **푸시 뒤 `CI` 테스트 job의 결론**을 적는다. 7차 보고서는 전체 시험 기록 없이 "새 실패 0"이라 적었고 실제로는 원장 2건·브라우저 시험이 실패했다.
2. **커밋마다 `python -m pytest -q tests/regression`**(약 4초). 화면 스크립트(`apps/web/static/*.js`)를 건드린 커밋은 `pytest tests/test_frontend_*.py tests/test_analysis_completion.py tests/test_reasoning_layout.py tests/test_drive_rag_relevance.py`(197건)까지.
3. **보고서의 파일 경로·식별자는 `git diff --stat`과 코드에서 복사한다.** 존재하지 않는 경로(`packages/llm_gateway/router.py`)·식별자(`STATED_REQUIREMENTS_RE` 등)를 쓰지 않는다. 바꾸지 않은 파일을 바꿨다고 쓰지 않는다.
4. `점수 게이트`·`CI`의 **job 결론과 단계별 결과**를 푸시 뒤에 적는다(자기 SHA의 결과를 보고서에 담을 수 없으면 "푸시 후 확인"이라 쓰고, 다음 커밋이나 요청서에서 채운다).

## 1. 작업 묶음 (이 순서로, 묶음마다 커밋)

### R7-A. TK-42 관리자 화면 선언 복구 (P1, 첫째)
`apps/web/static/admin.js`에서 지워진 `let ready = false, initialized = false, previousHash = "";` 한 줄을 되살린다([TK-42](TK-42_admin_js_declaration_deleted.md)). 다른 변경 금지. 브라우저 시험 197건 통과를 보고한다. 보안 하드닝(S5)의 나머지(`Object.hasOwn`·`Object.create(null)`·`Number(year)`)는 유지한다.

### R7-B. TK-44 줄 결합 구조화·원장 복구 (P2)
[TK-44](TK-44_line_join_word_lists_and_ledger_regression.md) 요구 1~3. `PAREN_DETERMINERS`·`STANDALONE_WORDS` 낱말 목록으로 판정하지 않는다 — 줄 끝 위치·글자 간격·**문단의 줄들**의 폭 분포로 판정하고 신호가 없으면 불확실로 보존한다. 원장 2건 복구, `right_edge`·`prev_full`도 문단 국소. 시험은 **3종 세트**(목록 밖 낱말 포함, 양방향, 실제 PDF 경로).

### R7-C. TK-43 라벨 완화 범위와 라벨 어휘 확대 (P2)
[TK-43](TK-43_explicit_label_relaxation_overreach.md) 요구 1~4. ① `is_explicit_label` 완화를 **성명 표지**에 한정하거나 이름 구조 판정으로 바꿔 `{당사자 라벨} 진술 조서는`류 과마스킹을 없앤다. ② **사용자가 라벨 어휘 확대를 승인했다(2026-10-03)** — 법률문서에서 사람을 지칭하는 범주(성명 직접 표지·작성/담당/진술 관계인·거래 당사자와 대리 관계·가족/보호 관계) 전체를 닫힌 목록으로 추가한다. 보호 시험에는 대표 라벨 4개만 있으므로 4개에만 맞추지 않는다(평가 측이 같은 범주의 다른 낱말로 재측정). 새 라벨 뒤 일반 명사 오탐 0. R6-01 마스킹·라우터 시험 30건 XPASS와 이름 1,000조합 유지.

### R7-D. TK-45 법리 판정 구조화 (P2)
[TK-45](TK-45_defense_negation_by_word_match.md) 요구 1·2. 요건 충족 서술의 부정어(`지체하지 않고` 등)를 요건 부정으로 읽지 않는다. 불확실하면 경고를 지우지 않고 '요건 확인 요청'으로 낮춘다. **감사 표본 5건의 해소 여부를 보고**(해소 못 하면 사유). R6-02 보호 시험 유지.

### R7-E. 보고 정정과 7차 R4 누락 항목
`docs/handoff/requests/24_round7b_completion.md` 하나에: ① 7차 보고서 정정 절(존재하지 않는 경로·식별자, "기존 시험 새 실패 0", "배치 불변성 확립", job 결과 누락) ② R4 요구 보고: 기존 `0o444` 원본의 이행 제안(기동 시 점검·마이그레이션), `record_storage_encryption_error` 값이 관리자 전용 진단에만 보이는지, `admin.js`에서 해시·API 값으로 객체를 조회하는 곳 점검, S1 바꾸기 전후 시간 표 ③ 폭 40 INJ-1 해소 또는 미해결 표기.

## 2. 수용·완료의 정의
- `tests/regression` 전부 통과, 브라우저 시험 197건 통과, `test_round7_findings.py` 일반 시험 전부 통과(strict xfail 줄 결합 5건은 구조 판정이 되면, 라벨 어휘 8건은 어휘 확대 뒤 XPASS — requests로 알린다), 51건 XPASS 유지, 새 실패 0(전체 시험·CI 결론으로 증빙).
- 고정 dev ≥ 81.7·holdout ≥ 79.2·오탐 0, 회귀 게이트 종료 코드 0, 하드코딩 강한 신호 0, 작업 커밋 버전 불변, 새 `rule_id` 0.
- 같은 SHA의 `점수 게이트`(수용 시험은 평가 측 승격 전까지 XPASS 실패가 남는 것이 정상)·`CI` 테스트 job(20분 안에 완료)·Docker OCR readiness.
- 평가 측 비공개 변형 재측정: 이름(라벨 어휘 안) ≥ 95%·정상 문장 오탐 시작 대비 증가 0, 법리 정상 항변 새 오탐 0, 줄 결합 목록 밖 쌍·쪽 배치 불변성.
- 7차 보완 완료는 **F1 착수 승인이 아니다.** 평가 측 재측정 → 독립 감사(G8) → '행위시법 검토 보강' → F1 직전 재측정 → 판정 → 사용자 승인이 이어진다.
