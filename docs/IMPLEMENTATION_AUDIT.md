# 구현 여부 감사표 (v4 P0)

지시서 항목이 '함수가 있다'가 아니라 **실제 파이프라인에서 호출되고, finding을 만들고, 보고서에 표시되고, 요약 점수에 반영되는지**를 합성 문서 실행으로 확인한 표다. `python scripts/implementation_audit.py --label …`로 다시 만든다.

- 상태: 완료 / 부분 / 부분(탐지 실패) / 미구현 / 연결 안 됨 / 완료(단위 테스트: 오프라인 합성 실행으로 확인할 수 없어 단위 테스트·CI 실연동으로 확인)
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

