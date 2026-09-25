# 구현 여부 감사표 (v4 P0)

지시서 항목이 '함수가 있다'가 아니라 **실제 파이프라인에서 호출되고, finding을 만들고, 보고서에 표시되고, 요약 점수에 반영되는지**를 합성 문서 실행으로 확인한 표다. `python scripts/implementation_audit.py --label …`로 다시 만든다.

- 상태(0.8.0부터): 완료(탐지율 90% 이상·오탐 0건·보고서·요약 점수 반영) / 부분(미달 사유 표시) / 미구현 / 연결 안 됨 / 완료(실연동) / 미확인(국가법령정보센터·모델 실제 호출로만 확인할 수 있는 항목. `tests/live`의 CI 실연동 통합 테스트가 `docs/live_integration_results.json`에 통과를 기록하기 전까지 이 상태로 둔다)
- '수정 전 (0.7.0 기준)' 표는 처음 낸 표(열 구성이 다름)를 그대로 두었다. 같은 기준으로 비교하려면 아래 '수정 전 (0.7.2 코드 …재측정)'과 '수정 후' 표를 본다.
- '보고서 해당 없음'은 finding이 아니라 판정 라벨·산출물로 나타나는 항목이다.

## 외부 채점에서 지적된 3건의 원인 (수정 전 확인)

| 지적 | 확인한 원인 | 근거 |
|---|---|---|
| 문서 간 교차검증 4회 연속 `cross_document_issues=0` | 사실 저장소가 **서로 다른 입력 파일끼리만** 대조했다. 목록 표·첨부 원문이 한 파일 안에 있는 서면(단일 파일 제출)에서는 대조 대상이 생기지 않아 항상 0이 된다. 속성도 부위 좌우·사고일·청구금액 3가지뿐이었다. | 같은 내용(좌측/우측 슬관절, 사고일 3.15/3.16)을 두 파일로 나누면 2건, 한 파일 안의 청구원인·첨부 진단서 섹션으로 두면 0건(`claim_engine/fact_store.py`의 `cross_document_facts`가 문서 ID별로만 묶음) |
| 법원–사건부호 호환성 미반영 | 검사는 실행되지만 판정 유형이 `CASE_CITATION_ERROR`(표시 라벨 INVALID_FORMAT)로 나가 지시서의 `COURT_CODE_MISMATCH`로 식별되지 않았다. 또 '헌법재판소 + 법원 사건부호'(예: 헌재 … 2018다…) 조합은 탐지하지 못하고 '검증하지 못한 인용'(UNVERIFIED)으로 끝났다. | 합성 실행 D2 행: 대법원+구합·대법원+헌바는 탐지, 헌재+다는 미탐지 |
| 버전 표기 4회 연속 `2026.09.21.4` | 프로그램 버전만 올리고 규칙 버전(`rule_version`)은 한 번도 올리지 않았다. 규칙 버전은 검증 키·결과 JSON에 기록되므로, 규칙이 바뀌어도 같은 버전으로 표시됐다. | `packages/common/config.py` `rule_version` |

## 수정 전 (0.7.0 기준)

- 실행일: 2026-09-24 · 프로그램 0.7.0 · 규칙 2026.09.21.4
- 합성 문서: 민사 준비서면·진단서·소장(txt), 행정 의견서(숨김·구조 경로 인젝션 PDF), 형사 스캔 서면(이미지 PDF). `scripts/audit/synthetic_docs.py`
- 상태 집계: 부분 12, 완료 26
- 실행 매니페스트: 실행하지 않은 엔진 ['semantic_review', 'model_fact_reconcile']

| 항목 | 내용 | 구현 코드 위치 | 파이프라인 호출 위치 | 단위 테스트 | 합성 문서 실행 시 finding | 보고서(JSON·docx) | 요약 점수(scores.axes) | 상태 |
|---|---|---|---|---|---|---|---|---|
| D1 | 변형 인용문 어절 diff(MODIFIED_QUOTE) | legal_engine/quote_diff.py, verifier._modified_quote_finding | legal_engine/verifier.py:quote_changes | test_v3_d1_quote_diff.py | 생성 (1건) | JSON O · docx O | 반영 | 완료 |
| D2 | 법원–사건부호 호환(대법원+1심, 대법원+헌재부호, 헌재+법원부호) | legal_engine/citation_format.py(format_violations), config/legal_rules/case_codes.yaml | legal_engine/verifier.py:format_violations | test_v3_d2_case_codes.py | 생성 안 됨 (대법원+구합: 탐지(1건) / 대법원+헌바: 탐지(1건) / 헌재+다: 미탐지(0건)) | JSON O · docx O | 반영 | 부분 |
| D3 | 다수·반대의견 귀속(MISATTRIBUTED_OPINION) | legal_engine/opinion_attribution.py | legal_engine/verifier.py:attribute_claim | test_v3_d3_opinion.py | 생성 (1건) | JSON O · docx O | 반영 | 완료 |
| D4 | 정확한 인용 VERIFIED_CITATION·요약 verified 반영 | legal_engine/verification_labels.py | legal_engine/verifier.py:citation_label | test_v3_d4_verified.py | 생성 (정확 인용 판정=['VERIFIED_CITATION'], 요약 verified=1) | 해당 없음(판정 산출물) | 반영(legal_citation_accuracy.verified) | 완료 |
| D5 | 같은 인용의 모순 판정 방지(일관성 검사) | verification_engine/finalize.py(enforce_consistency) | verification_engine/finalize.py:enforce_consistency | test_v3_d5_consistency.py | 생성 (모순 판정 인용 0건) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D6 | 증거 표 셀 파싱·호증 파서·누락 알림 묶음 | claim_engine/exhibits.py, attachments._missing_notice | claim_engine/attachments.py:parse_exhibit_label | test_v3_d6_evidence.py | 생성 (1건) | JSON O · docx O | 반영 | 완료 |
| D7 | 출처 조회 실패는 UNVERIFIED(학술) | legal_engine/verifier.verify_academic | legal_engine/verifier.py:verify_academic | test_v3_d7_sources.py | 생성 안 됨 (학술 인용을 추출하지 못함) | 해당 없음(판정 산출물) | 해당 없음 | 부분(탐지 실패) |
| D8 | 요약 표 문서 열·문서 간 그룹 | report_engine/docx_report.py | apps/api/routers/reports.py:build_report_docx | test_report_completion.py | 생성 (요약 표의 문서 열·문서 간 그룹 있음) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D9 | 보이는 AI 대상 억제 지시문 B등급 | adversarial_engine/scanner.py, patterns.py | verification_engine/pipeline.py:self.adversarial.scan | test_v3_d9_visible_instruction.py | 생성 (1건) | JSON O · docx O | 반영 | 완료 |
| §3-1 | 쪽별 텍스트 레이어 판정·OCR 텍스트 전 검사·OCR 실패 '분석 불가' | document_engine/pdf_parser.py(_apply_ocr), pipeline(OCR_LOW_QUALITY·PARSE_ERROR) | verification_engine/pipeline.py:page_coverage | test_ocr.py, test_v3_g2_ocr_quality.py | 생성 (OCR 쪽 1, OCR 글자에서 형식 판정 1건) | JSON O · docx O | 반영 | 완료 |
| §3-2 | 숨김 텍스트 일반화(대비비·투명도·렌더모드) | document_engine/pdf_parser.py(_render_facts, _apply_contrast) | document_engine/pdf_parser.py:_apply_contrast | test_v3_j4_visibility.py | 생성 안 됨 (흰 글자: 탐지(1건) / 저대비: 탐지(1건) / 투명: 미탐지(0건) / Tr 3: 탐지(2건)) | JSON O · docx O | 반영 | 부분 |
| §3-3 | 구조 경로(Info·XMP 전체 키, Outline, 주석, 양식, 첨부, 이미지 OCR) 분류기 투입 | adversarial_engine/scanner.py, document_engine/pdf_parser.py(raw_layers) | verification_engine/pipeline.py:self.adversarial.scan | test_adversarial*.py | 생성 안 됨 (메타데이터 사용자 키: 미탐지(0건) / 주석: 미탐지(0건) / 북마크: 미탐지(0건) / 양식: 미탐지(0건) / 첨부: 미탐지(0건)) | — | — | 부분(탐지 실패) |
| §3-4 | NFKC·폭 0 문자 제거·Base64/hex 디코딩 후 분류 | adversarial_engine/unicode_scan.py, encoding_scan.py | adversarial_engine/scanner.py:decode_candidates | test_adversarial*.py | 생성 안 됨 (Base64: 미탐지(0건) / 전각: 탐지(1건) / 폭 0: 미탐지(0건)) | JSON O · docx O | 반영 | 부분 |
| §3-5 | 산술·날짜 재계산, 문서 간 금액·부위·기관·인적사항 교차검증 | claim_engine/calculation.py, fact_checks.py, fact_store.py | verification_engine/pipeline.py:check_periods | test_v3_j3_arithmetic.py, test_v3_g5_facts.py | 생성 안 됨 (합계: 탐지(1건) / 기간 만료일: 미탐지(0건) / 문서 간: 탐지(3건)) | JSON O · docx O | 반영 | 부분 |
| §3-6 | AI 잔재 패턴 사전 분리·탐지 | verification_engine/ai_residue.py | verification_engine/ai_document_detector.py:scan_residue | test_ai_residue*.py | 생성 안 됨 (0건) | — | — | 부분(탐지 실패) |
| G1 | 헌재 결정 조회(detc) 정확 일치 | source_adapters/law_go_kr.py(search_case) | legal_engine/verifier.py:search_case | test_v3_g1_detc.py | 확인 불가 — 공식 DB(국가법령정보) 조회가 필요해 오프라인 합성 실행으로는 확인 불가 — 단위 테스트와 CI 실연동 평가로 확인 | — | — | 완료(단위 테스트) |
| G2 | 한국어 OCR 품질(쪽별 신뢰도·한글 비율) | document_engine/ocr.py(page_quality) | document_engine/pdf_parser.py:page_quality | test_v3_g2_ocr_quality.py | 생성 (쪽별 OCR 품질 기록 1쪽) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| G3 | 항·호 단위 결합('같은 조 제N항') | legal_engine/citation_extractor.py(_resolve_article_references) | legal_engine/citation_extractor.py:_resolve_article_references | test_v3_g3_paragraph_binding.py | 생성 ('같은 조 제2항' → ['가상손해배상법 제10조 제2항']) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| G4 | 법리 주장 유형 분류→근거 조회→판단 | legal_engine/claim_review.py | verification_engine/pipeline.py:review_claims | test_v3_g4_claims.py | 생성 (전칭: 탐지(1건) / 근거 없는 청구: 탐지(1건)) | JSON O · docx O | 일부 반영 | 부분 |
| G5 | 사실 저장소·기간 재계산·증거 선후 | claim_engine/fact_store.py, fact_checks.py, evidence_consistency.py | verification_engine/pipeline.py:cross_document_facts | test_v3_g5_facts.py | 생성 안 됨 (부위 좌우: 탐지(1건) / 사고일: 탐지(1건) / 청구금액: 탐지(1건) / 증거 작성일<사건일: 미탐지(0건)) | JSON O · docx O | 반영 | 부분 |
| G6 | 오탐 제거(파일명 표지 등) | forensic_engine/covert.py | verification_engine/pipeline.py:self.forensic.scan | test_v3_g6_filename.py | 생성 (파일명 표지 오탐 없음) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| J1 | 헌재 조회 재조회·정확 일치 | source_adapters/law_go_kr.py | legal_engine/verifier.py:search_case | test_v3_g1_detc.py | 확인 불가 — 공식 DB 조회 필요 — 단위 테스트·CI 실연동으로 확인 | — | — | 완료(단위 테스트) |
| J2 | AI 모델 사실 모순 지적 결정론 재검증(MODEL_FACT_REMARK) | verification_engine/ai_document_detector.py | verification_engine/pipeline.py:reconcile_model_fact_remarks | test_v3_j2_model_remarks.py | 확인 불가 — AI 모델 호출이 필요 — 오프라인 합성 실행으로는 확인 불가(v4 P6: '정확히 기재' 칭찬을 모순으로 분류한 결함 보고) | — | — | 완료(단위 테스트) |
| J3 | 산식 행('a × b = c') 검산 | claim_engine/calculation.py(evaluate_expression) | verification_engine/pipeline.py:self.calculation.verify_document | test_v3_j3_arithmetic.py | 생성 (1건) | JSON O · docx O | 반영 | 완료 |
| J4 | 글자별 가시성(투명도·대비·가림) | document_engine/pdf_parser.py | document_engine/pdf_parser.py:_render_facts | test_v3_j4_visibility.py | 생성 안 됨 (투명: 미탐지(0건) / 이미지 가림: 미탐지(0건) / 저대비: 탐지(1건)) | JSON O · docx O | 반영 | 부분 |
| J5 | 조회 실패는 NOT_FOUND가 아닌 UNVERIFIED | legal_engine/verifier.py | legal_engine/verifier.py:verify_case | test_v3_g1_detc.py | 생성 (1건) | 해당 없음(판정 산출물) | 반영 | 완료 |
| J6 | scanned_layers에 outline·annotation·image_ocr·metadata 기록 | adversarial_engine/scanner.py | verification_engine/pipeline.py:self.adversarial.scan | — | 생성 안 됨 (scanned_layers=['annotation', 'hidden_text', 'visible_text'] (필수 ['annotation', 'image_ocr', 'metadata', 'outline'])) | 해당 없음(판정 산출물) | 해당 없음 | 부분(탐지 실패) |
| R1 | 다른 서면을 조항 원문으로 쓰지 않음 | legal_engine/internal_citation.py | verification_engine/pipeline.py:_internal_citation_check | test_v2_root_causes.py | 생성 (서면 간 조항 대조 오판 없음) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R2 | 인용문을 올바른 인용에 결합 | legal_engine/citation_extractor.py(bind_quotes) | legal_engine/citation_extractor.py:bind_quotes | test_v2_root_causes.py | 생성 (인용문 결합={'2018구합51234': False, '2020나12345': False, '2018다90044': False, '2019헌바90055': False, '2014다90011': True, '2015다90022': True, '2016다90033': False}) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R3 | 줄바꿈으로 법원·선고일 유실 방지(읽기 본문) | document_engine/reading_text.py | legal_engine/citation_extractor.py:build_reading_text | test_v2_root_causes.py | 확인 불가 — PDF 줄바꿈 배치가 필요 — 단위 테스트로 확인 | — | — | 완료(단위 테스트) |
| R4 | 사건번호 정확 일치 기록만 채택 | source_adapters/law_go_kr.py | legal_engine/verifier.py:search_case | test_v2_root_causes.py, test_source_adapters.py | 확인 불가 — 공식 DB 응답 필요 — 단위 테스트로 확인 | — | — | 완료(단위 테스트) |
| R5 | 조문 본문 대조(claim_text) | legal_engine/provision_content.py | legal_engine/source_review.py:compare_claim_to_provision | test_v2_root_causes.py, test_v3_g3_paragraph_binding.py | 생성 안 됨 (0건) | — | — | 부분(탐지 실패) |
| R6 | 머리글·바닥글 반복 줄 제외 | document_engine(running_head) | adversarial_engine/scanner.py:running_head | test_v2_root_causes.py | 확인 불가 — 여러 쪽 PDF 필요 — 단위 테스트로 확인 | — | — | 완료(단위 테스트) |
| R7 | 법령명 추출(앞 문장 혼입 방지·긴 법령명) | legal_engine/normalize.py(law_name_suffix) | legal_engine/citation_extractor.py:law_name_suffix | test_v2_root_causes.py | 생성 (법령명 '가상손해배상법' 추출) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R8 | 숨김 경로별 탐지(Tr 3·도형 가림) | document_engine/pdf_parser.py, adversarial_engine/scanner.py | verification_engine/pipeline.py:self.adversarial.scan | test_v2_root_causes.py | 생성 (2건) | JSON O · docx O | 반영 | 완료 |
| R9 | 증거 정합성(달력·결번·선후) | claim_engine/evidence_consistency.py | verification_engine/pipeline.py:check_evidence_consistency | test_v2_root_causes.py | 생성 (달력: 탐지(1건) / 결번: 탐지(1건)) | JSON O · docx O | 반영 | 완료 |
| R10 | AI 판정 축과 문서 결과 일치 | verification_engine/ai_document_detector.py, scoring.py | verification_engine/pipeline.py:create_ai_detector_findings | test_v2_root_causes.py | 확인 불가 — AI 모델 교차판정 필요 — 단위 테스트로 확인 | — | — | 완료(단위 테스트) |
| R11 | 같은 조문 중복 추출 방지 | legal_engine/citation_extractor.py | verification_engine/pipeline.py:extract_citations | test_v2_root_causes.py | 생성 (중복 추출 0건) | 해당 없음(판정 산출물) | 해당 없음 | 완료 |

## 수정 전 (0.7.2 코드, 새 PDF 코퍼스·새 기준으로 재측정)

- 실행일: 2026-09-25 · 프로그램 0.7.2 · 규칙 2026.09.21.4
- 합성 문서(모두 PDF, 표·여러 쪽·머리글/바닥글): 민사 준비서면·진단서, 행정 의견서(숨김·구조 경로 인젝션)·손상 문서, 형사 변론요지서(3쪽 스캔·4쪽 회전 스캔), 가사 소장·답변서 — `scripts/audit/corpus.py`
- 완료 기준: 파이프라인 호출·보고서·요약 점수 반영, 탐지율 90% 이상, 오탐 0건. 실연동 항목은 CI 실연동 통합 테스트 통과 전 '미확인'
- 합계: 준비한 결함 120 · 탐지 58 · 오탐 24
- 상태 집계: 미구현 7, 미확인 7, 부분 12, 연결 안 됨 2, 완료 18
- 실행 매니페스트: 실행하지 않은 엔진 ['semantic_review', 'model_fact_reconcile'] (예시 전문: `docs/run_manifest_example.json`)

| 항목 | 내용 | 구현 코드 위치 | 파이프라인 호출 위치 | 단위·통합 테스트 | 준비한 결함 수 | 탐지 수 | 오탐 수 | 보고서(JSON·docx) | 요약 점수(scores.axes) | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | 변형 인용문 어절 diff(MODIFIED_QUOTE) | legal_engine/quote_diff.py | legal_engine/verifier.py:quote_changes | test_v3_d1_quote_diff.py | 2 | 1 | 0 | JSON O · docx O | 반영 | 부분(탐지율 50%) |
| D2 | 법원–사건부호 호환(COURT_CODE_MISMATCH) | legal_engine/citation_format.py, config/legal_rules/case_codes.yaml | legal_engine/verifier.py:format_violations | test_v3_d2_case_codes.py | 5 | 5 | 0 | JSON O · docx O | 반영 | 완료 |
| D3 | 다수·반대의견 귀속(MISATTRIBUTED_OPINION) | legal_engine/opinion_attribution.py | legal_engine/verifier.py:attribute_claim | test_v3_d3_opinion.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| D4 | 정확한 인용 VERIFIED_CITATION·요약 verified 반영 | legal_engine/verification_labels.py | legal_engine/verifier.py:citation_label | test_v3_d4_verified.py | 3 | 3 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D5 | 같은 인용의 모순 판정 방지(일관성 검사) | verification_engine/finalize.py(enforce_consistency) | verification_engine/finalize.py:enforce_consistency | test_v3_d5_consistency.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D6 | 증거 표 셀 파싱·호증 파서 | claim_engine/exhibits.py, attachments.py, document_engine 표 칸 추출 | claim_engine/attachments.py:parse_exhibit_label | test_v3_d6_evidence.py | 1 | 1 | 6 | JSON O · docx O | 반영 | 부분(오탐 6) |
| D7 | 출처 조회 실패는 UNVERIFIED(학술 인용) | legal_engine/verifier.verify_academic | legal_engine/verifier.py:verify_academic | test_v3_d7_sources.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D8 | 요약 표 문서 열·문서 간 그룹 | report_engine/docx_report.py | apps/api/routers/reports.py:build_report_docx | test_report_completion.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D9 | 보이는 AI 대상 억제 지시문 B등급 | adversarial_engine/scanner.py, patterns.py | verification_engine/pipeline.py:self.adversarial.scan | test_v3_d9_visible_instruction.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-1 | 쪽별 텍스트 레이어 판정·OCR 쪽 전 검사·분석 불가 명시 | document_engine/pdf_parser.py(_apply_ocr) | verification_engine/pipeline.py:page_coverage | test_ocr.py, test_v3_g2_ocr_quality.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-2 | 숨김 텍스트 일반화(대비비·투명도·렌더모드) | document_engine/pdf_parser.py(_render_facts, _apply_contrast) | document_engine/pdf_parser.py:_apply_contrast | test_v3_j4_visibility.py | 4 | 3 | 0 | JSON O · docx O | 반영 | 부분(탐지율 75%) |
| §3-3 | 구조 경로(문서 속성 전체 키·주석·북마크·양식·첨부) 분류기 투입 | adversarial_engine/scanner.py, structure_layers | verification_engine/pipeline.py:self.adversarial.scan | test_v4_p7_injection_paths.py | 5 | 0 | 0 | — | — | 미구현 |
| §3-4 | NFKC·폭 0·Base64 디코딩·자모 재조합 후 분류 | adversarial_engine/unicode_scan.py, encoding_scan.py | adversarial_engine/scanner.py:decode_candidates | test_v4_p7_injection_paths.py | 4 | 0 | 0 | — | — | 미구현 |
| §3-5 | 산술·기간 재계산 | claim_engine/calculation.py, fact_checks.py | verification_engine/pipeline.py:check_periods | test_v3_j3_arithmetic.py, test_v4_s35_periods_subtotals.py | 3 | 1 | 1 | JSON O · docx O | 반영 | 부분(탐지율 33%, 오탐 1) |
| §3-6 | AI 잔재 패턴(사전 분리) | verification_engine/ai_residue.py, config/ai_residue_patterns.yaml | verification_engine/pipeline.py:residue_findings(호출 없음) | test_v4_ai_residue.py | 3 | 0 | 0 | — | — | 연결 안 됨 |
| G1 | 헌재 결정 조회(detc) 정확 일치 | source_adapters/law_go_kr.py(search_case) | legal_engine/verifier.py:search_case | tests/live/test_live_sources.py | — | — | — | — | — | 미확인 |
| G2 | 한국어 OCR 품질(쪽별 신뢰도·한글 비율) | document_engine/ocr.py(page_quality) | document_engine/pdf_parser.py:page_quality | test_v3_g2_ocr_quality.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| G3 | 항·호 단위 결합('같은 조 제N항') | legal_engine/citation_extractor.py(_resolve_article_references) | legal_engine/citation_extractor.py:_resolve_article_references | test_v3_g3_paragraph_binding.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| G4 | 법리 주장 유형 분류→근거 조회→판단 | legal_engine/claim_review.py | verification_engine/pipeline.py:review_claims | test_v3_g4_claims.py, test_v4_g4_reasoning_axis.py | 3 | 2 | 0 | JSON O · docx O | 일부 반영 | 부분(탐지율 67%, 요약 점수 미반영) |
| G5 | 사실 저장소(문서 간·문서 안)·증거 선후 | claim_engine/fact_store.py, evidence_consistency.py | verification_engine/pipeline.py:cross_document_facts | test_v3_g5_facts.py, test_v4_p1_facts.py | 3 | 0 | 0 | — | — | 미구현 |
| G6 | 오탐 제거(파일명 표지 등) | forensic_engine/covert.py | verification_engine/pipeline.py:self.forensic.scan | test_v3_g6_filename.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| J1 | 헌재 조회 재조회·정확 일치(병합 표기 포함) | source_adapters/law_go_kr.py | legal_engine/verifier.py:search_case | tests/live/test_live_sources.py | — | — | — | — | — | 미확인 |
| J2 | AI 모델 사실 모순 지적 결정론 재검증 | verification_engine/ai_document_detector.py | verification_engine/pipeline.py:reconcile_model_fact_remarks | tests/live/test_live_models.py | — | — | — | — | — | 미확인 |
| J3 | 산식 행('a × b = c') 검산 | claim_engine/calculation.py(evaluate_expression) | verification_engine/pipeline.py:self.calculation.verify_document | test_v3_j3_arithmetic.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| J4 | 글자별 가시성(투명도·대비·가림) | document_engine/pdf_parser.py | document_engine/pdf_parser.py:_render_facts | test_v3_j4_visibility.py | 3 | 1 | 0 | JSON O · docx O | 반영 | 부분(탐지율 33%) |
| J5 | 조회 실패는 NOT_FOUND가 아닌 UNVERIFIED | legal_engine/verifier.py | legal_engine/verifier.py:verify_case | test_v3_g1_detc.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| J6 | scanned_layers에 실제 검사 경로 기록 | adversarial_engine/scanner.py | verification_engine/pipeline.py:self.adversarial.scan | test_v4_p7_injection_paths.py | 6 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 부분(탐지율 17%) |
| R1 | 다른 서면을 조항 원문으로 쓰지 않음 | legal_engine/internal_citation.py | verification_engine/pipeline.py:_internal_citation_check | test_v2_root_causes.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R2 | 인용문을 올바른 인용에 결합(기대값 대조) | legal_engine/citation_extractor.py(bind_quotes) | legal_engine/citation_extractor.py:bind_quotes | test_v2_root_causes.py | 7 | 6 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 부분(탐지율 86%) |
| R3 | 줄바꿈으로 법원·선고일 유실 방지(읽기 본문) | document_engine/reading_text.py | legal_engine/citation_extractor.py:build_reading_text | tests/live/test_live_sources.py | 1 | 1 | — | — | — | 미확인 |
| R4 | 사건번호 정확 일치 기록만 채택 | source_adapters/law_go_kr.py | legal_engine/verifier.py:search_case | tests/live/test_live_sources.py | — | — | — | — | — | 미확인 |
| R5 | 조문 본문 대조(claim_text) | legal_engine/provision_content.py | legal_engine/source_review.py:compare_claim_to_provision | test_v2_root_causes.py, test_v3_g3_paragraph_binding.py | 1 | 0 | 0 | — | — | 미구현 |
| R6 | 머리글·바닥글 반복 줄 제외 | document_engine/reading_text.py(mark_running_heads) | adversarial_engine/scanner.py:running_head | tests/live/test_live_sources.py | 1 | 1 | — | — | — | 미확인 |
| R7 | 법령명 추출 | legal_engine/normalize.py(law_name_suffix) | legal_engine/citation_extractor.py:law_name_suffix | test_v2_root_causes.py | 4 | 4 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R8 | 숨김 경로별 개별 탐지(Tr 3·가림) | document_engine/pdf_parser.py, adversarial_engine/scanner.py | verification_engine/pipeline.py:self.adversarial.scan | test_v2_root_causes.py | 2 | 1 | 0 | JSON O · docx O | 반영 | 부분(탐지율 50%) |
| R9 | 증거 정합성(달력·결번) | claim_engine/evidence_consistency.py | verification_engine/pipeline.py:check_evidence_consistency | test_v2_root_causes.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| R10 | AI 판정 축과 문서 결과 일치 | verification_engine/ai_document_detector.py, scoring.py | verification_engine/pipeline.py:create_ai_detector_findings | tests/live/test_live_models.py | — | — | — | — | — | 미확인 |
| R11 | 같은 인용 중복 추출 방지 | legal_engine/citation_extractor.py | verification_engine/pipeline.py:extract_citations | test_v2_root_causes.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| P1 | 사실 저장소 교차검증(CROSS_DOC_INCONSISTENCY, 문서 간·문서 안, 자릿수 뒤바뀜) | claim_engine/fact_store.py | verification_engine/pipeline.py:cross_document_facts | test_v4_p1_facts.py | 5 | 0 | 2 | — | — | 미구현 |
| P3 | 법령 적용 시점(행위시법) 판단 | legal_engine/temporal_review.py | verification_engine/pipeline.py:review_temporal_application(호출 없음) | test_v4_p3_temporal.py | 2 | 0 | 0 | — | — | 연결 안 됨 |
| P4 | 증거·금액 검사 보강(한글 금액·목록↔원문·번호 중복·서면 작성일 이후) | claim_engine/korean_amount.py, evidence_consistency.py | verification_engine/pipeline.py:check_evidence_consistency | test_v4_p4_evidence_amounts.py | 6 | 0 | 7 | — | — | 미구현 |
| P5 | 법리 검토 확장(재량↔의무·판례 방향 반대·절차 규칙·양형 사유 혼동) | legal_engine/provision_content.py, opinion_attribution.py, config/legal_rules/rules.json | verification_engine/pipeline.py:review_claims | test_v4_p5_legal_rules.py | 4 | 0 | 0 | — | — | 미구현 |
| P6 | AI 판별 집계(관여 여부·범위 분리, 약한 신호는 참고 부록) | verification_engine/ai_document_detector.py | verification_engine/pipeline.py:create_ai_detector_findings | test_v4_p6_ai_aggregation.py | 1 | 1 | 6 | JSON O · docx O | 반영 안 됨 | 부분(오탐 6, 요약 점수 미반영) |
| P7 | 인젝션 경로 전수 검사·경로별 개별 finding | adversarial_engine/scanner.py, document_engine/pdf_parser.py | verification_engine/pipeline.py:self.adversarial.scan | test_v4_p7_injection_paths.py | 17 | 4 | 2 | JSON O · docx O | 반영 | 부분(탐지율 24%, 오탐 2) |
| P8 | 파서 대체 경로·손상 PDF·회전 스캔·보고서 직렬화 | document_engine/pdf_parser.py, report_engine/serialize.py | verification_engine/pipeline.py:parse_document | test_v4_p8_parser_report.py | 3 | 1 | 0 | JSON O · docx O | 반영 | 부분(탐지율 33%) |
| P2 | 법원–사건부호(=D2), 공백 정규화·헌재 일련번호 | legal_engine/citation_format.py, config/legal_rules/case_codes.yaml | legal_engine/verifier.py:format_violations | test_v3_d2_case_codes.py | 5 | 5 | 0 | JSON O · docx O | 반영 | 완료 |

<details><summary>결함별 탐지 내역</summary>

- **D1** D1-1 민사: 정도 부사 '현저히' 삭제(2015다90022): 미탐지; D1-2 행정: 부정 치환(2013두90066): 탐지 — 직접 인용문 변형(MODIFIED_QUOTE, 부정 변경): 대법원 2014. 2. 13. 선고 2013두90066 판결 — 치환(부정) — 원문 「상대방에게 [
- **D2** D2-1 민사: 대법원+1심 부호(2018구합51234): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2019. 3. 14. 선고 2018구합51234 판결; D2-2 민사: 헌재+법원 부호(2018다90044): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2019. 4. 11. 선고 2018다90044 결정; D2-3 행정: 대법원+헌재 부호(2019헌바90055): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 5. 28. 선고 2019헌바90055 판결; D2-4 형사: 헌재+형사 부호(2020도12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2021. 3. 25. 2020도12345 결정; D2-5 가사: 대법원+가사 1심 부호(2019드단12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 9. 24. 선고 2019드단12345 판결
- **D3** D3-1 민사: 반대의견을 판시처럼 요약(2016다90033): 탐지 — 반대의견 취지를 판결의 판시처럼 요약: 대법원 2017. 6. 22. 선고 2016다90033 판결
- **D4** D4-1 민사: 정확한 직접 인용(2014다90011): 탐지; D4-2 가사: 판결 취지의 정확한 요약(2018므90088): 탐지; D4-3 요약 점수 verified 반영: 탐지
- **D5** D5-1 모든 인용에 CONTRADICTED와 VERIFIED가 함께 붙지 않음: 탐지
- **D6** D6-1 민사 증거표 칸 단위 파싱(갑 제1호증 진단서 작성일): 탐지 — 증거 작성일이 달력에 없는 날짜다: 갑 제1호증 진단서 작성일 2023. 2. 30.; 오탐(별도 판정): 6건
- **D7** D7-1 민사: 학술 인용을 추출하고 UNVERIFIED로 둠: 탐지
- **D8** D8-1 docx 요약 표에 문서명·문서 간 그룹: 탐지
- **D9** D9-1 민사: 보이는 본문의 검증 억제 지시(B 이상): 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 보이는 본문
- **§3-1** §3-1a 형사: 1·2쪽 텍스트, 3쪽 OCR: 탐지; §3-1b 형사 3쪽(OCR 글자)의 달력에 없는 날짜: 탐지 — 날짜 불가능(INVALID_FORMAT): 대법원 2019. 2. 30. 선고 2018 도 12345 판결
- **§3-2** §3-2a 흰 글자: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION, OUTPUT_MANIPULATION — 경로: 흰 글자(배경과 같은 색); §3-2b 투명 글자: 미탐지; §3-2c 저대비: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 배경과 대비가 거의 없는 글자; §3-2d 렌더모드 3: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 보이지 않는 렌더모드(Tr 3)
- **§3-3** §3-3a 문서 속성 사용자 키: 미탐지; §3-3b 주석: 미탐지; §3-3c 북마크: 미탐지; §3-3d 양식 필드: 미탐지; §3-3e 첨부파일: 미탐지
- **§3-4** §3-4a Base64: 미탐지; §3-4b 전각: 미탐지; §3-4c 폭 0 문자: 미탐지; §3-4d 한글 자모 분리: 미탐지
- **§3-5** §3-5a 민사 손해액 표 합계(차이 600,000원): 미탐지; §3-5b 민사 산식 행(80,000원 × 30일): 탐지 — 산식의 계산 결과가 기재 금액과 다르다 (차이 100,000원); §3-5c 민사 시효 만료일(2026. 9. 15.): 미탐지; 오탐: 합계가 세부 금액 합산값과 다르다 (차이 -17,700,000원) (민사_준비서면.pdf)
- **§3-6** §3-6a 챗봇 맺음말: 미탐지; §3-6b 출처 토큰: 미탐지; §3-6c 렌더링되지 않은 마크다운 표: 미탐지
- **G1** 실연동 통합 테스트 결과 없음
- **G2** G2-1 형사 3쪽 OCR 품질 기록: 탐지
- **G3** G3-1 민사: '같은 조 제2항' → 가상손해배상법 제10조 제2항: 탐지
- **G4** G4-1 민사: 전칭 일반화: 탐지 — 법리 검토(전칭 일반화): 근거 없는 전칭 법리 명제 — '8. 법원은 이와 같은 사고에서 예외 없이 항상 원고 승소 판결을 해 왔다.'; G4-2 민사: 법률 근거 없는 배수 배상: 탐지 — 법리 검토(근거 없는 청구 유형): 개별 법률 근거 없이 배수·징벌적 배상 청구 — '9. 원고는 피고에게 손해액의 3배에 해당하는 징벌적 손해배상을 청구한다.'; G4-3 행정: 취소소송 제소기간 배제 주장: 미탐지
- **G5** G5-1 민사 부위 좌우(문서 간): 미탐지; G5-2 민사 사고일(문서 간): 미탐지; G5-3 민사 증거 작성일<사건일(사고경위서): 미탐지
- **G6** G6-1 파일명 표지 오탐 없음: 탐지
- **J1** 실연동 통합 테스트 결과 없음
- **J2** 실연동 통합 테스트 결과 없음
- **J3** J3-1 민사 간병비 산식 행: 탐지 — 산식의 계산 결과가 기재 금액과 다르다 (차이 100,000원)
- **J4** J4-1 투명 글자: 미탐지; J4-2 이미지로 덮은 글자: 미탐지; J4-3 저대비 글자: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 배경과 대비가 거의 없는 글자
- **J5** J5-1 오프라인 조회 실패 인용에 NOT_FOUND 판정 없음: 탐지
- **J6** J6-metadata scanned_layers에 metadata: 미탐지; J6-outline scanned_layers에 outline: 미탐지; J6-annotation scanned_layers에 annotation: 탐지; J6-form_field scanned_layers에 form_field: 미탐지; J6-attachment scanned_layers에 attachment: 미탐지; J6-image_ocr scanned_layers에 image_ocr: 미탐지
- **R1** R1-1 서면 간 조항 대조 오판 없음: 탐지
- **R2** 2014다90011: 기대 인용문 있음 / 결과 ['있음', '없음'] → 성공; 2015다90022: 기대 인용문 있음 / 결과 ['없음', '없음'] → 실패; 2016다90033: 기대 인용문 없음 / 결과 ['없음'] → 성공; 2018구합51234: 기대 인용문 없음 / 결과 ['없음'] → 성공; 2018다90044: 기대 인용문 없음 / 결과 ['없음'] → 성공; 2013두90066: 기대 인용문 있음 / 결과 ['있음'] → 성공; 2019헌바90055: 기대 인용문 없음 / 결과 ['없음'] → 성공
- **R3** 실연동 통합 테스트 결과 없음; 오프라인 합성 1/1; R3-1 민사: 줄바꿈으로 나뉜 '대법원 2016. 5. 12. / 선고 2015다90022': 탐지
- **R4** 실연동 통합 테스트 결과 없음
- **R5** R5-1 민사: 제10조 제2항 10년(원문 5년): 미탐지
- **R6** 실연동 통합 테스트 결과 없음; 오프라인 합성 1/1; R6-1 민사: 머리글의 '대법원 2014다90011 판결'을 인용으로 세지 않음(본문 2회): 탐지
- **R7** R7-가상손해배상법 법령명 '가상손해배상법' 추출: 탐지; R7-민법 법령명 '민법' 추출: 탐지; R7-가상형사법 법령명 '가상형사법' 추출: 탐지; R7-가상행정절차법 법령명 '가상행정절차법' 추출: 탐지
- **R8** R8-1 렌더모드 3: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 보이지 않는 렌더모드(Tr 3); R8-2 이미지로 덮은 글자: 미탐지
- **R9** R9-1 달력에 없는 작성일: 탐지 — 증거 작성일이 달력에 없는 날짜다: 갑 제1호증 진단서 작성일 2023. 2. 30.; R9-2 가지번호 결번: 탐지 — 가지번호가 비어 있다: 갑 제2호증의 1 결번
- **R10** 실연동 통합 테스트 결과 없음
- **R11** R11-1 중복 추출 0건: 탐지
- **P1** P1-1 민사 부위 좌우(준비서면↔진단서): 미탐지; P1-2 민사 부위 좌우(준비서면 본문↔첨부 진단서, 문서 안): 미탐지; P1-3 민사 사고일(준비서면↔진단서): 미탐지; P1-4 가사 원고 성명 표기(박○○↔이○○, 문서 안): 미탐지; P1-5 가사 청구금액 자릿수 뒤바뀜(소장 205,000,000↔답변서 250,000,000): 미탐지; 오탐: 문서마다 청구금액이 다르다: 민사_준비서면.pdf 금 35,000,000원, 가사_소장.pdf 205,000,000원 (민사_준비서면.pdf); 오탐(별도 판정): 1건
- **P3** P3-1 형사: 행위시 버전(5년)과 일치 — 확인, '현행과 다름' 안내: 미탐지; P3-2 형사: 어느 버전과도 불일치(10년) — 두 버전 값 제시: 미탐지
- **P4** P4-1 민사 한글 금액(칠백만원↔7,500,000원): 미탐지; P4-2 가사 한글 금액(이억오천만원↔205,000,000원): 미탐지; P4-3 가사 증거목록 금액↔첨부 원문(12,000,000↔21,000,000): 미탐지; P4-4 민사 호증 번호 중복(갑 제5호증): 미탐지; P4-5 민사 서면 작성일 이후 작성 증거(사실확인서): 미탐지; P4-6 민사 사건일 전 작성 증거(사고경위서): 미탐지; 오탐: 사건을 기록·증명하는 서증의 작성일이 그 사건보다 앞선다: 갑 제5호증 영수증 작성일 2023. 4. 1., 대상 2024. 6. 1. (민사_준비서면.pdf); 오탐(별도 판정): 6건
- **P5** P5-1 행정: '할 수 있다' 조문을 의무로 주장: 미탐지; P5-2 민사: 판결 취지 방향 반대 요약(2014다90011): 미탐지; P5-3 형사: 불이익변경금지 적용 범위 오인: 미탐지; P5-4 형사: 사후 변제를 범죄 불성립 사유로 주장: 미탐지
- **P6** P6-1 민사(AI 잔재 문서)에 AI 관여 근거 제시: 탐지 — 문서 일부의 AI 작성 가능성 (추정치 0.45, 근거 신뢰도는 별도 표시); 오탐: 문서 일부의 AI 작성 가능성 (추정치 0.35, 근거 신뢰도는 별도 표시) (민사_진단서.pdf); 오탐: 문서 일부의 AI 작성 가능성 (추정치 0.35, 근거 신뢰도는 별도 표시) (행정_의견서.pdf); 오탐: 문서 일부의 AI 작성 가능성 (추정치 0.35, 근거 신뢰도는 별도 표시) (형사_변론요지서.pdf); 오탐: 문서 일부의 AI 작성 가능성 (추정치 0.35, 근거 신뢰도는 별도 표시) (가사_소장.pdf); 오탐: 문서 일부의 AI 작성 가능성 (추정치 0.35, 근거 신뢰도는 별도 표시) (가사_답변서.pdf)
- **P7** P7-1 흰 글자: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION, OUTPUT_MANIPULATION — 경로: 흰 글자(배경과 같은 색); P7-2 투명 글자: 미탐지; P7-3 저대비: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 배경과 대비가 거의 없는 글자; P7-4 이미지로 덮은 글자: 미탐지; P7-5 렌더모드 3: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 보이지 않는 렌더모드(Tr 3); P7-6 초소형 글자: 미탐지; P7-7 페이지 밖: 미탐지; P7-8 문서 속성: 미탐지; P7-9 주석: 미탐지; P7-10 북마크: 미탐지; P7-11 양식 필드: 미탐지; P7-12 첨부파일: 미탐지; P7-13 Base64: 미탐지; P7-14 전각: 미탐지; P7-15 폭 0 문자: 미탐지; P7-16 한글 자모 분리: 미탐지; P7-17 민사: 보이는 본문 지시문: 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 보이는 본문; 오탐: META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 보이는 본문 (행정_의견서.pdf); 오탐: META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 보이는 본문 (행정_의견서.pdf)
- **P8** P8-1 손상 PDF 구조 손상 신호(MALFORMED_PDF): 미탐지; P8-2 손상 PDF 본문 추출(날짜 불가능 인용 판정): 탐지 — 날짜 불가능(INVALID_FORMAT): 대법원 2021. 4. 31. 선고 2020두12345 판결; P8-3 회전 스캔 쪽 방향 보정 후 판정(2016도54321): 미탐지
- **P2** D2와 같은 결함 집합으로 판정; D2-1 민사: 대법원+1심 부호(2018구합51234): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2019. 3. 14. 선고 2018구합51234 판결; D2-2 민사: 헌재+법원 부호(2018다90044): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2019. 4. 11. 선고 2018다90044 결정; D2-3 행정: 대법원+헌재 부호(2019헌바90055): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 5. 28. 선고 2019헌바90055 판결; D2-4 형사: 헌재+형사 부호(2020도12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2021. 3. 25. 2020도12345 결정; D2-5 가사: 대법원+가사 1심 부호(2019드단12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 9. 24. 선고 2019드단12345 판결

</details>

## 수정 후 (0.8.5)

- 실행일: 2026-09-25 · 프로그램 0.8.5 · 규칙 2026.09.25.2
- 합성 문서(모두 PDF, 표·여러 쪽·머리글/바닥글): 민사 준비서면·진단서, 행정 의견서(숨김·구조 경로 인젝션)·손상 문서, 형사 변론요지서(3쪽 스캔·4쪽 회전 스캔), 가사 소장·답변서 — `scripts/audit/corpus.py`
- 완료 기준: 파이프라인 호출·보고서·요약 점수 반영, 탐지율 90% 이상, 오탐 0건. 실연동 항목은 CI 실연동 통합 테스트 통과 전 '미확인'
- 합계: 준비한 결함 139 · 탐지 139 · 오탐 0
- 상태 집계: 완료 46
- 실행 매니페스트: 실행하지 않은 엔진 ['semantic_review', 'model_fact_reconcile'] (예시 전문: `docs/run_manifest_example.json`)

| 항목 | 내용 | 구현 코드 위치 | 파이프라인 호출 위치 | 단위·통합 테스트 | 준비한 결함 수 | 탐지 수 | 오탐 수 | 보고서(JSON·docx) | 요약 점수(scores.axes) | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | 변형 인용문 어절 diff(MODIFIED_QUOTE) | legal_engine/quote_diff.py | legal_engine/verifier.py:quote_changes | test_v3_d1_quote_diff.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| D2 | 법원–사건부호 호환(COURT_CODE_MISMATCH) | legal_engine/citation_format.py, config/legal_rules/case_codes.yaml | legal_engine/verifier.py:format_violations | test_v3_d2_case_codes.py | 5 | 5 | 0 | JSON O · docx O | 반영 | 완료 |
| D3 | 다수·반대의견 귀속(MISATTRIBUTED_OPINION) | legal_engine/opinion_attribution.py | legal_engine/verifier.py:attribute_claim | test_v3_d3_opinion.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| D4 | 정확한 인용 VERIFIED_CITATION·요약 verified 반영 | legal_engine/verification_labels.py | legal_engine/verifier.py:citation_label | test_v3_d4_verified.py | 3 | 3 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D5 | 같은 인용의 모순 판정 방지(일관성 검사) | verification_engine/finalize.py(enforce_consistency) | verification_engine/finalize.py:enforce_consistency | test_v3_d5_consistency.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D6 | 증거 표 셀 파싱·호증 파서 | claim_engine/exhibits.py, attachments.py, document_engine 표 칸 추출 | claim_engine/attachments.py:parse_exhibit_label | test_v3_d6_evidence.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| D7 | 출처 조회 실패는 UNVERIFIED(학술 인용) | legal_engine/verifier.verify_academic | legal_engine/verifier.py:verify_academic | test_v3_d7_sources.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D8 | 요약 표 문서 열·문서 간 그룹 | report_engine/docx_report.py | apps/api/routers/reports.py:build_report_docx | test_report_completion.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| D9 | 보이는 AI 대상 억제 지시문 B등급 | adversarial_engine/scanner.py, patterns.py | verification_engine/pipeline.py:self.adversarial.scan | test_v3_d9_visible_instruction.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-1 | 쪽별 텍스트 레이어 판정·OCR 쪽 전 검사·분석 불가 명시 | document_engine/pdf_parser.py(_apply_ocr) | verification_engine/pipeline.py:page_coverage | test_ocr.py, test_v3_g2_ocr_quality.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-2 | 숨김 텍스트 일반화(대비비·투명도·렌더모드) | document_engine/pdf_parser.py(_render_facts, _apply_contrast) | document_engine/pdf_parser.py:_apply_contrast | test_v3_j4_visibility.py | 4 | 4 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-3 | 구조 경로(문서 속성 전체 키·주석·북마크·양식·첨부) 분류기 투입 | adversarial_engine/scanner.py, structure_layers | verification_engine/pipeline.py:self.adversarial.scan | test_v4_p7_injection_paths.py | 5 | 5 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-4 | NFKC·폭 0·Base64 디코딩·자모 재조합 후 분류 | adversarial_engine/unicode_scan.py, encoding_scan.py | adversarial_engine/scanner.py:decode_candidates | test_v4_p7_injection_paths.py | 4 | 4 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-5 | 산술·기간 재계산 | claim_engine/calculation.py, fact_checks.py | verification_engine/pipeline.py:check_periods | test_v3_j3_arithmetic.py, test_v4_s35_periods_subtotals.py | 3 | 3 | 0 | JSON O · docx O | 반영 | 완료 |
| §3-6 | AI 잔재 패턴(사전 분리) | verification_engine/ai_residue.py, config/ai_residue_patterns.yaml | verification_engine/pipeline.py:residue_findings | test_v4_ai_residue.py | 3 | 3 | 0 | JSON O · docx O | 반영 | 완료 |
| G1 | 헌재 결정 조회(detc) 정확 일치 | source_adapters/law_go_kr.py(search_case) | legal_engine/verifier.py:search_case | tests/live/test_live_sources.py | 11 | 11 | 0 | — | — | 완료(실연동) |
| G2 | 한국어 OCR 품질(쪽별 신뢰도·한글 비율) | document_engine/ocr.py(page_quality) | document_engine/pdf_parser.py:page_quality | test_v3_g2_ocr_quality.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| G3 | 항·호 단위 결합('같은 조 제N항') | legal_engine/citation_extractor.py(_resolve_article_references) | legal_engine/citation_extractor.py:_resolve_article_references | test_v3_g3_paragraph_binding.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| G4 | 법리 주장 유형 분류→근거 조회→판단 | legal_engine/claim_review.py | verification_engine/pipeline.py:review_claims | test_v3_g4_claims.py, test_v4_g4_reasoning_axis.py | 3 | 3 | 0 | JSON O · docx O | 반영 | 완료 |
| G5 | 사실 저장소(문서 간·문서 안)·증거 선후 | claim_engine/fact_store.py, evidence_consistency.py | verification_engine/pipeline.py:cross_document_facts | test_v3_g5_facts.py, test_v4_p1_facts.py | 3 | 3 | 0 | JSON O · docx O | 반영 | 완료 |
| G6 | 오탐 제거(파일명 표지 등) | forensic_engine/covert.py | verification_engine/pipeline.py:self.forensic.scan | test_v3_g6_filename.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| J1 | 헌재 조회 재조회·정확 일치(병합 표기 포함) | source_adapters/law_go_kr.py | legal_engine/verifier.py:search_case | tests/live/test_live_sources.py | 2 | 2 | 0 | — | — | 완료(실연동) |
| J2 | AI 모델 사실 모순 지적 결정론 재검증 | verification_engine/ai_document_detector.py | verification_engine/pipeline.py:reconcile_model_fact_remarks | tests/live/test_live_models.py | 2 | 2 | 0 | — | — | 완료(실연동) |
| J3 | 산식 행('a × b = c') 검산 | claim_engine/calculation.py(evaluate_expression) | verification_engine/pipeline.py:self.calculation.verify_document | test_v3_j3_arithmetic.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| J4 | 글자별 가시성(투명도·대비·가림) | document_engine/pdf_parser.py | document_engine/pdf_parser.py:_render_facts | test_v3_j4_visibility.py | 3 | 3 | 0 | JSON O · docx O | 반영 | 완료 |
| J5 | 조회 실패는 NOT_FOUND가 아닌 UNVERIFIED | legal_engine/verifier.py | legal_engine/verifier.py:verify_case | test_v3_g1_detc.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| J6 | scanned_layers에 실제 검사 경로 기록 | adversarial_engine/scanner.py | verification_engine/pipeline.py:self.adversarial.scan | test_v4_p7_injection_paths.py | 6 | 6 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R1 | 다른 서면을 조항 원문으로 쓰지 않음 | legal_engine/internal_citation.py | verification_engine/pipeline.py:_internal_citation_check | test_v2_root_causes.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R2 | 인용문을 올바른 인용에 결합(기대값 대조) | legal_engine/citation_extractor.py(bind_quotes) | legal_engine/citation_extractor.py:bind_quotes | test_v2_root_causes.py | 7 | 7 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R3 | 줄바꿈으로 법원·선고일 유실 방지(읽기 본문) | document_engine/reading_text.py | legal_engine/citation_extractor.py:build_reading_text | tests/live/test_live_sources.py | 1 | 1 | 0 | — | — | 완료(실연동) |
| R4 | 사건번호 정확 일치 기록만 채택 | source_adapters/law_go_kr.py | legal_engine/verifier.py:search_case | tests/live/test_live_sources.py | 3 | 3 | 0 | — | — | 완료(실연동) |
| R5 | 조문 본문 대조(claim_text) | legal_engine/provision_content.py | legal_engine/source_review.py:compare_claim_to_provision | test_v2_root_causes.py, test_v3_g3_paragraph_binding.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| R6 | 머리글·바닥글 반복 줄 제외 | document_engine/reading_text.py(mark_running_heads) | adversarial_engine/scanner.py:running_head | tests/live/test_live_sources.py | 1 | 1 | 0 | — | — | 완료(실연동) |
| R7 | 법령명 추출 | legal_engine/normalize.py(law_name_suffix) | legal_engine/citation_extractor.py:law_name_suffix | test_v2_root_causes.py | 4 | 4 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| R8 | 숨김 경로별 개별 탐지(Tr 3·가림) | document_engine/pdf_parser.py, adversarial_engine/scanner.py | verification_engine/pipeline.py:self.adversarial.scan | test_v2_root_causes.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| R9 | 증거 정합성(달력·결번) | claim_engine/evidence_consistency.py | verification_engine/pipeline.py:check_evidence_consistency | test_v2_root_causes.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| R10 | AI 판정 축과 문서 결과 일치 | verification_engine/ai_document_detector.py, scoring.py | verification_engine/pipeline.py:create_ai_detector_findings | tests/live/test_live_models.py | 1 | 1 | 0 | — | — | 완료(실연동) |
| R11 | 같은 인용 중복 추출 방지 | legal_engine/citation_extractor.py | verification_engine/pipeline.py:extract_citations | test_v2_root_causes.py | 1 | 1 | 0 | 해당 없음(판정 산출물) | 해당 없음 | 완료 |
| P1 | 사실 저장소 교차검증(CROSS_DOC_INCONSISTENCY, 문서 간·문서 안, 자릿수 뒤바뀜) | claim_engine/fact_store.py | verification_engine/pipeline.py:cross_document_facts | test_v4_p1_facts.py | 5 | 5 | 0 | JSON O · docx O | 반영 | 완료 |
| P3 | 법령 적용 시점(행위시법) 판단 | legal_engine/temporal_review.py | verification_engine/pipeline.py:review_temporal_application | test_v4_p3_temporal.py | 2 | 2 | 0 | JSON O · docx O | 반영 | 완료 |
| P4 | 증거·금액 검사 보강(한글 금액·목록↔원문·번호 중복·서면 작성일 이후) | claim_engine/korean_amount.py, evidence_consistency.py | verification_engine/pipeline.py:check_evidence_consistency | test_v4_p4_evidence_amounts.py | 6 | 6 | 0 | JSON O · docx O | 반영 | 완료 |
| P5 | 법리 검토 확장(재량↔의무·판례 방향 반대·절차 규칙·양형 사유 혼동) | legal_engine/provision_content.py, opinion_attribution.py, config/legal_rules/rules.json | verification_engine/pipeline.py:review_claims | test_v4_p5_legal_rules.py | 4 | 4 | 0 | JSON O · docx O | 반영 | 완료 |
| P6 | AI 판별 집계(관여 여부·범위 분리, 약한 신호는 참고 부록) | verification_engine/ai_document_detector.py | verification_engine/pipeline.py:create_ai_detector_findings | test_v4_p6_ai_aggregation.py | 1 | 1 | 0 | JSON O · docx O | 반영 | 완료 |
| P7 | 인젝션 경로 전수 검사·경로별 개별 finding | adversarial_engine/scanner.py, document_engine/pdf_parser.py | verification_engine/pipeline.py:self.adversarial.scan | test_v4_p7_injection_paths.py | 17 | 17 | 0 | JSON O · docx O | 반영 | 완료 |
| P8 | 파서 대체 경로·손상 PDF·회전 스캔·보고서 직렬화 | document_engine/pdf_parser.py, report_engine/serialize.py | verification_engine/pipeline.py:parse_document | test_v4_p8_parser_report.py | 3 | 3 | 0 | JSON O · docx O | 반영 | 완료 |
| P2 | 법원–사건부호(=D2), 공백 정규화·헌재 일련번호 | legal_engine/citation_format.py, config/legal_rules/case_codes.yaml | legal_engine/verifier.py:format_violations | test_v3_d2_case_codes.py | 5 | 5 | 0 | JSON O · docx O | 반영 | 완료 |

<details><summary>결함별 탐지 내역</summary>

- **D1** D1-1 민사: 정도 부사 '현저히' 삭제(2015다90022): 탐지 — 직접 인용문 변형(MODIFIED_QUOTE, 정도 부사 변경): 대법원 2016. 5. 12. 선고 2015다90022 판결 — 삭제(정도 부사) — 원문 「비; D1-2 행정: 부정 치환(2013두90066): 탐지 — 직접 인용문 변형(MODIFIED_QUOTE, 부정 변경): 대법원 2014. 2. 13. 선고 2013두90066 판결 — 치환(부정) — 원문 「상대방에게 [
- **D2** D2-1 민사: 대법원+1심 부호(2018구합51234): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2019. 3. 14. 선고 2018구합51234 판결; D2-2 민사: 헌재+법원 부호(2018다90044): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2019. 4. 11. 선고 2018다90044 결정; D2-3 행정: 대법원+헌재 부호(2019헌바90055): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 5. 28. 선고 2019헌바90055 판결; D2-4 형사: 헌재+형사 부호(2020도12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2021. 3. 25. 2020도12345 결정; D2-5 가사: 대법원+가사 1심 부호(2019드단12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 9. 24. 선고 2019드단12345 판결
- **D3** D3-1 민사: 반대의견을 판시처럼 요약(2016다90033): 탐지 — 반대의견 취지를 판결의 판시처럼 요약: 대법원 2017. 6. 22. 선고 2016다90033 판결
- **D4** D4-1 민사: 정확한 직접 인용(2014다90011): 탐지; D4-2 가사: 판결 취지의 정확한 요약(2018므90088): 탐지; D4-3 요약 점수 verified 반영: 탐지
- **D5** D5-1 모든 인용에 CONTRADICTED와 VERIFIED가 함께 붙지 않음: 탐지
- **D6** D6-1 민사 증거표 칸 단위 파싱(갑 제1호증 진단서 작성일): 탐지 — 증거 작성일이 달력에 없는 날짜다: 갑 제1호증 진단서 작성일 2023. 2. 30.
- **D7** D7-1 민사: 학술 인용을 추출하고 UNVERIFIED로 둠: 탐지
- **D8** D8-1 docx 요약 표에 문서명·문서 간 그룹: 탐지
- **D9** D9-1 민사: 보이는 본문의 검증 억제 지시(B 이상): 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 보이는 본문
- **§3-1** §3-1a 형사: 1·2쪽 텍스트, 3쪽 OCR: 탐지; §3-1b 형사 3쪽(OCR 글자)의 달력에 없는 날짜: 탐지 — 날짜 불가능(INVALID_FORMAT): 대법원 2019. 2. 30. 선고 2018 도 12345 판결
- **§3-2** §3-2a 흰 글자: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION, OUTPUT_MANIPULATION — 경로: 흰 글자(배경과 같은 색); §3-2b 투명 글자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 투명 글자(채움 투명도 0); §3-2c 저대비: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 배경과 대비가 거의 없는 글자; §3-2d 렌더모드 3: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 보이지 않는 렌더모드(Tr 3)
- **§3-3** §3-3a 문서 속성 사용자 키: 탐지 — 문서 속성 'ReviewerNote'에 지시형 문자열이 있다 — 경로: 문서 속성(메타데이터); §3-3b 주석: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 주석; §3-3c 북마크: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 북마크(개요); §3-3d 양식 필드: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 양식 필드 값; §3-3e 첨부파일: 탐지 — 첨부파일 'memo.txt' 안에 지시형 문자열이 있다 — 경로: 첨부파일 내용
- **§3-4** §3-4a Base64: 탐지 — BASE64 인코딩된 지시형 문자열 — 경로: 인코딩 문자열(BASE64); §3-4b 전각: 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 전각·호환 문자(NFKC 정규화) · 화면 표시 글자; §3-4c 폭 0 문자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 표시 대체 문자열(ActualText) · 폭 0 문자; §3-4d 한글 자모 분리: 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 한글 자모 분리(재조합) · 화면 표시 글자
- **§3-5** §3-5a 민사 손해액 표 합계(차이 600,000원): 탐지 — 합계가 세부 금액 합산값과 다르다 (차이 600,000원); §3-5b 민사 산식 행(80,000원 × 30일): 탐지 — 산식의 계산 결과가 기재 금액과 다르다 (차이 100,000원); §3-5c 민사 시효 만료일(2026. 9. 15.): 탐지 — 기간 만료일이 계산과 다르다: 문서 2026. 9. 15. / 계산 2026. 3. 15. — 2023. 3. 15.부터 3년이 경과한 2026. 9. 15.
- **§3-6** §3-6a 챗봇 맺음말: 탐지 — AI 응답 잔재(AI_RESPONSE_RESIDUE): 챗봇 맺음말 — '도움이 되셨길 바랍니다'; §3-6b 출처 토큰: 탐지 — AI 응답 잔재(AI_RESPONSE_RESIDUE): 생성 도구의 출처 표시 토큰 — '[출처: 2]'; §3-6c 렌더링되지 않은 마크다운 표: 탐지 — AI 응답 잔재(AI_RESPONSE_RESIDUE): 렌더링되지 않은 마크다운 표 — '\| 항목 \| 금액 \| \|---\|'
- **G1** 헌재 결정 11/11건 사건번호 정확 일치(다른 번호 기록 0건은 채택하지 않음) (커밋 b73504d·2026-09-25T01:29:47+00:00 통과; 최근 실행 075cf94은 헌재 결정 조회: 무응답 11건으로 판정 보류)
- **G2** G2-1 형사 3쪽 OCR 품질 기록: 탐지
- **G3** G3-1 민사: '같은 조 제2항' → 가상손해배상법 제10조 제2항: 탐지
- **G4** G4-1 민사: 전칭 일반화: 탐지 — 법리 검토(전칭 일반화): 근거 없는 전칭 법리 명제 — '8. 법원은 이와 같은 사고에서 예외 없이 항상 원고 승소 판결을 해 왔다.'; G4-2 민사: 법률 근거 없는 배수 배상: 탐지 — 법리 검토(근거 없는 청구 유형): 개별 법률 근거 없이 배수·징벌적 배상 청구 — '9. 원고는 피고에게 손해액의 3배에 해당하는 징벌적 손해배상을 청구한다.'; G4-3 행정: 취소소송 제소기간 배제 주장: 탐지 — 법리 검토: 조문에 없는 제소기간 예외 주장 — '무효확인소송이 아닌 이 취소소송에는 제소기간 제한이 적용되지 않는다.' (사람 판단 필요)
- **G5** G5-1 민사 부위 좌우(문서 간): 탐지 — 문서마다 슬관절의 좌·우가 다르다: 민사_준비서면.pdf 좌측, 민사_진단서.pdf 우측; G5-2 민사 사고일(문서 간): 탐지 — 문서마다 사고일(사건일)이 다르다: 민사_준비서면.pdf 2023-03-15, 민사_진단서.pdf 2023-03-16; G5-3 민사 증거 작성일<사건일(사고경위서): 탐지 — 사건을 기록·증명하는 서증의 작성일이 그 사건보다 앞선다: 갑 제3호증 사고경위서 작성일 2023. 1. 10., 대상 2023. 3. 15.
- **G6** G6-1 파일명 표지 오탐 없음: 탐지
- **J1** 병합 표기 2/2건 대표 번호로 확인 (커밋 b73504d·2026-09-25T01:29:47+00:00 통과; 최근 실행 075cf94은 병합 표기 조회: 무응답 2건으로 판정 보류)
- **J2** 모델 3개 응답, 결정론 재계산 2건, 모델 지적 연결 5건, 사람 확인으로 남은 지적 1건, 확인 문장의 오분류 0건
- **J3** J3-1 민사 간병비 산식 행: 탐지 — 산식의 계산 결과가 기재 금액과 다르다 (차이 100,000원)
- **J4** J4-1 투명 글자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 투명 글자(채움 투명도 0); J4-2 이미지로 덮은 글자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 이미지로 덮은 글자; J4-3 저대비 글자: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 배경과 대비가 거의 없는 글자
- **J5** J5-1 오프라인 조회 실패 인용에 NOT_FOUND 판정 없음: 탐지
- **J6** J6-metadata scanned_layers에 metadata: 탐지; J6-outline scanned_layers에 outline: 탐지; J6-annotation scanned_layers에 annotation: 탐지; J6-form_field scanned_layers에 form_field: 탐지; J6-attachment scanned_layers에 attachment: 탐지; J6-image_ocr scanned_layers에 image_ocr: 탐지
- **R1** R1-1 서면 간 조항 대조 오판 없음: 탐지
- **R2** 2014다90011: 기대 인용문 있음 / 결과 ['있음', '없음'] → 성공; 2015다90022: 기대 인용문 있음 / 결과 ['있음', '없음'] → 성공; 2016다90033: 기대 인용문 없음 / 결과 ['없음'] → 성공; 2018구합51234: 기대 인용문 없음 / 결과 ['없음'] → 성공; 2018다90044: 기대 인용문 없음 / 결과 ['없음'] → 성공; 2013두90066: 기대 인용문 있음 / 결과 ['있음'] → 성공; 2019헌바90055: 기대 인용문 없음 / 결과 ['없음'] → 성공
- **R3** 실연동 테스트 1/1 통과 (커밋 b73504d·2026-09-25T01:29:47+00:00 통과; 최근 실행 075cf94은 대법원 판결 조회: 무응답 1건으로 판정 보류); 오프라인 합성 1/1; R3-1 민사: 줄바꿈으로 나뉜 '대법원 2016. 5. 12. / 선고 2015다90022': 탐지
- **R4** 실제 조회 3/3건, 다른 번호 기록 채택 0건 (커밋 b73504d·2026-09-25T01:29:47+00:00 통과; 최근 실행 075cf94은 헌재 결정 조회: 무응답 3건으로 판정 보류)
- **R5** R5-1 민사: 제10조 제2항 10년(원문 5년): 탐지 — 조문 본문과 수치가 다르다: 가상손해배상법 제10조 제2항('같은 조 제2항') (문서 10년 / 조문 5년)
- **R6** 실연동 테스트 1/1 통과 (커밋 b73504d·2026-09-25T01:29:47+00:00 통과; 최근 실행 075cf94은 대법원 판결 조회: 무응답 1건으로 판정 보류); 오프라인 합성 1/1; R6-1 민사: 머리글의 '대법원 2014다90011 판결'을 인용으로 세지 않음(본문 2회): 탐지
- **R7** R7-가상손해배상법 법령명 '가상손해배상법' 추출: 탐지; R7-민법 법령명 '민법' 추출: 탐지; R7-가상형사법 법령명 '가상형사법' 추출: 탐지; R7-가상행정절차법 법령명 '가상행정절차법' 추출: 탐지
- **R8** R8-1 렌더모드 3: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 보이지 않는 렌더모드(Tr 3); R8-2 이미지로 덮은 글자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 이미지로 덮은 글자
- **R9** R9-1 달력에 없는 작성일: 탐지 — 증거 작성일이 달력에 없는 날짜다: 갑 제1호증 진단서 작성일 2023. 2. 30.; R9-2 가지번호 결번: 탐지 — 가지번호가 비어 있다: 갑 제2호증의 1 결번
- **R10** 문서 판정 UNCERTAIN / 축 판정 UNCERTAIN / 관여 TRACES_FOUND
- **R11** R11-1 중복 추출 0건: 탐지
- **P1** P1-1 민사 부위 좌우(준비서면↔진단서): 탐지 — 문서마다 슬관절의 좌·우가 다르다: 민사_준비서면.pdf 좌측, 민사_진단서.pdf 우측; P1-2 민사 부위 좌우(준비서면 본문↔첨부 진단서, 문서 안): 탐지 — 같은 문서 안에서 슬관절의 좌·우가 다르다: 민사_준비서면.pdf 좌측, 민사_준비서면.pdf 첨부 진단서(사본) 우측; P1-3 민사 사고일(준비서면↔진단서): 탐지 — 문서마다 사고일(사건일)이 다르다: 민사_준비서면.pdf 2023-03-15, 민사_진단서.pdf 2023-03-16; P1-4 가사 원고 성명 표기(박○○↔이○○, 문서 안): 탐지 — 같은 문서 안에서 원고 성명 표기가 다르다: 박○○ 2회, 이○○ 1회; P1-5 가사 청구금액 자릿수 뒤바뀜(소장 205,000,000↔답변서 250,000,000): 탐지 — 문서마다 청구금액이 다르다(자릿수 뒤바뀜 의심): 가사_소장.pdf 205,000,000원, 가사_답변서.pdf 250,000,000원
- **P3** P3-1 형사: 행위시 버전(5년)과 일치 — 확인, '현행과 다름' 안내: 탐지 — 법령 적용 시점 검토: 가상형사법 제5조 — 기준일 2021-06-01 시행 버전(2010-01-01~2021-12-31)과 일치 — 현행과 다름(현행 7년); P3-2 형사: 어느 버전과도 불일치(10년) — 두 버전 값 제시: 탐지 — 법령 적용 시점 검토: 가상형사법 제5조 — 어느 시행 버전과도 다르다(2010-01-01~2021-12-31: 5년; 2022-01-01~현행: 7년)
- **P4** P4-1 민사 한글 금액(칠백만원↔7,500,000원): 탐지 — 한글 금액과 숫자 금액이 다르다(AMOUNT_WORDS_MISMATCH): '칠백만'=7,000,000원 / 숫자 7,500,000원; P4-2 가사 한글 금액(이억오천만원↔205,000,000원): 탐지 — 한글 금액과 숫자 금액이 다르다(AMOUNT_WORDS_MISMATCH): '이억오천만'=250,000,000원 / 숫자 205,000,000원; P4-3 가사 증거목록 금액↔첨부 원문(12,000,000↔21,000,000): 탐지 — 증거목록 금액과 첨부 원문의 금액이 다르다: 갑 제2호증 입금확인서 — 목록 12,000,000원, 원문 금 21,000,000원 (자릿수 뒤바뀜 의심); P4-4 민사 호증 번호 중복(갑 제5호증): 탐지 — 같은 호증 번호가 두 번 쓰였다: 갑 제5호증 — 영수증, 급여명세서; P4-5 민사 서면 작성일 이후 작성 증거(사실확인서): 탐지 — 증거 작성일이 이 서면의 작성일보다 뒤다: 갑 제4호증 사실확인서 작성일 2024. 6. 1. (서면 작성일 2024. 5. 20.); P4-6 민사 사건일 전 작성 증거(사고경위서): 탐지 — 사건을 기록·증명하는 서증의 작성일이 그 사건보다 앞선다: 갑 제3호증 사고경위서 작성일 2023. 1. 10., 대상 2023. 3. 15.
- **P5** P5-1 행정: '할 수 있다' 조문을 의무로 주장: 탐지 — 조문은 재량('할 수 있다')인데 의무로 주장했다: 가상행정절차법 제21조 — 문서 의무('통지하여야') / 조문 재량('통지할 수 있다'); P5-2 민사: 판결 취지 방향 반대 요약(2014다90011): 탐지 — 판시사항과 결론 방향이 반대(판결: 긍정, 서면: 부정): 대법원 2015. 4. 9. 선고 2014다90011 판결; P5-3 형사: 불이익변경금지 적용 범위 오인: 탐지 — 법리 검토: 검사만 항소한 사건에 불이익변경금지를 적용 — '검사만 항소한 이 사건에서 항소심은 원심보다 무거운 형을 선고할 수 없다.'; P5-4 형사: 사후 변제를 범죄 불성립 사유로 주장: 탐지 — 법리 검토: 사후 피해 회복(변제)을 범죄 불성립 사유로 주장 — '피고인은 피해액을 전액 변제하였으므로 업무상횡령죄는 성립하지 않는다.' (사람 판단 필요)
- **P6** P6-1 민사(AI 잔재 문서)에 AI 관여 근거 제시: 탐지 — AI 응답 잔재(AI_RESPONSE_RESIDUE): 챗봇 맺음말 — '도움이 되셨길 바랍니다'
- **P7** P7-1 흰 글자: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION, OUTPUT_MANIPULATION — 경로: 흰 글자(배경과 같은 색); P7-2 투명 글자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 투명 글자(채움 투명도 0); P7-3 저대비: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 배경과 대비가 거의 없는 글자; P7-4 이미지로 덮은 글자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 이미지로 덮은 글자; P7-5 렌더모드 3: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 보이지 않는 렌더모드(Tr 3); P7-6 초소형 글자: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 아주 작은 글자; P7-7 페이지 밖: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 페이지 밖 좌표; P7-8 문서 속성: 탐지 — 문서 속성 'ReviewerNote'에 지시형 문자열이 있다 — 경로: 문서 속성(메타데이터); P7-9 주석: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 주석; P7-10 북마크: 탐지 — HIDDEN_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 북마크(개요); P7-11 양식 필드: 탐지 — HIDDEN_INSTRUCTION 후보: INSTRUCTION_OVERRIDE — 경로: 양식 필드 값; P7-12 첨부파일: 탐지 — 첨부파일 'memo.txt' 안에 지시형 문자열이 있다 — 경로: 첨부파일 내용; P7-13 Base64: 탐지 — BASE64 인코딩된 지시형 문자열 — 경로: 인코딩 문자열(BASE64); P7-14 전각: 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 전각·호환 문자(NFKC 정규화) · 화면 표시 글자; P7-15 폭 0 문자: 탐지 — HIDDEN_INSTRUCTION 후보: OUTPUT_MANIPULATION — 경로: 표시 대체 문자열(ActualText) · 폭 0 문자; P7-16 한글 자모 분리: 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 한글 자모 분리(재조합) · 화면 표시 글자; P7-17 민사: 보이는 본문 지시문: 탐지 — META_INSTRUCTION 후보: VERIFICATION_SUPPRESSION — 경로: 보이는 본문
- **P8** P8-1 손상 PDF 구조 손상 신호(MALFORMED_PDF): 탐지 — PDF 구조가 손상되어 복구 읽기로 처리했다(MALFORMED_PDF): 행정_손상문서.pdf; P8-2 손상 PDF 본문 추출(날짜 불가능 인용 판정): 탐지 — 날짜 불가능(INVALID_FORMAT): 대법원 2021. 4. 31. 선고 2020두12345 판결; P8-3 회전 스캔 쪽 방향 보정 후 판정(2016도54321): 탐지 — 날짜 불가능(INVALID_FORMAT): 대법원 2017. 11. 31. 선고 2016 도 54321 판결
- **P2** D2와 같은 결함 집합으로 판정; D2-1 민사: 대법원+1심 부호(2018구합51234): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2019. 3. 14. 선고 2018구합51234 판결; D2-2 민사: 헌재+법원 부호(2018다90044): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2019. 4. 11. 선고 2018다90044 결정; D2-3 행정: 대법원+헌재 부호(2019헌바90055): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 5. 28. 선고 2019헌바90055 판결; D2-4 형사: 헌재+형사 부호(2020도12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 헌법재판소 2021. 3. 25. 2020도12345 결정; D2-5 가사: 대법원+가사 1심 부호(2019드단12345): 탐지 — 법원–부호 불일치(COURT_CODE_MISMATCH): 대법원 2020. 9. 24. 선고 2019드단12345 판결

</details>

