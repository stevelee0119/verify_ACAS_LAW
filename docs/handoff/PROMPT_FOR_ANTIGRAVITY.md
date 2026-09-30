# Antigravity 작업 지시서 (구현 에이전트)

작성: 평가 에이전트(claude-code) 2026-09-30 · 기준 커밋: main 4ad64a7 + 평가 체계(`Steve_ACASiaLAW`)
아래 전체를 그대로 Antigravity에 붙여 넣어 사용한다.

---

## 0. 역할과 규칙 (먼저 읽을 것)

너는 **구현 에이전트**다. 저장소 `stevelee0119/verify_ACAS_LAW`의 제품 코드(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`)를 고친다.
평가는 다른 에이전트(claude-code)가 하고, 승인은 사용자(변호사)가 한다. 작업을 시작하기 전에 다음을 읽는다.
`AGENTS.md`, `docs/AGENT_ROLES.md`, `docs/handoff/README.md`, `docs/handoff/TK-01`~`TK-12`.

**지킬 것**
1. 보호 경로는 수정하지 않는다: `tests/acceptance/**`, `tests/fixtures/**`, `scripts/eval_testset.py`, `scripts/scorecard.py`, `scripts/score_gate.py`, `scripts/probe_document.py`, `scripts/score_report.py`, `scripts/check_case_literals.py`, `scripts/review_feedback_report.py`, `docs/scorecards/**`, `.github/workflows/score-gate.yml`, `docs/AGENT_ROLES.md`, `AGENTS.md`, `CLAUDE.md`, `.github/CODEOWNERS`. 변경이 필요하면 `docs/handoff/requests/<번호>_<제목>.md`에 요청을 적는다(평가 에이전트가 검토해 반영한다).
2. **사건 고유 값(당사자명·사건번호·금액·수치), 서면 문구(한글 열 글자 이상 그대로 따온 것), 서면의 영문 대문자 식별자(12자 이상)를 코드에 넣지 않는다.** 숫자만 빼고 서면 문구로 정규식을 짜는 것도 맞춤 수정이다. `tests/acceptance/test_no_case_literals.py`와 `python scripts/check_case_literals.py`가 막는다.
3. 새 규칙·수정마다 **양성 예시 3건 이상, 대조군 3건 이상**을 `tests/`에 함께 낸다. 양성은 값·문구·어순·서식 중 **둘 이상이 서로 다르게** 만든다. 대조군은 "결함 요소만 뺀 같은 서면"을 우선한다.
4. 기대값만 바꿔 시험을 통과시키지 않는다. 시험을 건너뛰거나(skip) 끄지 않는다. 기준선(`docs/scorecards/baseline.json`)을 낮추지 않는다.
5. 공식 출처(국가법령정보센터 등)에서 확인하지 못한 자료는 넣지 않는다. 모르는 값은 `null`로 둔다. 지어내지 않는다.
6. 사용자에게 보이는 설명문에 확정적 비난(`허위 조작`, `날조`)을 쓰지 않는다. 불일치한 사실(서면 수치 vs 자료 수치)과 "확인 필요"만 적는다.
7. 커밋은 **원인 유형 묶음 단위**로 한다. 커밋 메시지에 게이트 출력의 점수 변화를 적고 끝에 `Agent: implementer`를 넣는다. 사용자가 지정한 브랜치에서 작업하고, 강제 푸시하지 않는다.
8. 정책을 네가 정하지 않는다. 아래 "사용자 결정 필요"는 묻는다.

---

## 1. 왜 이 작업인가 (측정 근거)

- 처음 보는 서면의 첫 점수(고치기 전 코드): 서면6 PDF 4/20·텍스트 11/20, 서면7 PDF 10/25·텍스트 16/25, 서면7 온라인 보고서 10/20. 고정 시험 점수는 9/26부터 79.9/77.3에서 움직이지 않는다(`docs/scorecards/HISTORY.md`).
- 공통 원인: **결함을 서면 한 건의 문구에 맞춰 고쳐서, 다음 서면에서 같은 결함이 다른 문구로 재발한다.** 서면6을 고친 뒤 받은 서면7도 PDF에서 14개 항목을 놓쳤고, 원인은 서면6과 달랐다.
- 최근 4개 커밋(2d0113e·894b799·73357d8·4ad64a7)은 "하드코딩 완전 제거·범용화"라고 했으나 앞의 세 커밋은 고정 시험 점수를 바꾸지 않았고, 상승분(81.7/79.2) 전부는 마지막 미러 커밋에서 나왔다. 그 미러 자료에 오류가 있다(묶음 A).
- 측정 도구는 이미 있다. 고치는 동안 스스로 잴 수 있다(아래 4절).

---

## 2. 작업 묶음 — 원인과 개선 방안 (권장 순서)

각 묶음의 자세한 증거는 `docs/handoff/TK-nn_*.md`에 있다. 여기서는 원인·방향·수용 기준만 적는다. **개선 방향은 제안이며, 수용 기준을 만족하면 구현 방식은 자유다.**

### A. 증거 계층 데이터 — 로컬 미러가 없는 값을 채우고 조문을 뭉갠다 (TK-10) ← 먼저
- **증거:** `packages/source_adapters/local_mirror.py`(4ad64a7)가 `config/legal_rules/rules.json`의 `sources`를 미러로 자동 등록한다. 34건 모두 `effective_from: "1980-01-01"`, `paragraph: "1"`(지어낸 값). 정규식 `제\s*(\d+)\s*조`가 `조의N`·`제N항`을 버려서 `군인사법 제59조의2`→제59조, `민사소송법 제202조의2`→제202조, `군인사법 제51조의2`→제51조, `헌법 제13조 제2항`·`제37조 제2항`·`민법 제398조 제2항`→기본 조문으로 등록된다. `민사소송법 제202조의2`의 `url`은 판례 페이지(`precInfoP.do?precSeq=618533`)이고 원문이 조문이 아닌 판결요지·발췌인 항목이 섞여 있다. 그 결과 `LV_ALLOW_NETWORK=0` 출력에 `"effective_from": "1980-01-01"`이 나오고 시행일 판단(`source_review.py`, `temporal_review.py`)이 그 값에 기댄다.
- **원인:** 자료 원천(`rules.json`)은 "규칙의 근거 인용"이지 조문 DB가 아닌데 조문 DB처럼 변환했고, 모르는 필드를 임의 기본값으로 채웠다.
- **개선 방향:** (1) 시행일·항을 알 수 없으면 `null`. 시행일 `null` 조문은 행위시법·처분시법 검토에서 "시행일 확인 불가"로 다루고 통과시키지 않는다. (2) `조의N`·`제N항`을 보존하거나, 보존하지 못하면 등록하지 않는다. (3) 조문 원문이 아닌 항목(판결요지 등)은 등록하지 않는다. `detail_link`는 조문 링크만. (4) 미러 출처를 "사용자 자료(공식 DB 아님)"로 표시한다(`authority: USER_REFERENCE_NOT_OFFICIAL`).
- **수용 기준:** 미러 시험 신규(가지조문 3종·항 지정 3종이 기본 조문과 섞이지 않음, 시행일 `null` 경로). `python scripts/scorecard.py && python scripts/score_gate.py` 통과. 점수가 내려가도 사유가 "부정확한 자료가 빠져서"이면 커밋 메시지에 적고 평가 에이전트에게 기준선 조정을 요청한다(네가 기준선을 낮추지 않는다).

### B. 문구·식별자 하드코딩 (TK-08, TK-03 추가 증거, TK-05)
- **증거 1 — `packages/rag_engine/exhibit_facts.py`:** 숫자는 뺐지만 서면4·5의 문구가 정규식·설명문에 남았다. `_check_percentage_attribution`(`100% 유일한 원인`, `의사의 의료과실 기여도`, 설명문 `뇌동맥류`), `_check_classification_roles`(`단독 진단용 1등급 의료기기`, `진단보조소프트웨어`), `_check_negation_contradictions`(`즉시 해고`, `N년의 유급휴가`, `대표이사 … 주도·공모`, 제목 키워드 `취업규칙|고충처리|인사위원회`), `_check_monetary_discrepancies`(제목 키워드 `노동위원회|임금|판정서`, 라벨 `합계 (최종 인정액)`). 설명문에 `망인`, `초고혈압 위기 상태`. 이 모듈을 넣은 커밋에 시험이 없다.
- **증거 2 — `packages/adversarial_engine/patterns.py` 88·92~95행:** 이전 서면의 식별자가 그대로 열거되어 있다: `SYSTEM_OVERRIDE_DIRECTIVE`, `LABOR_DISPUTE_AI_AUDITOR`, `MEDICAL_AI_AUDITOR`, `PROTECTED_WORKER_DEFENSE_PROTOCOL`, `PROTECTED_PATIENT_SAFETY_PROTOCOL`, `COMPLIANT_AND_GENUINE`, `(?:LABOR|MED)[-_]AI[-_]\d+`, `전자심판/전자감정 표준규정` 계열. 159~162행의 `[…(AUDIT|SECURITY|…)[\s_-]+(METADATA|CLEARANCE|…)]`도 서면6의 표지 어휘에 맞춘 것이다.
- **증거 3 — `config/legal_rules/rules.json`의 규칙들:** `CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS`, `CONST.BASIC_RIGHT_OVER_STATUTORY_LIMITS`, `CRIM.POST_OFFENSE_OTHER_LAW_AS_DEFENSE` 등이 서면6의 문장 틀(`…충족…위법성 조각`, `정당행위에 해당하므로…`, `…보다…우월`)에 맞춘 정규식이다. 서면7의 `정당행위이므로 위법성이 조각되어`는 어미가 달라 일치하지 않았다.
- **증거 4 — 코드 주석의 사건 정보:** `packages/pii_engine/detector.py` 314행(실명 형태의 이름), `packages/rag_engine/review.py` 185행(`갑3호증 취업규칙…`), `packages/document_engine/pdf_parser.py` 443행(사건번호). 동작에는 영향이 없으나 사건 정보가 코드에 남는다. 일반 예시(`홍길동`, `사건 20XX고단NNN`)로 바꾼다.
- **원인:** 결함을 잡는 단위를 "서면에 나온 표현"으로 잡았다. 표현이 바뀌면 재발한다. 평가 도구가 숫자·한글 문구·식별자를 잡지 못하던 구멍이 있어 그동안 통과했다(지금은 잡는다).
- **개선 방향:** (1) 표현이 아니라 **구조**를 잡는다. 예: 인젝션은 "문서 본문 밖에서 검증 결과·등급·통과 여부를 정하려는 형식"(대괄호·주석 머리표 + 대문자 식별자 + 지시·통과·면제 계열 어휘 + 문서 경계 위치)으로, 서증 대조는 "같은 종류의 수치(금액·비율·등급)가 서면과 자료에서 다르다"는 구조로. (2) 식별자·기관명·제목 키워드 열거를 지운다. (3) 규칙마다 변형 시험(3.절)을 붙인다. (4) 주석의 사건 정보를 지운다.
- **수용 기준:** `python scripts/check_case_literals.py` 새 위반 0, `tests/acceptance/literal_debt.json`의 부채(patterns.py 식별자 6개, exhibit_facts 문구 1개) 소멸(부채 정리는 평가 에이전트가 하고, 위반이 사라지면 시험이 통과한다). 서면7 INJ-1·LEG-1·LEG-2 일부가 이 묶음과 겹친다(F 참조).

### C. 오탐 (TK-08 오탐, TK-06)
- **증거 1 — 사건과 무관한 문서가 "허위 조작" 판정을 받는다(평가 측 재현):** `check_exhibit_facts_generic`에 서면 `공유지분이 30/100`과 참고자료 `지분 50/100`을 넣으면 `CONTRADICTS` + "소장은 망인의 내원 당시 혈압이 30/100 초고혈압 위기 상태였다고 주장하나 … 소장이 수치를 허위 조작함(NUMERICAL_FRAUD)". `_check_vital_measurements`가 문맥(혈압·mmHg) 확인 없이 서면의 첫 `NN/NN`과 자료의 첫 `NN/NN`을 비교한다. 같은 식으로 제목이 `임금대장 양식 안내`인 참고자료(합계 1,000,000원)와 서면의 `미지급 임금 상당액 3,000,000원`이 "부풀려 날조된 수치임"이 된다. 이 경로(`rag_engine/review.py`의 `_check_exhibit_facts`)는 사용자 Drive의 **어떤 참고자료**와도 서면을 비교한다.
- **증거 2 — Google Docs 줄바꿈 표시가 은닉 신호로 알려진다(서면6에서 고친 것이 서면7에서 재발):** 서면7 PDF는 `ActualText <FEFF200B>`가 1쪽에 10곳이고 그중 2곳이 `UNICODE_SMUGGLING` MEDIUM으로 남는다(430543d의 예외는 "평소 공백 글리프 3회 이상, 같은 글꼴" 조건이라 서면6 글꼴 조합에 맞춰져 있다). `adversarial_manipulation_risk: MEDIUM`의 유일한 근거가 이것이다.
- **원인:** 대조기가 "주장한 수치와 자료의 수치가 같은 **대상**을 가리키는지"를 확인하지 않는다. ZWSP 예외가 글꼴이라는 우연한 조건에 묶였다.
- **개선 방향:** (1) 대조는 같은 대상일 때만(같은 문맥 어휘·단위·항목명 일치) 수행하고, 대상이 불명확하면 의견을 내지 않는다. (2) 설명문은 사실만: "서면 수치 X, 자료 수치 Y, 확인 필요". (3) ZWSP는 글꼴이 아니라 **위치·형태**로 가른다: 표시용 ActualText는 줄·문단 경계에서 글리프 없이 붙고, 은닉용은 글자 사이에 들어간다.
- **수용 기준:** 위 두 재현 입력이 더는 `CONTRADICTS`를 내지 않는다(구현자가 같은 입력으로 대조군 시험을 만든다). 서면7 pdf `FA-1` 통과, 서면6 probe 20/20 유지, 고정 시험 오탐 0·인젝션 방어 유지(진짜 ZWSP 은닉 TC-03 양성 유지).

### D. 입력 단계 (TK-01, TK-07) — 첫 점수에 가장 크게 영향
- **증거 1 — 글꼴 구두점 글리프가 사용자 영역 문자로 읽힌다(TK-01):** 서면7(Google Docs/Skia, Inter 글꼴)에서 육안으로 보이는 `09-108273`, `010-4729-1830`, `1002-841-928371`, `14-09-718293-02`의 하이픈이 U+E088로, `제57조의3(지휘관…)`의 `(`가 U+E081로, 말미 표지의 `[`·`:`·`]`가 U+E083·U+E092·U+E084로 본문에 들어온다. PDF 내용 스트림에는 `/Span <</ActualText (-)>>`처럼 실제 문자가 지정되어 있다. 그 결과 하이픈 있는 군번·연락처·계좌·운전면허가 마스킹되지 않았고(온라인 보고서 9종 중 4종 누락) 환각표의 조문 제목에도 ``이 남았다. 같은 문서를 원문 텍스트로 넣으면 그 네 항목이 모두 마스킹된다 — 개인정보 엔진이 아니라 입력 단계 문제다. `pypdfium2.get_text_range`는 `-`·`(`·`[`를 복원하고 pdfplumber·pypdf는 U+E0xx를 낸다(평가 측 확인).
- **증거 2 — 줄바꿈으로 갈라진 「법령명」 인용(TK-07):** 줄 바꿈이 그대로 있는 `.txt`에서 `「군인\n징계령」 제12조 제2항`, `「육군 군인·군무원 징계업무\n처리 훈령」 제15조 제3항`이 추출되지 않는다(PDF 경로는 추출된다).
- **원인:** 추출기가 문자 코드만 믿고 PDF가 알려 주는 대체 텍스트(ActualText)를 쓰지 않는다. 텍스트 입력은 줄 경계를 인용 추출에서 정규화하지 않는다.
- **개선 방향:** (1) 파서 출력에 사용자 영역(유니코드 범주 Co)·U+FFFD가 남지 않게 한다. ActualText 존중, 또는 교차 추출기 비교(`parser_disagreements` 지표 재사용)로 복원하고, 복원하지 못하면 문서 경고를 남긴다. (2) 인용 추출은 줄바꿈·공백 변형을 같은 인용으로 본다(서로 다른 두 문장이 줄바꿈으로 이어질 때는 합치지 않는다).
- **금지:** 코드포인트→문자 사상표(U+E088→`-`)를 코드에 고정하지 않는다(번호는 글꼴마다 다르다). 서면7에서만 동작하는 분기를 만들지 않는다.
- **수용 기준:** 서면7 pdf TEXT-1·2·3, PII-2·7·9·10, text CIT-3·6 통과. `python -m pytest tests/acceptance/test_input_layer_fidelity.py` — 모든 fixture PDF의 본문에 사용자 영역 문자 0.

### E. 개인정보 정책 (TK-02) — 사용자 결정 확정
- **결정:** **소송대리인·법원 주소는 마스킹하지 않는다. 당사자(원고·피고·피고인 등)의 주소는 마스킹한다.** 이 결정은 주소에 한정한다(대리인 성명·연락처 등은 현행 유지).
- **증거:** 당사자 주소 `충청남도 계룡시 신도안면 계룡대로 305, 108동 801호`가 `[ADDRESS_001]계룡대로 305, 108동 801호`로 행정구역까지만 가려진다(서면7 PII-5·6). 대리인 사무소 주소 `대전 서구 둔산중로 78, 502호 (법률사무소 청람)`가 `대전 [ADDRESS_002] (법률사무소 청람)`로 가려진다(과잉, PII-11).
- **원인:** 주소 탐지가 역할(누구의 주소인가)을 모르고, 도로명·번지·동호 구간을 행정구역과 함께 덮지 못한다.
- **개선 방향:** 문맥으로 역할을 구분한다(`소송대리인`·`법률사무소`·`법무법인` 줄, 법원 표시 줄은 제외; 당사자 줄·인적사항 괄호는 대상). 도로명+동호·지번·층호 표기를 하나의 주소로 덮는다.
- **수용 기준:** 서면7 PII-5·6·11 통과(pdf·text). 양성 3건(도로명+동호, 지번, 층·호)과 대조군 3건(대리인 주소, 법원 주소, 주소 아닌 `제305조`·`제108조 제801항`).

### F. 규칙 부족 — 구조로 일반화 (TK-04, TK-05, TK-03)
- **TK-04 처분일보다 뒤의 개정을 그 처분에 적용하라는 주장:** 서면7은 처분일 `2024. 2. 20.`을 적고 `2025년 3월 1일 … 개정·공포`된 규정을 그 처분에 적용했어야 한다고 주장한다. 온라인 보고서에는 이미 `reference_date: 2024-02-20`(처분일)이 추정되어 있는데도 `TEMPORAL_LAW_MISMATCH`/`TIMELINE_CONTRADICTION`이 없고, 모델 의견이 `MODEL_FACT_REMARK`(MEDIUM·UNVERIFIED)로만 남는다. 공식 DB 없이 **서면 내부 날짜**만으로 잡을 수 있다. 행정처분은 처분 당시 법령·사실상태를 기준으로 위법 여부를 판단하는 것이 원칙이고(출처: [법률신문](https://www.lawtimes.co.kr/news/186107), [대법원 92누19033](https://casenote.kr/%EB%8C%80%EB%B2%95%EC%9B%90/92%EB%88%8419033) — 검색 결과로 확인, 원문 미열람. 규칙 `basis`에는 국가법령정보센터에서 원문을 확인한 것만 쓴다), 형사 행위시법(형법 제1조)과 기준 시점이 다르다. 부수 오류: `temporal_review` 사유 문구가 `제57의3조`(정식은 `제57조의3`). **수용:** 서면7 TMP-1(pdf·text). 양성 3건은 날짜·법령명·문구가 다르게, 대조군(개정일이 처분일보다 앞선 경우, 처분 이후 개정을 참고로만 언급, 부칙의 소급 경과규정)은 알리지 않는다.
- **TK-05 공금 유용에 사무관리·정당행위 원용:** 오프라인·온라인 모두 알리지 않는다. 온라인에서 모델 3개는 "인용 미확인 건"에만 의견을 냈고 사무관리·정당행위 주장의 타당성은 묻지도 않았다. 정규식을 더하는 방식으로는 닫히지 않는다. **개선 방향:** 구조(비위 사실 인정 + 예외 사유 원용 + 요건 일부 생략)를 잡거나, TK-09의 "모델 제안 → 결정적 검증" 경로로 푼다. **수용:** 서면7 LEG-1·2(SUSPICIOUS·사람 확인 대상 허용). 양성 3건은 주제(사무관리·긴급피난·정당방위 등)와 문장 틀이 다르게, 대조군(요건을 모두 주장·소명한 서면, 판례를 정확히 인용한 서면)은 알리지 않는다.
- **TK-03 인젝션 표지(서면7):** `[ADMINISTRATIVE_AUDIT_PROTOCOL: CRITICAL OVERRIDE]`에 일치하는 `INSTRUCTION_PATTERNS`가 104개 중 하나도 없다(평가 측 확인). 분류기(`classifier.py`)의 어휘를 늘려도 이 경로는 고쳐지지 않는다(패턴 단계에서 걸리지 않으므로 분류기까지 가지 못한다). 정답지는 표지 뒤에 주석 본문이 있다고 적었지만 이 PDF의 텍스트 계층에는 표지 한 줄뿐이다. **수용:** 서면7 INJ-1(pdf·text), 양성 3건(서면6·7 표지와 어휘가 다른 새 변형), 대조군 3건(판결문·규정에서 `override`·`protocol`·`audit`가 평범하게 나오는 문장, `[별지 제1호]` 같은 머리표)과 고정 시험 오탐 0 유지.

### G. 정책 변경 — AI 작성 판정 다수결 (TK-11) — 사용자 결정 확정
- **결정:** 문서의 AI 작성 판정은 모델 의견의 **만장일치가 아니라 다수결**로 정한다. 지금은 라벨이 모두 같아야 합의로 보고(`PARTIAL`과 `FULL`이 섞이면 `HELD_DISAGREEMENT`), 합의여도 문체 경보·가상 인용 군집·객관적 흔적 중 하나가 없으면 `HELD_NO_OBJECTIVE_TRACE`로 유보한다(`ai_document_detector.py` `_combine_model_verdicts` 486~535행). 서면7은 모델 3개가 모두 AI 쪽(anthropic 0.60 PARTIAL, openai 0.91·gemini 0.95 FULL)인데 `UNCERTAIN`이었다.
- **규칙:** 응답한 모델 수 n. `HUMAN_AUTHORED_LIKELY`는 지금처럼 `UNCERTAIN`으로 센다. AI 표(FULL+PARTIAL)가 n의 과반(n/2 초과)이면 AI 쪽, FULL 표가 과반이면 FULL 아니면 PARTIAL, 과반이 아니면 `UNCERTAIN`. n=1은 현행 유지(규칙 판정으로 상한). `decision_rule`은 AI 다수결이면 `MAJORITY…`, 유보면 `HELD_…`로 시작.
- **해석(사용자 확인 대상):** 다수결이 판정을 정하고 객관적 흔적 부재는 판정을 막지 않는다. `involvement`(`NO_OBJECTIVE_TRACES`)·`objective_traces`·`verdict_distribution`은 판정과 별도 축으로 보고서에 계속 싣는다. 흔적 요건을 유지하라는 지시가 오면 `tests/acceptance/test_ai_majority_rule.py`의 "흔적 없음" 기대값만 바뀐다.
- **함께 고칠 기존 시험(`tests/`):** `test_verification_regressions.py::test_unanimous_models_without_objective_trace_hold_and_explain_score_vs_confidence`, `test_case6_military_secret_defense_opinion.py::test_cluster_controls`, `test_case5_…`·`test_case6_…`의 `MAJORITY_AI_CONSENSUS`·`MAJORITY_AI_AGREE` 기대. 새 규칙에 맞는 새 양성·대조군으로 바꾼다.
- **수용 기준:** `python -m pytest tests/acceptance/test_ai_majority_rule.py` — 현재 미해결 8건이 strict xfail이므로 고치면 XPASS로 실패한다. 그때 평가 에이전트에게 알리면 xfail 표시를 지운다.

### H. CI 빨간불 (TK-12) — 평가 에이전트와 협업
- **증거:** main `CI`가 4ad64a7에서 실패([실행 기록](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/36683167780)). 실패는 `tests/test_ground_truth_prepared_brief.py`의 두 시험(`test_precedent_and_regulation_existence`, `test_temporal_retroactive_application_review`). 이 시험은 `config/legal_mirror/*.json`을 전제하는데 `.gitignore` 17행이 그 파일들을 제외해 깨끗한 복제본·CI에는 `README.md`만 있다.
- **원인:** 시험이 저장소 밖(작성자 PC)에만 있는 데이터에 의존한다.
- **개선 방향:** 두 시험이 쓰는 자료를 `tests/fixtures/` 아래 전용 미러 폴더로 두고 시험이 `LocalLegalMirror(root=…)`로 읽게 한다. 자료는 공식 원문에서 확인한 것만(2018도15313 판결의 존재, 부정경쟁방지법 제2조 제1호 카목 신설일 등, 출처 URL 포함). `tests/fixtures/`는 보호 경로이므로 **자료와 출처를 `docs/handoff/requests/`에 첨부해 평가 에이전트에게 반영을 요청한다.** 시험을 건너뛰거나 기대값을 낮추지 않는다.
- **수용 기준:** CI `pytest -q` 통과.

### I. 설계 — 구현 금지, 사용자 승인 후 (TK-09)
모델 3개는 이미 서면7의 시점 모순(`MODEL_FACT_REMARK`)과 Drive 훈령 제15조 제3항과의 정면 모순(`rag.observations[0].relationship = CONTRADICTS`)을 찾아냈지만, 앞의 것은 `UNVERIFIED` 참고 의견으로만, 뒤의 것은 advisory로 finding 목록에 오르지 않았다. 설계안(모델이 후보를 제안하고 결정적 검증기가 받아들이거나 버린다, 통과한 후보는 SUSPICIOUS finding으로 목록에 오른다)은 `TK-09`에 명세만 있다. **사용자 승인 전에는 구현하지 않는다.** 구현 전에 설계 초안을 `docs/handoff/requests/`에 올려 승인을 받는다.

---

## 3. 공통 작업 방식

**변형 시험(일반화를 재는 방법).** 규칙 하나마다 다음을 `tests/`에 둔다.
- 양성 3건 이상: 원래 서면과 **값·문구·어순·서식(줄바꿈·공백·글꼴) 중 둘 이상을 바꾼** 합성 문서. 원래 서면의 낱말을 재사용하지 않는다.
- 대조군 3건 이상: 같은 문서에서 결함 요소만 빼거나 고친 것(예: 개정일이 처분일보다 앞선 경우, 요건을 모두 주장한 서면).
- 서면 고유 문구·식별자가 시험 입력에만 있고 코드에는 없어야 한다.

**막히면.** 보호 경로 변경·자료 제공·정책 해석이 필요하면 `docs/handoff/requests/NN_제목.md`에 (무엇이, 왜, 네가 제안하는 변경) 세 줄로 적고 해당 묶음을 이어 간다.

**하지 말 것.** 서면6·7의 낱말·식별자·날짜를 코드에 추가, 기대값 조정으로 시험 통과, 시험 skip, 기준선 하향, 자료 지어내기, 정책 임의 결정, 보호 경로 수정, 강제 푸시.

---

## 4. 검증 명령 (커밋 전에 모두 통과)

```
python scripts/scorecard.py && python scripts/score_gate.py            # 고정 시험 점수 하락·오탐 증가 없음 (기준 79.9/77.3)
python scripts/check_case_literals.py                                   # 새 위반 0
python -m pytest tests/acceptance -q -rxX                               # 미해결은 strict xfail, XPASS(strict) 실패는 평가 에이전트에게 알림
python -m pytest -q --ignore=tests/acceptance                           # 기존 시험(알려진 실패 3건은 묶음 H·환경 사유, 새 실패 금지)
python scripts/probe_document.py run --spec tests/fixtures/probes/case7_suspension.json [--text]   # 서면7 항목별
python scripts/probe_document.py run --spec tests/fixtures/probes/case6_military_secret.json [--text]  # 서면6은 20/20 유지
```
알려진 기존 실패: `test_ground_truth_prepared_brief.py` 2건(묶음 H), `test_v5_ocr_dates.py::test_rotated_scan_page_impossible_date_is_found`(이 세션 환경에서만 실패, CI에서는 통과).

## 5. 보고 형식 (묶음마다)
1. 바꾼 원인(한 줄)과 바꾼 파일
2. 위 검증 명령 출력 요약(점수 전/후, 새 시험 수, 서면7 항목 전/후)
3. 남은 미해결과 사용자 결정이 필요한 것
4. 커밋 해시(`Agent: implementer`)

## 6. 사용자 결정 필요 (네가 정하지 않는다)
- 다수결 해석: 객관적 흔적 부재가 판정을 막지 않는 것으로 구현(평가 에이전트 해석). 사용자가 다르게 지시하면 그에 따른다.
- 기준선(`baseline.json`) 상향 시점: 묶음 A(미러) 처리 뒤 평가 에이전트가 요청하고 사용자가 승인한다.
- TK-09 설계 구현 여부.
