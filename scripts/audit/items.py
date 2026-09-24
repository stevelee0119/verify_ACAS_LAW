"""구현 감사 항목(v2 R1~R11, v3 D1~D9·§3 1~6, 추가지시 G1~G6·J1~J6).

각 항목은 (구현 위치, 파이프라인 호출 확인용 기호, 단위 테스트, 합성 실행 판정 함수)를 가진다.
판정 함수는 합성 실행 결과에서 그 항목의 finding(또는 산출물)을 찾아
    (True|False, 대상 finding 목록, 설명)
을 돌려준다. 오프라인 합성 실행으로 확인할 수 없는 항목은 None을 돌려주고 사유를 적는다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

Check = Callable[[Dict[str, Any]], Tuple[Optional[bool], List[Any], str]]


def _findings(out):
    result = out["result"]
    return [f for d in result.documents for f in d.findings] + list(result.project_findings)


def _doc(out, name):
    return next(d for d in out["result"].documents if d.filename == name)


def _rule(f):
    cf = f.confidence_features or {}
    return str(cf.get("rule_id") or "")


def by(pred) -> Check:
    def check(out):
        hits = [f for f in _findings(out) if pred(f)]
        return bool(hits), hits, f"{len(hits)}건"
    return check


def all_of(*checks: Check) -> Check:
    def check(out):
        found, notes = [], []
        ok = True
        for c in checks:
            flag, hits, note = c(out)
            ok = ok and bool(flag)
            found += hits
            notes.append(note)
        return ok, found, " / ".join(notes)
    return check


def named(label: str, c: Check) -> Check:
    def check(out):
        flag, hits, note = c(out)
        return flag, hits, f"{label}: {'탐지' if flag else '미탐지'}({note})"
    return check


def offline(reason: str) -> Check:
    def check(out):
        return None, [], reason
    return check


def title_has(text):
    return lambda f: text in (f.title or "")


def rule_is(rule):
    return lambda f: _rule(f) == rule


def type_is(name):
    return lambda f: str(f.type) == name


def injection_path(label):
    """인젝션 finding의 경로 표기(제목의 '경로: …')에 label이 있는지."""
    return lambda f: str(f.type) in {"HIDDEN_INSTRUCTION", "META_INSTRUCTION", "PROMPT_INJECTION"} and label in (f.title or "")


# --- 특수 판정 ------------------------------------------------------------------------------
def verified_citation(out):
    doc = _doc(out, "준비서면_원고.txt")
    cites = {c["citation_id"]: c for c in doc.citations}
    hits = [v for v in doc.engine_data.get("legal_verdicts", [])
            if (cites.get(v.get("citation_id")) or {}).get("case_number") == "2014다90011"]
    ok = any(v.get("verification_label") == "VERIFIED_CITATION" for v in hits)
    verified = (out["result"].scores.get("axes", {}).get("legal_citation_accuracy") or {}).get("verified", 0)
    return ok, [], f"정확 인용 판정={[v.get('verification_label') for v in hits]}, 요약 verified={verified}"


def consistent_citations(out):
    bad = []
    for d in out["result"].documents:
        per: Dict[str, set] = {}
        for f in d.findings:
            for cid in (f.confidence_features or {}).get("citation_ids") or []:
                per.setdefault(cid, set()).add(str(f.status))
        bad += [cid for cid, statuses in per.items() if {"CONTRADICTED", "VERIFIED"} <= statuses]
    return not bad, [], f"모순 판정 인용 {len(bad)}건"


def academic_unverified(out):
    doc = _doc(out, "준비서면_원고.txt")
    academic = [c for c in doc.citations if c.get("type") == "ACADEMIC"]
    verdicts = [v for v in doc.engine_data.get("legal_verdicts", []) if v.get("citation_id") in {c["citation_id"] for c in academic}]
    statuses = [v.get("status") for v in verdicts]
    if not academic:
        return False, [], "학술 인용을 추출하지 못함"
    return all(s == "UNVERIFIED" for s in statuses), [], f"학술 인용 {len(academic)}건 판정={statuses}"


def docx_document_column(out):
    text = out["docx_text"]
    ok = "문서" in text and "준비서면_원고.txt" in text and "문서 간" in text
    return ok, [], "요약 표의 문서 열·문서 간 그룹 " + ("있음" if ok else "없음")


def scanned_page_checked(out):
    doc = _doc(out, "형사_스캔서면.pdf")
    coverage = doc.engine_data.get("page_coverage", [])
    ocr = [c for c in coverage if str(c.get("status", "")).startswith("OCR_")]
    hits = [f for f in doc.findings if _rule(f).startswith("FMT.")]
    return bool(ocr and hits), hits, f"OCR 쪽 {len(ocr)}, OCR 글자에서 형식 판정 {len(hits)}건"


def ocr_quality_recorded(out):
    doc = _doc(out, "형사_스캔서면.pdf")
    quality = [c.get("ocr_quality") for c in doc.engine_data.get("page_coverage", []) if c.get("ocr_quality")]
    return bool(quality), [], f"쪽별 OCR 품질 기록 {len(quality)}쪽"


def paragraph_binding(out):
    doc = _doc(out, "준비서면_원고.txt")
    bound = [c for c in doc.citations if (c.get("attributes") or {}).get("resolved_label") == "가상손해배상법 제10조 제2항"]
    return bool(bound), [], f"'같은 조 제2항' → {[(c.get('attributes') or {}).get('resolved_label') for c in bound]}"


def scanned_layers(out):
    doc = _doc(out, "행정_의견서.pdf")
    layers = set((doc.engine_data.get("adversarial") or {}).get("scanned_layers") or [])
    wanted = {"outline", "annotation", "image_ocr", "metadata"}
    return wanted <= layers, [], f"scanned_layers={sorted(layers)} (필수 {sorted(wanted)})"


def no_duplicate_citations(out):
    dup = 0
    for d in out["result"].documents:
        keys = [(c.get("type"), c.get("canonical_case_number") or c.get("case_number") or c.get("normalized_key"),
                 c.get("law_name"), c.get("article"), c.get("paragraph"), c.get("block_id")) for c in d.citations]
        dup += len(keys) - len(set(keys))
    return dup == 0, [], f"중복 추출 {dup}건"


def quote_bound_to_right_case(out):
    doc = _doc(out, "준비서면_원고.txt")
    quoted = {c.get("case_number"): bool(c.get("quoted_text")) for c in doc.citations if c.get("case_number")}
    ok = quoted.get("2014다90011") and quoted.get("2015다90022") and not quoted.get("2016다90033")
    return bool(ok), [], f"인용문 결합={quoted}"


# --- 항목 표 --------------------------------------------------------------------------------
ITEMS: List[Dict[str, Any]] = [
    # v3 D1~D9
    {"id": "D1", "title": "변형 인용문 어절 diff(MODIFIED_QUOTE)", "code": "legal_engine/quote_diff.py, verifier._modified_quote_finding",
     "call": ("legal_engine/verifier.py", "quote_changes"), "tests": "test_v3_d1_quote_diff.py",
     "check": by(rule_is("QUOTE.MEANINGFUL_CHANGE"))},
    {"id": "D2", "title": "법원–사건부호 호환(대법원+1심, 대법원+헌재부호, 헌재+법원부호)",
     "code": "legal_engine/citation_format.py(format_violations), config/legal_rules/case_codes.yaml",
     "call": ("legal_engine/verifier.py", "format_violations"), "tests": "test_v3_d2_case_codes.py",
     "check": all_of(named("대법원+구합", by(lambda f: _rule(f) == "FMT.COURT_CODE_MISMATCH" and "2018구합51234" in f.title)),
                     named("대법원+헌바", by(lambda f: _rule(f) == "FMT.COURT_CODE_MISMATCH" and "2019헌바90055" in f.title)),
                     named("헌재+다", by(lambda f: "2018다90044" in f.title and str(f.status) == "CONTRADICTED")))},
    {"id": "D3", "title": "다수·반대의견 귀속(MISATTRIBUTED_OPINION)", "code": "legal_engine/opinion_attribution.py",
     "call": ("legal_engine/verifier.py", "attribute_claim"), "tests": "test_v3_d3_opinion.py",
     "check": by(rule_is("OPINION.MISATTRIBUTED_OPINION"))},
    {"id": "D4", "title": "정확한 인용 VERIFIED_CITATION·요약 verified 반영", "code": "legal_engine/verification_labels.py",
     "call": ("legal_engine/verifier.py", "citation_label"), "tests": "test_v3_d4_verified.py", "check": verified_citation,
     "axes_from_check": True, "report_na": True},
    {"id": "D5", "title": "같은 인용의 모순 판정 방지(일관성 검사)", "code": "verification_engine/finalize.py(enforce_consistency)",
     "call": ("verification_engine/finalize.py", "enforce_consistency"), "tests": "test_v3_d5_consistency.py",
     "check": consistent_citations, "report_na": True},
    {"id": "D6", "title": "증거 표 셀 파싱·호증 파서·누락 알림 묶음", "code": "claim_engine/exhibits.py, attachments._missing_notice",
     "call": ("claim_engine/attachments.py", "parse_exhibit_label"), "tests": "test_v3_d6_evidence.py",
     "check": by(lambda f: str(f.type) == "EVIDENCE_DATE_INVALID" and "진단서" in f.title)},
    {"id": "D7", "title": "출처 조회 실패는 UNVERIFIED(학술)", "code": "legal_engine/verifier.verify_academic",
     "call": ("legal_engine/verifier.py", "verify_academic"), "tests": "test_v3_d7_sources.py",
     "check": academic_unverified, "report_na": True},
    {"id": "D8", "title": "요약 표 문서 열·문서 간 그룹", "code": "report_engine/docx_report.py",
     "call": ("apps/api/routers/reports.py", "build_report_docx"), "tests": "test_report_completion.py",
     "check": docx_document_column, "report_na": True},
    {"id": "D9", "title": "보이는 AI 대상 억제 지시문 B등급", "code": "adversarial_engine/scanner.py, patterns.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v3_d9_visible_instruction.py",
     "check": by(lambda f: str(f.type) == "META_INSTRUCTION" and str(f.evidence_grade) in {"A", "B"} and "보이는 본문" in f.title)},
    # v3 §3
    {"id": "§3-1", "title": "쪽별 텍스트 레이어 판정·OCR 텍스트 전 검사·OCR 실패 '분석 불가'",
     "code": "document_engine/pdf_parser.py(_apply_ocr), pipeline(OCR_LOW_QUALITY·PARSE_ERROR)",
     "call": ("verification_engine/pipeline.py", "page_coverage"), "tests": "test_ocr.py, test_v3_g2_ocr_quality.py",
     "check": scanned_page_checked},
    {"id": "§3-2", "title": "숨김 텍스트 일반화(대비비·투명도·렌더모드)", "code": "document_engine/pdf_parser.py(_render_facts, _apply_contrast)",
     "call": ("document_engine/pdf_parser.py", "_apply_contrast"), "tests": "test_v3_j4_visibility.py",
     "check": all_of(named("흰 글자", by(injection_path("흰 글자"))), named("저대비", by(injection_path("대비가 거의 없는"))),
                     named("투명", by(injection_path("투명 글자"))), named("Tr 3", by(injection_path("렌더모드"))))},
    {"id": "§3-3", "title": "구조 경로(Info·XMP 전체 키, Outline, 주석, 양식, 첨부, 이미지 OCR) 분류기 투입",
     "code": "adversarial_engine/scanner.py, document_engine/pdf_parser.py(raw_layers)",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_adversarial*.py",
     "check": all_of(named("메타데이터 사용자 키", by(injection_path("메타데이터"))), named("주석", by(injection_path("주석"))),
                     named("북마크", by(injection_path("북마크"))), named("양식", by(injection_path("양식"))),
                     named("첨부", by(injection_path("첨부"))))},
    {"id": "§3-4", "title": "NFKC·폭 0 문자 제거·Base64/hex 디코딩 후 분류", "code": "adversarial_engine/unicode_scan.py, encoding_scan.py",
     "call": ("adversarial_engine/scanner.py", "decode_candidates"), "tests": "test_adversarial*.py",
     "check": all_of(named("Base64", by(injection_path("인코딩"))), named("전각", by(lambda f: "ＡＩ" in str((f.confidence_features or {}).get("observed_text") or "") or "전각" in f.title)),
                     named("폭 0", by(lambda f: "폭 0" in f.title or str(f.type) == "ZERO_WIDTH_TEXT")))},
    {"id": "§3-5", "title": "산술·날짜 재계산, 문서 간 금액·부위·기관·인적사항 교차검증", "code": "claim_engine/calculation.py, fact_checks.py, fact_store.py",
     "call": ("verification_engine/pipeline.py", "check_periods"), "tests": "test_v3_j3_arithmetic.py, test_v3_g5_facts.py",
     "check": all_of(named("합계", by(lambda f: str(f.type) == "ARITHMETIC_MISMATCH" and "합계" in f.title)),
                     named("기간 만료일", by(lambda f: _rule(f).startswith("FACT.PERIOD") or "만료" in f.title)),
                     named("문서 간", by(lambda f: _rule(f).startswith("FACT."))))},
    {"id": "§3-6", "title": "AI 잔재 패턴 사전 분리·탐지", "code": "verification_engine/ai_residue.py",
     "call": ("verification_engine/ai_document_detector.py", "scan_residue"), "tests": "test_ai_residue*.py",
     "check": by(lambda f: str(f.type) in {"AI_RESPONSE_RESIDUE", "DRAFT_ARTIFACT"} or "잔재" in f.title)},
    # 추가지시 G
    {"id": "G1", "title": "헌재 결정 조회(detc) 정확 일치", "code": "source_adapters/law_go_kr.py(search_case)",
     "call": ("legal_engine/verifier.py", "search_case"), "tests": "test_v3_g1_detc.py",
     "check": offline("공식 DB(국가법령정보) 조회가 필요해 오프라인 합성 실행으로는 확인 불가 — 단위 테스트와 CI 실연동 평가로 확인")},
    {"id": "G2", "title": "한국어 OCR 품질(쪽별 신뢰도·한글 비율)", "code": "document_engine/ocr.py(page_quality)",
     "call": ("document_engine/pdf_parser.py", "page_quality"), "tests": "test_v3_g2_ocr_quality.py", "check": ocr_quality_recorded,
     "report_na": True},
    {"id": "G3", "title": "항·호 단위 결합('같은 조 제N항')", "code": "legal_engine/citation_extractor.py(_resolve_article_references)",
     "call": ("legal_engine/citation_extractor.py", "_resolve_article_references"), "tests": "test_v3_g3_paragraph_binding.py",
     "check": paragraph_binding, "report_na": True},
    {"id": "G4", "title": "법리 주장 유형 분류→근거 조회→판단", "code": "legal_engine/claim_review.py",
     "call": ("verification_engine/pipeline.py", "review_claims"), "tests": "test_v3_g4_claims.py",
     "check": all_of(named("전칭", by(rule_is("CLAIM.UNSUPPORTED_GENERALIZATION"))), named("근거 없는 청구", by(rule_is("CLAIM.NO_BASIS_REMEDY"))))},
    {"id": "G5", "title": "사실 저장소·기간 재계산·증거 선후", "code": "claim_engine/fact_store.py, fact_checks.py, evidence_consistency.py",
     "call": ("verification_engine/pipeline.py", "cross_document_facts"), "tests": "test_v3_g5_facts.py",
     "check": all_of(named("부위 좌우", by(rule_is("FACT.INJURY_SIDE"))), named("사고일", by(rule_is("FACT.INCIDENT_DATE"))),
                     named("청구금액", by(rule_is("FACT.CLAIM_AMOUNT"))),
                     named("증거 작성일<사건일", by(lambda f: str(f.type) == "EVIDENCE_TIMELINE_INVERSION" and "사고경위서" in f.title)))},
    {"id": "G6", "title": "오탐 제거(파일명 표지 등)", "code": "forensic_engine/covert.py",
     "call": ("verification_engine/pipeline.py", "self.forensic.scan"), "tests": "test_v3_g6_filename.py",
     "check": lambda out: (not [f for f in _findings(out) if "파일명" in (f.title or "")], [], "파일명 표지 오탐 없음"), "report_na": True},
    # 추가지시 J
    {"id": "J1", "title": "헌재 조회 재조회·정확 일치", "code": "source_adapters/law_go_kr.py", "call": ("legal_engine/verifier.py", "search_case"),
     "tests": "test_v3_g1_detc.py", "check": offline("공식 DB 조회 필요 — 단위 테스트·CI 실연동으로 확인")},
    {"id": "J2", "title": "AI 모델 사실 모순 지적 결정론 재검증(MODEL_FACT_REMARK)", "code": "verification_engine/ai_document_detector.py",
     "call": ("verification_engine/pipeline.py", "reconcile_model_fact_remarks"), "tests": "test_v3_j2_model_remarks.py",
     "check": offline("AI 모델 호출이 필요 — 오프라인 합성 실행으로는 확인 불가(v4 P6: '정확히 기재' 칭찬을 모순으로 분류한 결함 보고)")},
    {"id": "J3", "title": "산식 행('a × b = c') 검산", "code": "claim_engine/calculation.py(evaluate_expression)",
     "call": ("verification_engine/pipeline.py", "self.calculation.verify_document"), "tests": "test_v3_j3_arithmetic.py",
     "check": by(lambda f: str(f.type) == "ARITHMETIC_MISMATCH" and ("산식" in f.title or "2,500,000" in f.title))},
    {"id": "J4", "title": "글자별 가시성(투명도·대비·가림)", "code": "document_engine/pdf_parser.py", "call": ("document_engine/pdf_parser.py", "_render_facts"),
     "tests": "test_v3_j4_visibility.py",
     "check": all_of(named("투명", by(injection_path("투명 글자"))), named("이미지 가림", by(injection_path("이미지로 덮은"))),
                     named("저대비", by(injection_path("대비가 거의 없는"))))},
    {"id": "J5", "title": "조회 실패는 NOT_FOUND가 아닌 UNVERIFIED", "code": "legal_engine/verifier.py",
     "call": ("legal_engine/verifier.py", "verify_case"), "tests": "test_v3_g1_detc.py",
     "check": by(lambda f: "2018다90044" in f.title and str(f.status) in {"UNVERIFIED", "CONTRADICTED"}), "report_na": True},
    {"id": "J6", "title": "scanned_layers에 outline·annotation·image_ocr·metadata 기록", "code": "adversarial_engine/scanner.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "—", "check": scanned_layers, "report_na": True},
    # v2 R1~R11
    {"id": "R1", "title": "다른 서면을 조항 원문으로 쓰지 않음", "code": "legal_engine/internal_citation.py", "call": ("verification_engine/pipeline.py", "_internal_citation_check"),
     "tests": "test_v2_root_causes.py", "check": lambda out: (not [f for f in _findings(out) if str(f.type) == "INTERNAL_CITATION_ERROR"], [], "서면 간 조항 대조 오판 없음"),
     "report_na": True},
    {"id": "R2", "title": "인용문을 올바른 인용에 결합", "code": "legal_engine/citation_extractor.py(bind_quotes)", "call": ("legal_engine/citation_extractor.py", "bind_quotes"),
     "tests": "test_v2_root_causes.py", "check": quote_bound_to_right_case, "report_na": True},
    {"id": "R3", "title": "줄바꿈으로 법원·선고일 유실 방지(읽기 본문)", "code": "document_engine/reading_text.py", "call": ("legal_engine/citation_extractor.py", "build_reading_text"),
     "tests": "test_v2_root_causes.py", "check": offline("PDF 줄바꿈 배치가 필요 — 단위 테스트로 확인")},
    {"id": "R4", "title": "사건번호 정확 일치 기록만 채택", "code": "source_adapters/law_go_kr.py", "call": ("legal_engine/verifier.py", "search_case"),
     "tests": "test_v2_root_causes.py, test_source_adapters.py", "check": offline("공식 DB 응답 필요 — 단위 테스트로 확인")},
    {"id": "R5", "title": "조문 본문 대조(claim_text)", "code": "legal_engine/provision_content.py", "call": ("legal_engine/source_review.py", "compare_claim_to_provision"),
     "tests": "test_v2_root_causes.py, test_v3_g3_paragraph_binding.py",
     "check": by(lambda f: "가상손해배상법" in f.title and str(f.status) == "CONTRADICTED")},
    {"id": "R6", "title": "머리글·바닥글 반복 줄 제외", "code": "document_engine(running_head)", "call": ("adversarial_engine/scanner.py", "running_head"),
     "tests": "test_v2_root_causes.py", "check": offline("여러 쪽 PDF 필요 — 단위 테스트로 확인")},
    {"id": "R7", "title": "법령명 추출(앞 문장 혼입 방지·긴 법령명)", "code": "legal_engine/normalize.py(law_name_suffix)", "call": ("legal_engine/citation_extractor.py", "law_name_suffix"),
     "tests": "test_v2_root_causes.py",
     "check": lambda out: (any(c.get("law_name") == "가상손해배상법" for c in _doc(out, "준비서면_원고.txt").citations), [], "법령명 '가상손해배상법' 추출"),
     "report_na": True},
    {"id": "R8", "title": "숨김 경로별 탐지(Tr 3·도형 가림)", "code": "document_engine/pdf_parser.py, adversarial_engine/scanner.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v2_root_causes.py",
     "check": by(injection_path("렌더모드"))},
    {"id": "R9", "title": "증거 정합성(달력·결번·선후)", "code": "claim_engine/evidence_consistency.py", "call": ("verification_engine/pipeline.py", "check_evidence_consistency"),
     "tests": "test_v2_root_causes.py", "check": all_of(named("달력", by(type_is("EVIDENCE_DATE_INVALID"))), named("결번", by(type_is("EVIDENCE_NUMBERING_GAP"))))},
    {"id": "R10", "title": "AI 판정 축과 문서 결과 일치", "code": "verification_engine/ai_document_detector.py, scoring.py", "call": ("verification_engine/pipeline.py", "create_ai_detector_findings"),
     "tests": "test_v2_root_causes.py", "check": offline("AI 모델 교차판정 필요 — 단위 테스트로 확인")},
    {"id": "R11", "title": "같은 조문 중복 추출 방지", "code": "legal_engine/citation_extractor.py", "call": ("verification_engine/pipeline.py", "extract_citations"),
     "tests": "test_v2_root_causes.py", "check": no_duplicate_citations, "report_na": True},
]
