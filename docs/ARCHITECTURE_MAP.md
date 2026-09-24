# 검증 프로그램 구조 지도 (v2 개선 착수 전)

v2 개선 작업 지시서 1항에 따라, 코드를 고치기 전에 모듈 위치와 데이터 흐름을 정리한다.
경로는 저장소 루트 기준이다.

## 1. 데이터 흐름

```
업로드 → document_engine(파싱) → adversarial_engine(인젝션·은닉 검사) → pii_engine(비식별화)
      → legal_engine.citation_extractor(인용 추출) → legal_engine.verifier(공식 출처 대조)
      → claim_engine(주장·사건·첨부) → legal_engine.argument_validity_verifier(법률 주장 대조표)
      → verification_engine.authorship / ai_document_detector(AI 작성)
      → claim_engine.assertion / legal_engine.omission(표현·누락)
      → verification_engine.scoring + gate(축별 집계·배포 게이트)
      → apps/api/routers/reports.py → report_engine(PDF·Word·Excel·JSON)
```

실행 순서는 `packages/verification_engine/pipeline.py`의 `VerificationPipeline._run_document()`가 정한다.
결과는 `DocumentResult`(문서별)와 `VerificationRunResult`(실행 전체)에 모이고 `report_engine.exporters.to_payload()`가
JSON으로 만든다.

## 2. 모듈 위치

| 기능 | 위치 | 비고 |
|---|---|---|
| PDF 파싱 | `packages/document_engine/pdf_parser.py` | 줄 단위 블록, 숨김 사유(`_hidden_reason`), 표 구조(`doc.structure["tables"]`), Tr 3 사용 여부(`_has_invisible_render_mode`) |
| 기타 파서·OCR | `document_engine/docx_parser.py`, `hwp_parser.py`, `simple_parsers.py`, `ocr.py`, `rasterize.py` | |
| 인용 추출(span parser) | `packages/legal_engine/citation_extractor.py` | 정규식 `FULL_CASE_RE`, `BARE_CASE_RE`, `CONST_RE`, `LAW_RE`, `ADMIN_RULE_REF_RE`; 블록 단위 + 페이지 이어붙이기 2회 |
| 인용 정규화 | `packages/legal_engine/normalize.py` | `canonical_law_name`, `canonical_case_number`, `case_number_possible`, 사건부호표 `CASE_CODE_MEANING` |
| 판례·법령 조회 어댑터 | `packages/source_adapters/law_go_kr.py`, `official_legal.py`, `legal_history.py`, `local_mirror.py` | 국가법령정보 DRF(판례 prec/detc, 법령 eflaw, 해석례 expc, 재결 decc, 행정규칙 admrul) |
| 학술 어댑터 | `packages/source_adapters/academic.py`, `registry.py` | KCI·OpenAlex·Crossref·Semantic Scholar |
| 인용 대조 | `packages/legal_engine/verifier.py`(판례 5단계·법령), `source_review.py`(시행 버전·조항 대조·해석례·행정규칙), `components.py`(단계별 결과), `quotation.py`(인용문 대조) | |
| 문서 내부 조항 참조 | `packages/legal_engine/internal_citation.py` | **B2의 발생 위치**: "조항번호와 내용이 다르다 … 해당 내용은 제X조에 있다" |
| 인젝션 탐지 | `packages/adversarial_engine/scanner.py`, `classifier.py`, `patterns.py`, `cross_layer.py`, `unicode_scan.py`, `encoding_scan.py` | 블록·메타데이터·유니코드·인코딩·레이어 비교·멀티모달 |
| 은닉·잔존 정보 | `packages/forensic_engine/*` | `covert.py`, `residual.py`, `redaction.py`, `specimen.py`(예시·자리표시자, **B14 '실제 계약서로 취급' 문구**), `template_residue.py` |
| AI 작성 판별(멀티모델) | `packages/verification_engine/ai_document_detector.py`(규칙 + `LLMRouter.consult_all` 교차판정), `authorship.py`(문체 통계, 판정 보류) | |
| LLM 라우터 | `packages/llm_router/router.py`, `providers.py`, `budget.py` | |
| 법리 검토 | `packages/legal_engine/argument_validity_verifier.py`(인용 판례에 기댄 주장), `omission.py`(누락 후보), `packages/claim_engine/assertion.py`(과잉 일반화·불확실성 미고지·초안 흔적) | 청구취지 자체의 소송요건 검토는 없음(B11) |
| 주장·사실·증거 | `packages/claim_engine/extractor.py`, `classification.py`, `attachments.py`, `structure.py`, `fact_ledger.py`, `contradiction.py`, `calculation.py` | 호증 결번·문서 간 복사·인적사항 대조는 없음(B12) |
| 점수·게이트 | `packages/verification_engine/scoring.py`, `gate.py` | 축별 위험도, 검증위험 지수, BLOCK 사유(인용별 묶음) |
| 보고서 | `apps/api/routers/reports.py`, `packages/report_engine/pdf_report.py`, `docx_report.py`, `exporters.py`(JSON·Excel·CSV), `summary.py`(요약본), `snapshot.py`(고정본) | |
| 화면 | `apps/web/static/app.js`, `workflow.js`, `report-workbench.js` | |

## 3. v1 결함과 관련 코드

| 결함 | 관련 위치 | 현재 동작 |
|---|---|---|
| B1 불가능 날짜·사건부호 | `normalize.case_number_possible`, `normalize.canonical_date`, `verifier.verify_case` | 미래 연도·미등록 부호만 성립 불가로 본다. 달력상 없는 날짜, 법원–부호 호환, 선고연도<접수연도는 검사하지 않는다 |
| B2 다른 법령 조문 혼동 | `internal_citation.py` | 문서 내부 조항 참조 검사가 외부 법령 조문에도 적용될 수 있다 |
| B3 span 파싱 | `citation_extractor.LAW_RE` | 법령명 앞쪽으로 문장 조각이 붙고, 약칭 사전이 없다 |
| B4 없는 법령·조문 | `source_review.verify_statute_source`, `official_legal.search_law_history` | 법령 목록에 없으면 "Missing or ambiguous exact law identity"(미확인)로 끝난다 |
| B5 수치 오기 | 없음 | |
| B6 고유사도 변형 인용 | `verifier._compare_quote`(0.98/0.88 임계), `quotation.py` | 0.88 이상은 일부 일치로 통과 |
| B7·B8 서지 비교 | `verifier._compare_metadata` | 사건명 비교 없음, 정규화 부족 |
| B9 반대의견 | 없음 | |
| B10 인젝션 경로 | `pdf_parser._hidden_reason`, `scanner._scan_blocks`, `cross_layer` | 숨김 사유는 있으나 경로별 finding 유형이 없다. 첨부파일 내용 미검사 |
| B11 청구취지 법리 | 없음 | |
| B12 증거 정합성 | `attachments.py`(첨부 상태만) | 호증 결번·인적사항·문서 간 복사 없음 |
| B13 AI 판별 오염 | `ai_document_detector.py` | 인용 오류는 이미 제외했다. 문서의 시험·예시 표식은 아직 가리지 않는다 |
| B14 보고서 품질 | `gate.citation_groups`, `specimen.py`, `assertion.py` | 인용별 묶음은 게이트·화면에만 있고 finding 자체는 중복될 수 있다 |

## 4. 평가

테스트셋(`tests/fixtures/legal_verifier_testset/`)과 평가 하네스(`scripts/eval_testset.py`)는 v2 작업에서 추가한다.
