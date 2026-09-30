# TK-01 입력 단계: 글꼴 구두점 글리프가 사용자 영역 문자로 읽힘
- 유형: 입력 단계 · 기준 커밋: 4ad64a7 · 작성: evaluator 2026-09-30

## 증상·증거
- 서면7(`tests/fixtures/case7_suspension_complaint_google_docs.pdf`, Skia/PDF m156 Google Docs, Inter 글꼴)에서 육안으로 보이는 `09-108273`(군번), `010-4729-1830`, `1002-841-928371`, `14-09-718293-02`의 **하이픈이 본문에 U+E088로 들어온다**. `제57조의3(지휘관…)`의 `(`은 U+E081, 말미 `[ADMINISTRATIVE_AUDIT_PROTOCOL: CRITICAL OVERRIDE]`의 `[`·`:`·`]`은 U+E083·U+E092·U+E084다.
- 그 결과 개인정보 정규식이 하이픈 있는 번호를 못 잡는다. 사용자 온라인 보고서(run_11a5576f04e845ff, 4ad64a7)는 `masked_preview` 6건(PERSON, ADDRESS×2, AFFILIATION, DOB, EMAIL)뿐이고 **군번·연락처·계좌·운전면허 4개가 마스킹되지 않았다**. 환각표 `claim_text`에도 `제57조의3지휘관`이 그대로 남았다.
- 같은 문서를 원문 텍스트(하이픈 복원)로 넣으면 PII-2·7·9·10이 통과한다(`--text`). 즉 **개인정보 엔진이 아니라 입력 단계 문제**다.

## 원인(확인한 것)
- PDF 내용 스트림에 `/Span <</ActualText (-)>>`처럼 실제 문자가 지정되어 있다(`(-)`, `(\()`, `([)`, `(:)`, `(])`). 해당 글리프는 ToUnicode에서 사용자 영역 코드를 받는다(글꼴의 문맥별 대체 글리프로 보이나 원인은 확정하지 못했다).
- pdfplumber·pypdf 추출은 U+E0xx를 내고, **pypdfium2 `get_text_range`는 `-`, `(`, `[`를 복원한다**(평가 측 확인, 구현 방식은 구현 판단).

## 수용 기준
1. `python scripts/probe_document.py run --spec tests/fixtures/probes/case7_suspension.json` 에서 TEXT-1·2·3, PII-2·7·9·10 통과.
2. 파서가 내는 본문에 사용자 영역 문자(유니코드 범주 Co)가 남지 않는다. 복원하지 못한 것이 있으면 문서 경고로 남기고 품질 지표에 반영한다(`parser_disagreements` 등 기존 지표 활용 가능).
3. `tests/acceptance/test_input_layer_fidelity.py`(평가 작성)의 fixture 전체 불변식 통과.

## 금지
- 코드포인트→문자 사상표(U+E088→`-` 등)를 코드에 고정하지 않는다. 사용자 영역 번호는 글꼴·문서마다 다르다.
- 서면7에서만 동작하는 분기를 넣지 않는다.
