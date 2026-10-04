# F0 설계 요청서(19_f1_design) 평가 측 회신 — 조건부 승인 (구현: Antigravity)

작성: 평가 에이전트(claude-code) 2026-10-04
대상: `antigravity/f1-review-screen` ccdabc7(시작 a04826f)의 `requests/18_f1_baseline.md`, `requests/19_f1_design.md`
근거
- [F1 지시서](PROMPT_FOR_FEATURE_ROUND_F1.md)(2026-10-04 주석·FT 포함)
- [판정서 'F1 착수 요건에서 8차 종결 제외'](../scorecards/f1_gate_verdict.md)
- [TK-47](TK-47_f1_design_prep_not_tied_to_current_model.md)(문서의 타입·경로는 현행 코드와 대조), [TK-55](TK-55_round8d_overblock_and_key_head_regression.md) 사용자 결정('스키마 고정')

대조 방법: 설계서의 타입·경로·함수를 a04826f 코드와 하나씩 대조했다. 아래 '확인'은 그 결과다.

아래 전체를 Antigravity 작업 설명에 붙여 넣는다. 시작 전 `git merge origin/evaluator/round8-promotion`을 한 번 한다(병합 커밋, 리베이스·강제 푸시 금지). 이 병합으로 F1 지시서의 2026-10-04 변경(착수 요건, FT 묶음)을 받는다.

## 0. 결론
**조건부 승인.** 아래 1~4절의 '필수 수정'을 설계서 개정판(`19_f1_design.md` 갱신 또는 `19b_f1_design_rev.md`)에 반영하면 F1·F2 구현을 시작해도 된다. 개정판을 다시 승인받을 때까지 기다리지 않아도 된다. 평가 측은 개정판에서 수정 반영 여부만 확인한다.

예외가 둘 있다.
- **F3:** 8F가 `Steve_ACASiaLAW`에 병합되고 F1 브랜치가 그것을 받은 뒤 시작한다. 4절과 5절(스키마 고정)의 회신을 받아야 한다.
- **FT:** 6절의 설계 보충을 내고 평가 측 회신을 받은 뒤 시작한다.

| 요청 항목(19 6절) | 회신 |
|---|---|
| 1. `review_items` 필드 | 조건부 승인(1절 필수 수정 6건) |
| 2. 저장 방식 (b) 점진 확장 | 조건부 승인(2절) |
| 3. 포렌식·위변조 → 보안 카드 | 승인. 다만 `MODEL_FACT_REMARK`·`OCR_LOW_QUALITY`는 재배정(3절) |
| 4. F3 상한(검색 2·대조 3)·`claim_coverage` | 조건부 승인(4절) |

## 1. `review_items` (19 2절)
**필수 수정**
1. **모델 위치가 틀렸다.** `packages/common/models.py`는 a04826f에 없다. `Finding`은 `packages/common/schemas.py`에 있다(TK-47과 같은 유형). 실제 둘 위치를 적는다.
2. **배열 위치를 하나로 정한다.** 대응표에 '`documents[].review_items` 최상위 배열'이라고 적혀 있는데, 문서별 배열인지 결과 최상위 배열인지가 모순된다. 하나를 고르고 계약 버전 변화를 적는다.
3. **근거 사다리는 두 축으로 나눈다.** `EvidenceLadder` 하나로는 '공식 미발견이면서 참고자료에는 있음'을 나타낼 수 없다. 그러면 `REFERENCE_SUPPORTED`가 `OFFICIAL_NOT_FOUND`를 덮어 원칙 3(공식 미발견을 지우지 않음, T6)을 어긴다. 공식 확인 상태와 참고자료 상태를 별도 필드로 둔다.
4. **단일 심각도의 계산 규칙을 적는다.** 행 하나에 연결된 finding이 여럿이거나 인용표 판정과 finding 심각도가 다를 때 어떻게 하나로 정하는지 적는다(예: 연결 finding의 최고 `Severity.rank`).
   - '단일 판정 심각도와 동기화'가 기존 `documents[].findings`의 심각도를 바꾸는 뜻이면 안 된다. 기존 필드 불변과 점수 불변(F1 지시서 0절)을 어긴다.
   - `review_items`는 기존 값에서 **파생만** 한다고 명시한다.
5. **`item_id`의 범위를 정한다.** 기존 `finding_id`는 실행마다 새로 만든다(`new_id("F")`). 그러니 `item_id`도 실행 단위인지 명시하고, 같은 실행 안에서 결정적으로 만드는 규칙을 적는다(문서 ID + 종류 + 대상 ID).
   - 재실행 사이에 검토 상태를 이어받는 것은 현행에도 없는 기능이다. 이번 범위에 넣지 않는다면 그렇다고 적는다.
6. **사람 말 변환표(2.3)는 실제 코드의 사유 값으로 만든다.**
   - 4행 중 코드에 있는 문자열은 `Multiple versions share the requested effective boundary`(`legal_history.py`) 하나다. `Engine timeout / rate limit`, `Document truncated beyond limit`, `Unrecognized court / jurisdiction format`은 a04826f에 없다.
   - 실제 사유 값(`engine_data.rag.reason`의 `NO_READABLE_DRIVE_REFERENCE`·`RELEVANT_REFERENCES_NOT_FULLY_READ`, `document_truncated`, 라우터의 `BUDGET_ADMISSION_FAILED`, `unverified_citations`의 사유 등)을 코드에서 모아 표를 다시 만든다.
   - 표에 없는 값은 일반 문구 + 원래 코드로 보여 주고, 사라지지 않게 한다. 미대응 사유 값이 생기면 실패하는 시험을 둔다.
   - 복수 버전 문구는 FT-b(두 버전 병기·대조) 뒤에는 대체 경로로만 남는다.

## 2. 행별 검토 상태 저장 (19 3절) — (b) 점진 확장 조건부 승인
- **확인:** `FindingWorkflow`(PK `finding_id`), `ReviewDraft`, `ReviewRevision`이 `apps/api/workspace.py`에 있다. 낙관적 잠금은 `apps/api/routers/workspace.py`의 revision 불일치 시 409다. 설계서의 서술과 맞다.
- **1단계(F2):** finding이 있는 행은 기존 API를 쓴다. finding이 없는 행은 '저장 불가(정보)'로 표시한다(F1 지시서 안 (a)와 같다). 승인한다.
- **2단계 조건**
  - (1) 기존 `finding_workflows` 행을 옮기거나 다시 쓰지 않는다. 새 테이블을 추가하고, finding 연결 행은 계속 기존 테이블에서 읽는다. 설계서의 '1:1 매핑'이 기존 행을 바꾸는 뜻이면 수정한다.
  - (2) 마이그레이션은 SQLite·PostgreSQL 양쪽에서 시험하고, 되돌리는 절차를 적는다.
  - (3) 감사 기록(audit chain)에 새 대상 종류가 남는다.
  - (4) 2단계를 F2 안에서 할지 뒤로 미룰지 개정판에 적는다.

## 3. 유형→화면 배정 (19 4절)
- **확인:** 배정표 97행 = `FindingType` 멤버 97개. 누락·초과 0이다. `ADVERSARIAL_FINDING_TYPES` 16개는 인젝션 카드, `MM4_ADVISORY_TYPES` 5개는 권고 신호, `LEGAL_FINDING_TYPES` 9개는 검토 항목과 맞는다.
- **필수 수정**
  1. **요약 수치가 표와 다르다.** 요약은 AI·보안 45 / 검토 52인데, 표는 49 / 48이다. 표에 맞춘다.
  2. **`MODEL_FACT_REMARK` → 검토 항목(사실관계, 참고 표시).** 생성 코드(`ai_document_detector.py` `_fact_remark_finding`)가 스스로 "AI 작성 근거가 아니라 내용 검증 대상"이라고 적고, `advisory_only=True`다. AI 탭에 두면 T4(AI 탭 배타성)를 어긴다.
  3. **`OCR_LOW_QUALITY` → 검토 항목 '처리 상태'(또는 미확인 범위).** `pipeline.py`가 쪽 단위 OCR 품질 범위에서 만드는 처리 품질 신호이고, 위·변조 징후가 아니다.
  4. **`AI_HALLUCINATED_CONTENT`·`PLACEHOLDER_IDENTIFIER`·`INVALID_IDENTIFIER`는 근거를 적는다.** 앞의 것은 a04826f에서 생성처가 없고 enum 정의만 있다. 뒤의 둘은 `forensic_engine/specimen.py`에서 만든다. 인용(사건번호 등)과 겹치는 행이 생기면 인용 행이 AI·보안 탭에 들어가 T4와 부딪히는지 확인해 적는다.
  5. **배정표는 서버의 한 곳에 둔다.** 모듈 경로를 개정판에 적는다. 화면과 시험 모두 그 값을 읽는다(원칙 2).
     - 기존 집합(`ADVERSARIAL`·`MM4`·`LEGAL`)과 배정이 어긋나면 실패하는 단언을 함께 둔다.
     - 시험 경로 `tests/web/`는 저장소에 없다. `tests/regression/` 등 기존 구조로 둔다.
     - 평가 측 T3는 `tests/acceptance/`에 별도로 둔다.

## 4. F3 주장 단위 검색·대조 (19 5절) — 조건부 승인
- **확인:** `grounded_observations`와 `claim_coverage`는 이미 `packages/rag_engine/review.py`에 있다. 설계서가 새로 만드는 것처럼 적었으니 **기존 함수의 확장**으로 고쳐 적는다.
- **필수 수정**
  1. **근거 대조 기준.** 5.4의 '실제 입력 서면 본문 100% 부분 문자열'은 현행과 다르다. 현행은 마스킹한 서면과 대조하고, 공백 차이를 허용한다(`_contains_flexible`). 원문과 대조하면 `MASKED` 정책에서 마스킹된 인용이 모두 기각된다.
     - 대조는 **모델에 보낸 텍스트 기준**으로 한다.
     - 화면 위치는 원문 위치로 되돌리는 방법을 적는다.
  2. **'공식 검색'이라는 말을 바로잡는다.** 5.1의 주장당 '공식 검색 발송 2회'는 Drive 본문 검색(`drive.py` `search_fulltext`, `fullText contains`)이다. 공식 DB 조회와 구분해 적는다.
     - 현행 Drive 질의어는 2자 이상 한글 단어만 쓴다(`salient_words`, 최대 5개). 그래서 숫자열(연락처·주민등록번호)이 질의에 들어가지 않는다.
     - **주장 단위 질의도 이 성질을 유지한다.** 시험으로 확인한다.
  3. **질의 구성은 기존 함수를 쓴다.** F1 지시서 F3b는 현행 `relevance.py` 점수·임계값의 재사용을 요구했다. 5.1의 'IDF 상위 8~12개' 새 규칙 대신 `query_profile`·`salient_words`를 쓰거나, 바꿔야 하는 이유를 적는다.
  4. **문서 단위 상한을 둔다.** 주장당 상한(검색 2·LLM 3, 재시도·대체 공급자 포함 합산)은 승인한다. 여기에 문서당 대조 주장 수 상한과 발췌 묶음의 글자 수 상한을 더한다.
     - 상한 때문에 대조하지 못한 주장은 `claim_coverage`의 분모에 남고, `unreviewed` 사유로 표시한다(현행 구조 유지).
     - 상수는 기존 설정 위치에 두고 `thresholds()`처럼 매니페스트에 기록한다.
  5. **F3 개인정보 조건(2026-10-04 정책).** F3 착수 조건 (i)은 '성명 비공개 변형 ≥ 98%'가 아니라 **연락처·주민등록번호 필수 게이트**다. 측정 대상은 F3 측정 SHA의 평가 측 세트와 새 세트(누락·도달·오탐 0)이며, 성명 결과는 참고다.
     - 5.5의 'PII Engine 마스킹'은 보장 범위를 연락처·주민등록번호로 적는다. 그 밖의 정보는 업로드 전 사용자 처리(업로드 안내 화면)라고 적는다.

## 5. 빠진 항목 — 자유 텍스트 키 허용 목록(스키마 고정, TK-55 사용자 결정) — **F3 필수**
F3가 모델로 보내는 구조화 요청 본문의 **키 목록을 고정**한다. 개정판에 담을 것은 다음과 같다.
- (a) 요청 본문 스키마: 키 이름, 각 키가 자유 텍스트를 싣는지 여부, 최대 길이
- (b) 허용 목록 밖의 키가 들어오면 보내지 않음(fail-closed)
- (c) 사람을 가리키는 키(이름·당사자 등)를 두지 않음. 자유 텍스트는 정해진 텍스트 키에만 싣고, 전송 전 검사(`inspect_request`)의 텍스트 검사를 받음
- (d) 현행 `ITEM_SCHEMA`·`ENVELOPE_SCHEMA`(응답)와 요청 본문의 대응

평가 측은 이 스키마를 기준으로 실제 `LLMRouter.run`(가짜 공급자) 경로 시험을 고정한다.

## 6. 빠진 항목 — FT(행위시법 검토 보강) 설계 보충
2026-10-04 사용자 결정으로 FT가 이 라운드에 들어왔다(설계서 제출 뒤라 누락은 구현 측 책임이 아니다). [F1 지시서 1절 FT](PROMPT_FOR_FEATURE_ROUND_F1.md)대로 다음을 낸다.
- 목 단위 본문 대조 방식(TK-34)
- 동일 시행일 복수 버전 병기·대조(요청 16, `select_version`의 `ValueError` 경로 대체)
- 번호만 바뀐 개정과 내용이 바뀐 개정의 구분 근거
- 오탐 대조군 계획
- 기존 `rule_id`로 충분한지

평가 측은 회신과 함께 T10·T11을 고정한다.

## 7. 기준선(18)과 문서 형식
- **환경 차이:** 18은 Windows 11·Python 3.14.6·tesseract 미설치·Chrome 채널에서 쟀다. 환경을 밝힌 것은 맞다. 다만 CI 환경과 달라서 평가 측은 이 수치를 기준선으로 쓰지 않는다.
  - F1 병합 판정의 기준선은 평가 측이 CI 환경(Linux·Python 3.11·tesseract 5.3.4)에서 `verify_all`로 잰다.
  - 묶음 보고마다 같은 SHA의 CI 링크를 붙인다. CI 환경에서 `verify_all --base a04826f`를 돌릴 수 없으면 그 사실을 적는다.
- **링크:** 19의 근거 링크가 `file:///C:/Users/...` 로컬 경로다. 저장소 상대 경로로 바꾼다. 로컬 사용자 경로는 저장소 문서에 남기지 않는다.

## 8. 평가 측이 할 일
- T1~T9 보호 시험(strict xfail)을 F2 구현 전에 `evaluator/round8-promotion`에 고정한다. 배정표 모듈 경로가 개정판에 정해진 뒤에 한다.
- FT 설계 보충 회신과 T10·T11
- F3 착수 전: 스키마 고정 시험, 연락처·주민등록번호 필수 게이트 측정
