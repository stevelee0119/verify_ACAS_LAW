"""구현 감사 항목과 심어 둔 결함(v4 P0, 합성 PDF 사건 묶음 scripts/audit/corpus.py 기준).

항목마다
- defects: 심어 둔 결함. 각 결함은 탐지 판정 함수(match: finding → bool 또는 check: 실행 결과 → bool)를 가진다.
- family: 그 항목이 만드는 finding의 범위. 어느 결함에도 대응하지 않는 family finding은 오탐으로 센다.
- fp_check: family로 셀 수 없는 오탐(예: 표 칸 이어 붙이기, 사건이 다른 문서끼리의 대조)을 세는 함수.
- live: 실제 국가법령정보·AI 모델 호출로만 확인할 수 있는 항목. 실연동 통합 테스트 결과가 없으면 '미확인'.
완료 기준: 탐지율 90% 이상, 오탐 0건, 파이프라인 호출, 보고서·요약 점수 반영.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

Pred = Callable[[Any], bool]


# --- 공용 도우미 ---------------------------------------------------------------------------
def features(f) -> Dict[str, Any]:
    return f.confidence_features or {}


def rule(f) -> str:
    return str(features(f).get("rule_id") or "")


def code(f) -> str:
    return str(features(f).get("defect_code") or "")


def title(f) -> str:
    return f.title or ""


def doc_of(out, f) -> str:
    return out["names"].get(f.document_id or "", "")


def all_findings(out) -> List[Any]:
    result = out["result"]
    return [f for d in result.documents for f in d.findings] + list(result.project_findings)


def document(out, name):
    return next(d for d in out["result"].documents if d.filename == name)


def D(defect_id: str, desc: str, match: Optional[Pred] = None, check=None, doc: Optional[str] = None) -> Dict[str, Any]:
    """결함 하나. doc를 주면 그 문서의 finding만 탐지로 센다."""
    return {"id": defect_id, "desc": desc, "match": match, "check": check, "doc": doc}


# 문서 속 지시문을 보고하는 finding 유형(경로별로 다르게 붙는다)
INJECTION_TYPES = {"HIDDEN_INSTRUCTION", "META_INSTRUCTION", "PROMPT_INJECTION_SUSPECTED", "METADATA_INJECTION",
                   "ENCODED_INSTRUCTION", "OBFUSCATED_INSTRUCTION", "UNICODE_SMUGGLING", "OCR_LAYER_INJECTION",
                   "MULTIMODAL_INJECTION", "SYSTEM_OVERRIDE_ATTEMPT", "ROLE_OVERRIDE_ATTEMPT", "VERIFICATION_SUPPRESSION",
                   "OUTPUT_MANIPULATION_ATTEMPT", "TOOL_MANIPULATION_ATTEMPT", "DATA_EXFILTRATION_INSTRUCTION"}


def injection(label: str):
    """인젝션 finding 중 경로 표기에 label이 들어 있는 것."""
    return lambda f: str(f.type) in INJECTION_TYPES and label in title(f)


def cited(number: str) -> Pred:
    return lambda f: number in title(f) or number in str(features(f).get("case_number") or "")


# --- 특수 판정 ------------------------------------------------------------------------------
def verdict_label(out, doc_name: str, number: str) -> List[str]:
    doc = document(out, doc_name)
    cites = {c["citation_id"]: c for c in doc.citations}
    labels = []
    for v in doc.engine_data.get("legal_verdicts", []):
        c = cites.get(v.get("citation_id")) or {}
        if c.get("case_number") == number:
            labels.append(v.get("verification_label") or (v.get("review") or {}).get("verification_label"))
    return labels


def quoted_verified(out, doc_name: str, number: str) -> int:
    doc = document(out, doc_name)
    ids = {c["citation_id"] for c in doc.citations if c.get("case_number") == number and c.get("quoted_text")}
    return sum(1 for v in doc.engine_data.get("legal_verdicts", [])
               if v.get("citation_id") in ids and (v.get("verification_label") or (v.get("review") or {}).get("verification_label")) == "VERIFIED_CITATION")


def no_conflicts(out) -> bool:
    for d in out["result"].documents:
        per: Dict[str, set] = {}
        for f in d.findings:
            for cid in features(f).get("citation_ids") or []:
                per.setdefault(cid, set()).add(str(f.status))
        if any({"CONTRADICTED", "VERIFIED"} <= s for s in per.values()):
            return False
    return True


def academic_unverified(out) -> bool:
    doc = document(out, "민사_준비서면.pdf")
    academic = [c for c in doc.citations if c.get("type") == "ACADEMIC"]
    ids = {c["citation_id"] for c in academic}
    statuses = [v.get("status") for v in doc.engine_data.get("legal_verdicts", []) if v.get("citation_id") in ids]
    return bool(academic) and bool(statuses) and all(s == "UNVERIFIED" for s in statuses)


def docx_has_document_groups(out) -> bool:
    text = out["docx_text"]
    return "민사_준비서면.pdf" in text and "문서 간" in text


def page_status(out, name, page) -> str:
    doc = document(out, name)
    return next((c["status"] for c in doc.engine_data.get("page_coverage", []) if c["page"] == page), "")


def ocr_quality_on(out, name, page) -> bool:
    doc = document(out, name)
    return any(c["page"] == page and c.get("ocr_quality") for c in doc.engine_data.get("page_coverage", []))


def resolved_label(out, name, label) -> bool:
    doc = document(out, name)
    return any((c.get("attributes") or {}).get("resolved_label") == label for c in doc.citations)


def layers(out) -> set:
    doc = document(out, "행정_의견서.pdf")
    return set((doc.engine_data.get("adversarial") or {}).get("scanned_layers") or [])


# R2: 인용문 결합의 기대값(사건번호 → 인용문을 가져야 하는지)
R2_EXPECTED = {"민사_준비서면.pdf": {"2014다90011": True, "2015다90022": True, "2016다90033": False,
                                     "2018구합51234": False, "2018다90044": False},
               "행정_의견서.pdf": {"2013두90066": True, "2019헌바90055": False}}


def r2_binding(out) -> Dict[str, Any]:
    rows = []
    for name, expected in R2_EXPECTED.items():
        doc = document(out, name)
        # 같은 사건번호가 여러 번 인용되면 하나라도 기대와 같으면 성공(인용문이 있는 인용·없는 인용이 섞일 수 있음)
        seen: Dict[str, List[bool]] = {}
        for c in doc.citations:
            if c.get("case_number") in expected:
                seen.setdefault(c["case_number"], []).append(bool(c.get("quoted_text")))
        for number, want in expected.items():
            got = seen.get(number, [])
            ok = want in got if got else False
            rows.append({"case": number, "expected": want, "actual": got, "ok": ok})
    return {"rows": rows, "ok": sum(r["ok"] for r in rows), "total": len(rows)}


def citation_count(out, name, number) -> int:
    return sum(1 for c in document(out, name).citations if c.get("case_number") == number)


def duplicate_citations(out) -> int:
    dup = 0
    for d in out["result"].documents:
        keys = [(c.get("type"), c.get("case_number"), c.get("law_name"), c.get("article"), c.get("paragraph"),
                 c.get("block_id"), tuple(c.get("span") or ())) for c in d.citations]
        dup += len(keys) - len(set(keys))
    return dup


FIELDS = {"민사_준비서면.pdf": "민사", "민사_진단서.pdf": "민사", "행정_의견서.pdf": "행정", "행정_손상문서.pdf": "행정",
          "형사_변론요지서.pdf": "형사", "가사_소장.pdf": "가사", "가사_답변서.pdf": "가사"}


def cross_case_comparisons(out) -> int:
    """사건이 다른 문서(분야가 다른 문서)끼리 사실을 대조한 finding 수(오탐)."""
    bad = 0
    for f in out["result"].project_findings:
        docs = features(f).get("documents") or []
        names = {out["names"].get(d, d) for d in docs}
        if len({FIELDS.get(n, n) for n in names}) > 1:
            bad += 1
    return bad


def concatenated_cells(out) -> int:
    pattern = re.compile(r"[가-힣](?:19|20)\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.[가-힣]")
    return sum(1 for f in all_findings(out) if pattern.search(title(f)))


# --- 항목 표 --------------------------------------------------------------------------------
LEGAL_RULE_FAMILY = lambda f: rule(f).startswith("CLAIM.") or rule(f).startswith("RULE.")

ITEMS: List[Dict[str, Any]] = [
    {"id": "D1", "title": "변형 인용문 어절 diff(MODIFIED_QUOTE)", "code": "legal_engine/quote_diff.py",
     "call": ("legal_engine/verifier.py", "quote_changes"), "tests": "test_v3_d1_quote_diff.py",
     "family": lambda f: rule(f).startswith("QUOTE."),
     "defects": [D("D1-1", "민사: 정도 부사 '현저히' 삭제(2015다90022)", lambda f: rule(f) == "QUOTE.MEANINGFUL_CHANGE" and "2015다90022" in title(f)),
                 D("D1-2", "행정: 부정 치환(2013두90066)", lambda f: rule(f) == "QUOTE.MEANINGFUL_CHANGE" and "2013두90066" in title(f))]},
    {"id": "D2", "title": "법원–사건부호 호환(COURT_CODE_MISMATCH)", "code": "legal_engine/citation_format.py, config/legal_rules/case_codes.yaml",
     "call": ("legal_engine/verifier.py", "format_violations"), "tests": "test_v3_d2_case_codes.py",
     "family": lambda f: code(f) == "COURT_CODE_MISMATCH",
     "defects": [D("D2-1", "민사: 대법원+1심 부호(2018구합51234)", lambda f: code(f) == "COURT_CODE_MISMATCH" and "2018구합51234" in title(f)),
                 D("D2-2", "민사: 헌재+법원 부호(2018다90044)", lambda f: code(f) == "COURT_CODE_MISMATCH" and "2018다90044" in title(f)),
                 D("D2-3", "행정: 대법원+헌재 부호(2019헌바90055)", lambda f: code(f) == "COURT_CODE_MISMATCH" and "2019헌바90055" in title(f)),
                 D("D2-4", "형사: 헌재+형사 부호(2020도12345)", lambda f: code(f) == "COURT_CODE_MISMATCH" and "2020도12345" in title(f)),
                 D("D2-5", "가사: 대법원+가사 1심 부호(2019드단12345)", lambda f: code(f) == "COURT_CODE_MISMATCH" and "2019드단12345" in title(f))]},
    {"id": "D3", "title": "다수·반대의견 귀속(MISATTRIBUTED_OPINION)", "code": "legal_engine/opinion_attribution.py",
     "call": ("legal_engine/verifier.py", "attribute_claim"), "tests": "test_v3_d3_opinion.py",
     "family": lambda f: rule(f) == "OPINION.MISATTRIBUTED_OPINION",
     "defects": [D("D3-1", "민사: 반대의견을 판시처럼 요약(2016다90033)", lambda f: rule(f) == "OPINION.MISATTRIBUTED_OPINION" and "2016다90033" in title(f))]},
    {"id": "D4", "title": "정확한 인용 VERIFIED_CITATION·요약 verified 반영", "code": "legal_engine/verification_labels.py",
     "call": ("legal_engine/verifier.py", "citation_label"), "tests": "test_v3_d4_verified.py", "report_na": True,
     "defects": [D("D4-1", "민사: 정확한 직접 인용(2014다90011)", check=lambda out: "VERIFIED_CITATION" in verdict_label(out, "민사_준비서면.pdf", "2014다90011")),
                 D("D4-2", "가사: 판결 취지의 정확한 요약(2018므90088)", check=lambda out: "VERIFIED_CITATION" in verdict_label(out, "가사_소장.pdf", "2018므90088")),
                 D("D4-3", "요약 점수 verified 반영", check=lambda out: ((out["result"].scores.get("axes", {}).get("legal_citation_accuracy") or {}).get("verified") or 0) >= 2)],
     # 인용문을 바꿔 쓴 인용(2015다90022의 인용문 있는 인용)을 '확인 완료'로 표시하면 오탐
     "fp_check": lambda out: quoted_verified(out, "민사_준비서면.pdf", "2015다90022")},
    {"id": "D5", "title": "같은 인용의 모순 판정 방지(일관성 검사)", "code": "verification_engine/finalize.py(enforce_consistency)",
     "call": ("verification_engine/finalize.py", "enforce_consistency"), "tests": "test_v3_d5_consistency.py", "report_na": True,
     "defects": [D("D5-1", "모든 인용에 CONTRADICTED와 VERIFIED가 함께 붙지 않음", check=no_conflicts)]},
    {"id": "D6", "title": "증거 표 셀 파싱·호증 파서", "code": "claim_engine/exhibits.py, attachments.py, document_engine 표 칸 추출",
     "call": ("claim_engine/attachments.py", "parse_exhibit_label"), "tests": "test_v3_d6_evidence.py",
     "defects": [D("D6-1", "민사 증거표 칸 단위 파싱(갑 제1호증 진단서 작성일)", lambda f: str(f.type) == "EVIDENCE_DATE_INVALID" and "진단서" in title(f))],
     "fp_check": concatenated_cells},
    {"id": "D7", "title": "출처 조회 실패는 UNVERIFIED(학술 인용)", "code": "legal_engine/verifier.verify_academic",
     "call": ("legal_engine/verifier.py", "verify_academic"), "tests": "test_v3_d7_sources.py", "report_na": True,
     "defects": [D("D7-1", "민사: 학술 인용을 추출하고 UNVERIFIED로 둠", check=academic_unverified)]},
    {"id": "D8", "title": "요약 표 문서 열·문서 간 그룹", "code": "report_engine/docx_report.py",
     "call": ("apps/api/routers/reports.py", "build_report_docx"), "tests": "test_report_completion.py", "report_na": True,
     "defects": [D("D8-1", "docx 요약 표에 문서명·문서 간 그룹", check=docx_has_document_groups)]},
    {"id": "D9", "title": "보이는 AI 대상 억제 지시문 B등급", "code": "adversarial_engine/scanner.py, patterns.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v3_d9_visible_instruction.py",
     "family": lambda f: str(f.type) in INJECTION_TYPES and "보이는 본문" in title(f),
     "defects": [D("D9-1", "민사: 보이는 본문의 검증 억제 지시(B 이상)",
                   lambda f: str(f.type) in INJECTION_TYPES and "보이는 본문" in title(f) and str(f.evidence_grade) in {"A", "B"})],
     "doc_scope": "민사_준비서면.pdf"},
    {"id": "§3-1", "title": "쪽별 텍스트 레이어 판정·OCR 쪽 전 검사·분석 불가 명시", "code": "document_engine/pdf_parser.py(_apply_ocr)",
     "call": ("verification_engine/pipeline.py", "page_coverage"), "tests": "test_ocr.py, test_v3_g2_ocr_quality.py",
     "defects": [D("§3-1a", "형사: 1·2쪽 텍스트, 3쪽 OCR", check=lambda out: page_status(out, "형사_변론요지서.pdf", 1) == "EXTRACTED"
                   and page_status(out, "형사_변론요지서.pdf", 3).startswith("OCR_")),
                 D("§3-1b", "형사 3쪽(OCR 글자)의 달력에 없는 날짜", lambda f: rule(f) == "FMT.DATE_NOT_ON_CALENDAR" and "12345" in title(f) and "2018" in title(f) and "도" in title(f))]},
    {"id": "§3-2", "title": "숨김 텍스트 일반화(대비비·투명도·렌더모드)", "code": "document_engine/pdf_parser.py(_render_facts, _apply_contrast)",
     "call": ("document_engine/pdf_parser.py", "_apply_contrast"), "tests": "test_v3_j4_visibility.py",
     "defects": [D("§3-2a", "흰 글자", injection("흰 글자")), D("§3-2b", "투명 글자", injection("투명 글자")),
                 D("§3-2c", "저대비", injection("대비")), D("§3-2d", "렌더모드 3", injection("렌더모드"))]},
    {"id": "§3-3", "title": "구조 경로(문서 속성 전체 키·주석·북마크·양식·첨부) 분류기 투입", "code": "adversarial_engine/scanner.py, structure_layers",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v4_p7_injection_paths.py",
     "defects": [D("§3-3a", "문서 속성 사용자 키", injection("문서 속성")), D("§3-3b", "주석", injection("주석")),
                 D("§3-3c", "북마크", injection("북마크")), D("§3-3d", "양식 필드", injection("양식")), D("§3-3e", "첨부파일", injection("첨부파일"))]},
    {"id": "§3-4", "title": "NFKC·폭 0·Base64 디코딩·자모 재조합 후 분류", "code": "adversarial_engine/unicode_scan.py, encoding_scan.py",
     "call": ("adversarial_engine/scanner.py", "decode_candidates"), "tests": "test_v4_p7_injection_paths.py",
     "defects": [D("§3-4a", "Base64", injection("인코딩")), D("§3-4b", "전각", injection("전각")),
                 D("§3-4c", "폭 0 문자", injection("폭 0")), D("§3-4d", "한글 자모 분리", injection("자모"))]},
    {"id": "§3-5", "title": "산술·기간 재계산", "code": "claim_engine/calculation.py, fact_checks.py",
     "call": ("verification_engine/pipeline.py", "check_periods"), "tests": "test_v3_j3_arithmetic.py, test_v4_s35_periods_subtotals.py",
     "family": lambda f: str(f.type) == "ARITHMETIC_MISMATCH",
     "defects": [D("§3-5a", "민사 손해액 표 합계(차이 600,000원)", lambda f: str(f.type) == "ARITHMETIC_MISMATCH" and "600,000" in title(f)),
                 D("§3-5b", "민사 산식 행(80,000원 × 30일)", lambda f: rule(f) == "CALC.FORMULA"),
                 D("§3-5c", "민사 시효 만료일(2026. 9. 15.)", lambda f: str(f.type) == "ARITHMETIC_MISMATCH" and "2026" in title(f) and "만료" in title(f))]},
    {"id": "§3-6", "title": "AI 잔재 패턴(사전 분리)", "code": "verification_engine/ai_residue.py, config/ai_residue_patterns.yaml",
     "call": ("verification_engine/pipeline.py", "residue_findings"), "tests": "test_v4_ai_residue.py",
     "family": lambda f: code(f) == "AI_RESPONSE_RESIDUE",
     "defects": [D("§3-6a", "챗봇 맺음말", lambda f: code(f) == "AI_RESPONSE_RESIDUE" and "맺음말" in title(f), doc="민사_준비서면.pdf"),
                 D("§3-6b", "출처 토큰", lambda f: code(f) == "AI_RESPONSE_RESIDUE" and "출처" in title(f), doc="민사_준비서면.pdf"),
                 D("§3-6c", "렌더링되지 않은 마크다운 표", lambda f: code(f) == "AI_RESPONSE_RESIDUE" and "마크다운" in title(f),
                   doc="민사_준비서면.pdf")]},
    {"id": "G1", "title": "헌재 결정 조회(detc) 정확 일치", "code": "source_adapters/law_go_kr.py(search_case)",
     "call": ("legal_engine/verifier.py", "search_case"), "tests": "tests/live/test_live_sources.py", "live": ["G1"]},
    {"id": "G2", "title": "한국어 OCR 품질(쪽별 신뢰도·한글 비율)", "code": "document_engine/ocr.py(page_quality)",
     "call": ("document_engine/pdf_parser.py", "page_quality"), "tests": "test_v3_g2_ocr_quality.py", "report_na": True,
     "defects": [D("G2-1", "형사 3쪽 OCR 품질 기록", check=lambda out: ocr_quality_on(out, "형사_변론요지서.pdf", 3))]},
    {"id": "G3", "title": "항·호 단위 결합('같은 조 제N항')", "code": "legal_engine/citation_extractor.py(_resolve_article_references)",
     "call": ("legal_engine/citation_extractor.py", "_resolve_article_references"), "tests": "test_v3_g3_paragraph_binding.py", "report_na": True,
     "defects": [D("G3-1", "민사: '같은 조 제2항' → 가상손해배상법 제10조 제2항", check=lambda out: resolved_label(out, "민사_준비서면.pdf", "가상손해배상법 제10조 제2항"))]},
    {"id": "G4", "title": "법리 주장 유형 분류→근거 조회→판단", "code": "legal_engine/claim_review.py",
     "call": ("verification_engine/pipeline.py", "review_claims"), "tests": "test_v3_g4_claims.py",
     "defects": [D("G4-1", "민사: 전칭 일반화", lambda f: rule(f) == "CLAIM.UNSUPPORTED_GENERALIZATION"),
                 D("G4-2", "민사: 법률 근거 없는 배수 배상", lambda f: rule(f) == "CLAIM.NO_BASIS_REMEDY"),
                 D("G4-3", "행정: 취소소송 제소기간 배제 주장", lambda f: rule(f) in {"CLAIM.LITIGATION_REQUIREMENT_EXCLUSION", "ADMIN.DEADLINE_EXCEPTION"})]},
    {"id": "G5", "title": "사실 저장소(문서 간·문서 안)·증거 선후", "code": "claim_engine/fact_store.py, evidence_consistency.py",
     "call": ("verification_engine/pipeline.py", "cross_document_facts"), "tests": "test_v3_g5_facts.py, test_v4_p1_facts.py",
     "defects": [D("G5-1", "민사 부위 좌우(문서 간)", lambda f: rule(f) == "FACT.INJURY_SIDE" and features(f).get("scope") == "CROSS_DOCUMENT"),
                 D("G5-2", "민사 사고일(문서 간)", lambda f: rule(f) == "FACT.INCIDENT_DATE"),
                 D("G5-3", "민사 증거 작성일<사건일(사고경위서)", lambda f: str(f.type) == "EVIDENCE_TIMELINE_INVERSION" and "사고경위서" in title(f))]},
    {"id": "G6", "title": "오탐 제거(파일명 표지 등)", "code": "forensic_engine/covert.py",
     "call": ("verification_engine/pipeline.py", "self.forensic.scan"), "tests": "test_v3_g6_filename.py", "report_na": True,
     "defects": [D("G6-1", "파일명 표지 오탐 없음", check=lambda out: not [f for f in all_findings(out) if "파일명" in title(f)])]},
    {"id": "J1", "title": "헌재 조회 재조회·정확 일치(병합 표기 포함)", "code": "source_adapters/law_go_kr.py",
     "call": ("legal_engine/verifier.py", "search_case"), "tests": "tests/live/test_live_sources.py", "live": ["J1"]},
    {"id": "J2", "title": "AI 모델 사실 모순 지적 결정론 재검증", "code": "verification_engine/ai_document_detector.py",
     "call": ("verification_engine/pipeline.py", "reconcile_model_fact_remarks"), "tests": "tests/live/test_live_models.py", "live": ["J2"]},
    {"id": "J3", "title": "산식 행('a × b = c') 검산", "code": "claim_engine/calculation.py(evaluate_expression)",
     "call": ("verification_engine/pipeline.py", "self.calculation.verify_document"), "tests": "test_v3_j3_arithmetic.py",
     "family": lambda f: rule(f) == "CALC.FORMULA",
     "defects": [D("J3-1", "민사 간병비 산식 행", lambda f: rule(f) == "CALC.FORMULA")]},
    {"id": "J4", "title": "글자별 가시성(투명도·대비·가림)", "code": "document_engine/pdf_parser.py", "call": ("document_engine/pdf_parser.py", "_render_facts"),
     "tests": "test_v3_j4_visibility.py",
     "defects": [D("J4-1", "투명 글자", injection("투명 글자")), D("J4-2", "이미지로 덮은 글자", injection("이미지로 덮은")),
                 D("J4-3", "저대비 글자", injection("대비"))]},
    {"id": "J5", "title": "조회 실패는 NOT_FOUND가 아닌 UNVERIFIED", "code": "legal_engine/verifier.py",
     "call": ("legal_engine/verifier.py", "verify_case"), "tests": "test_v3_g1_detc.py", "report_na": True,
     "defects": [D("J5-1", "오프라인 조회 실패 인용에 NOT_FOUND 판정 없음", check=lambda out: not [f for f in all_findings(out) if str(f.status) == "NOT_FOUND"])]},
    {"id": "J6", "title": "scanned_layers에 실제 검사 경로 기록", "code": "adversarial_engine/scanner.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v4_p7_injection_paths.py", "report_na": True,
     "defects": [D(f"J6-{name}", f"scanned_layers에 {name}", check=(lambda n: lambda out: n in layers(out))(name))
                 for name in ("metadata", "outline", "annotation", "form_field", "attachment", "image_ocr")]},
    {"id": "R1", "title": "다른 서면을 조항 원문으로 쓰지 않음", "code": "legal_engine/internal_citation.py", "call": ("verification_engine/pipeline.py", "_internal_citation_check"),
     "tests": "test_v2_root_causes.py", "report_na": True,
     "defects": [D("R1-1", "서면 간 조항 대조 오판 없음", check=lambda out: not [f for f in all_findings(out) if str(f.type) == "INTERNAL_CITATION_ERROR"])]},
    {"id": "R2", "title": "인용문을 올바른 인용에 결합(기대값 대조)", "code": "legal_engine/citation_extractor.py(bind_quotes)", "call": ("legal_engine/citation_extractor.py", "bind_quotes"),
     "tests": "test_v2_root_causes.py", "report_na": True, "r2": True},
    {"id": "R3", "title": "줄바꿈으로 법원·선고일 유실 방지(읽기 본문)", "code": "document_engine/reading_text.py", "call": ("legal_engine/citation_extractor.py", "build_reading_text"),
     "tests": "tests/live/test_live_sources.py", "live": ["R3"],
     "defects": [D("R3-1", "민사: 줄바꿈으로 나뉜 '대법원 2016. 5. 12. / 선고 2015다90022'", check=lambda out: any(
         c.get("case_number") == "2015다90022" and c.get("court") == "대법원" and c.get("decision_date") == "2016-05-12"
         and "\n" in (c.get("raw_text") or "") for c in document(out, "민사_준비서면.pdf").citations))]},
    {"id": "R4", "title": "사건번호 정확 일치 기록만 채택", "code": "source_adapters/law_go_kr.py", "call": ("legal_engine/verifier.py", "search_case"),
     "tests": "tests/live/test_live_sources.py", "live": ["R4"]},
    {"id": "R5", "title": "조문 본문 대조(claim_text)", "code": "legal_engine/provision_content.py", "call": ("legal_engine/source_review.py", "compare_claim_to_provision"),
     "tests": "test_v2_root_causes.py, test_v3_g3_paragraph_binding.py",
     "family": lambda f: str(f.type) == "LAW_CITATION_ERROR" and str(f.status) == "CONTRADICTED" and "가상손해배상법" in title(f),
     "defects": [D("R5-1", "민사: 제10조 제2항 10년(원문 5년)", lambda f: str(f.type) == "LAW_CITATION_ERROR" and str(f.status) == "CONTRADICTED" and "제2항" in title(f))]},
    {"id": "R6", "title": "머리글·바닥글 반복 줄 제외", "code": "document_engine/reading_text.py(mark_running_heads)", "call": ("adversarial_engine/scanner.py", "running_head"),
     "tests": "tests/live/test_live_sources.py", "live": ["R6"],
     "defects": [D("R6-1", "민사: 머리글의 '대법원 2014다90011 판결'을 인용으로 세지 않음(본문 2회)",
                   check=lambda out: citation_count(out, "민사_준비서면.pdf", "2014다90011") == 2)]},
    {"id": "R7", "title": "법령명 추출", "code": "legal_engine/normalize.py(law_name_suffix)", "call": ("legal_engine/citation_extractor.py", "law_name_suffix"),
     "tests": "test_v2_root_causes.py", "report_na": True,
     "defects": [D(f"R7-{n}", f"법령명 '{n}' 추출", check=(lambda law, doc: lambda out: any(c.get("law_name") == law for c in document(out, doc).citations))(n, d))
                 for n, d in (("가상손해배상법", "민사_준비서면.pdf"), ("민법", "민사_준비서면.pdf"), ("가상형사법", "형사_변론요지서.pdf"),
                              ("가상행정절차법", "행정_의견서.pdf"))]},
    {"id": "R8", "title": "숨김 경로별 개별 탐지(Tr 3·가림)", "code": "document_engine/pdf_parser.py, adversarial_engine/scanner.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v2_root_causes.py",
     "defects": [D("R8-1", "렌더모드 3", injection("렌더모드")), D("R8-2", "이미지로 덮은 글자", injection("이미지로 덮은"))]},
    {"id": "R9", "title": "증거 정합성(달력·결번)", "code": "claim_engine/evidence_consistency.py", "call": ("verification_engine/pipeline.py", "check_evidence_consistency"),
     "tests": "test_v2_root_causes.py",
     "defects": [D("R9-1", "달력에 없는 작성일", lambda f: str(f.type) == "EVIDENCE_DATE_INVALID"),
                 D("R9-2", "가지번호 결번", lambda f: str(f.type) == "EVIDENCE_NUMBERING_GAP")]},
    {"id": "R10", "title": "AI 판정 축과 문서 결과 일치", "code": "verification_engine/ai_document_detector.py, scoring.py", "call": ("verification_engine/pipeline.py", "create_ai_detector_findings"),
     "tests": "tests/live/test_live_models.py", "live": ["R10"]},
    {"id": "R11", "title": "같은 인용 중복 추출 방지", "code": "legal_engine/citation_extractor.py", "call": ("verification_engine/pipeline.py", "extract_citations"),
     "tests": "test_v2_root_causes.py", "report_na": True,
     "defects": [D("R11-1", "중복 추출 0건", check=lambda out: duplicate_citations(out) == 0)]},
    # --- v4 P1~P8 ------------------------------------------------------------------------
    {"id": "P1", "title": "사실 저장소 교차검증(CROSS_DOC_INCONSISTENCY, 문서 간·문서 안, 자릿수 뒤바뀜)", "code": "claim_engine/fact_store.py",
     "call": ("verification_engine/pipeline.py", "cross_document_facts"), "tests": "test_v4_p1_facts.py",
     "family": lambda f: str(f.type) == "CROSS_DOCUMENT_CONTRADICTION" and rule(f).startswith("FACT."),
     "defects": [D("P1-1", "민사 부위 좌우(준비서면↔진단서)", lambda f: rule(f) == "FACT.INJURY_SIDE" and features(f).get("scope") == "CROSS_DOCUMENT"),
                 D("P1-2", "민사 부위 좌우(준비서면 본문↔첨부 진단서, 문서 안)", lambda f: rule(f) == "FACT.INJURY_SIDE" and features(f).get("scope") == "IN_DOCUMENT"),
                 D("P1-3", "민사 사고일(준비서면↔진단서)", lambda f: rule(f) == "FACT.INCIDENT_DATE"),
                 D("P1-4", "가사 원고 성명 표기(박○○↔이○○, 문서 안)", lambda f: rule(f) == "FACT.PARTY_NAME"),
                 D("P1-5", "가사 청구금액 자릿수 뒤바뀜(소장 205,000,000↔답변서 250,000,000)",
                   lambda f: rule(f) == "FACT.CLAIM_AMOUNT" and features(f).get("digit_transposition"))],
     "fp_check": cross_case_comparisons},
    {"id": "P2", "title": "법원–사건부호(=D2), 공백 정규화·헌재 일련번호", "code": "legal_engine/citation_format.py, citation_extractor.py",
     "call": ("legal_engine/verifier.py", "format_violations"), "tests": "test_v3_d2_case_codes.py", "same_as": "D2"},
    {"id": "P3", "title": "법령 적용 시점(행위시법) 판단", "code": "legal_engine/temporal_review.py",
     "call": ("verification_engine/pipeline.py", "review_temporal_application"), "tests": "test_v4_p3_temporal.py",
     "family": lambda f: rule(f).startswith("TEMPORAL."),
     "defects": [D("P3-1", "형사: 행위시 버전(5년)과 일치 — 확인, '현행과 다름' 안내", lambda f: rule(f) == "TEMPORAL.REFERENCE_VERSION_MATCH"),
                 D("P3-2", "형사: 어느 버전과도 불일치(10년) — 두 버전 값 제시", lambda f: rule(f) == "TEMPORAL.NO_VERSION_MATCH" and str(f.status) == "CONTRADICTED")]},
    {"id": "P4", "title": "증거·금액 검사 보강(한글 금액·목록↔원문·번호 중복·서면 작성일 이후)", "code": "claim_engine/korean_amount.py, evidence_consistency.py",
     "call": ("verification_engine/pipeline.py", "check_evidence_consistency"), "tests": "test_v4_p4_evidence_amounts.py",
     "family": lambda f: rule(f) in {"AMOUNT.WORDS_MISMATCH", "EVI.LIST_AMOUNT_MISMATCH", "EVI.EVIDENCE_NUMBER_DUPLICATE"}
                         or str(f.type) == "EVIDENCE_TIMELINE_INVERSION",
     "defects": [D("P4-1", "민사 한글 금액(칠백만원↔7,500,000원)", lambda f: rule(f) == "AMOUNT.WORDS_MISMATCH" and "7,500,000" in title(f)),
                 D("P4-2", "가사 한글 금액(이억오천만원↔205,000,000원)", lambda f: rule(f) == "AMOUNT.WORDS_MISMATCH" and "205,000,000" in title(f)),
                 D("P4-3", "가사 증거목록 금액↔첨부 원문(12,000,000↔21,000,000)", lambda f: rule(f) == "EVI.LIST_AMOUNT_MISMATCH"),
                 D("P4-4", "민사 호증 번호 중복(갑 제5호증)", lambda f: rule(f) == "EVI.EVIDENCE_NUMBER_DUPLICATE"),
                 D("P4-5", "민사 서면 작성일 이후 작성 증거(사실확인서)", lambda f: str(f.type) == "EVIDENCE_TIMELINE_INVERSION" and "사실확인서" in title(f)),
                 D("P4-6", "민사 사건일 전 작성 증거(사고경위서)", lambda f: str(f.type) == "EVIDENCE_TIMELINE_INVERSION" and "사고경위서" in title(f))],
     "fp_check": concatenated_cells},
    {"id": "P5", "title": "법리 검토 확장(재량↔의무·판례 방향 반대·절차 규칙·양형 사유 혼동)", "code": "legal_engine/claim_review.py, opinion_attribution.py",
     "call": ("verification_engine/pipeline.py", "review_claims"), "tests": "test_v4_p5_legal_rules.py",
     "family": lambda f: rule(f) in {"CLAIM.DISCRETION_AS_MANDATE", "CLAIM.MANDATE_AS_DISCRETION", "CLAIM.SENTENCING_AS_ELEMENT",
                                     "CLAIM.PROCEDURAL_RULE", "OPINION.HOLDING_DIRECTION_REVERSED"},
     "defects": [D("P5-1", "행정: '할 수 있다' 조문을 의무로 주장", lambda f: rule(f) == "CLAIM.DISCRETION_AS_MANDATE"),
                 D("P5-2", "민사: 판결 취지 방향 반대 요약(2014다90011)", lambda f: rule(f) == "OPINION.HOLDING_DIRECTION_REVERSED" and "2014다90011" in title(f)),
                 D("P5-3", "형사: 불이익변경금지 적용 범위 오인", lambda f: rule(f) == "CLAIM.PROCEDURAL_RULE"),
                 D("P5-4", "형사: 사후 변제를 범죄 불성립 사유로 주장", lambda f: rule(f) == "CLAIM.SENTENCING_AS_ELEMENT")]},
    {"id": "P6", "title": "AI 판별 집계(관여 여부·범위 분리, 약한 신호는 참고 부록)", "code": "verification_engine/ai_document_detector.py",
     "call": ("verification_engine/pipeline.py", "create_ai_detector_findings"), "tests": "test_v4_p6_ai_aggregation.py",
     "family": lambda f: str(f.type) == "AI_AUTHORSHIP_LIKELY" and not f.advisory_only,
     "defects": [D("P6-1", "민사(AI 잔재 문서)에 AI 관여 근거 제시", lambda f: str(f.type) == "AI_AUTHORSHIP_LIKELY" or code(f) == "AI_RESPONSE_RESIDUE")],
     "fp_doc_exclude": ["민사_준비서면.pdf"]},
    {"id": "P7", "title": "인젝션 경로 전수 검사·경로별 개별 finding", "code": "adversarial_engine/scanner.py, document_engine/pdf_parser.py",
     "call": ("verification_engine/pipeline.py", "self.adversarial.scan"), "tests": "test_v4_p7_injection_paths.py",
     "family": lambda f: str(f.type) in INJECTION_TYPES,
     "defects": [D(f"P7-{i}", label, injection(key)) for i, (label, key) in enumerate((
         ("흰 글자", "흰 글자"), ("투명 글자", "투명 글자"), ("저대비", "대비"), ("이미지로 덮은 글자", "이미지로 덮은"),
         ("렌더모드 3", "렌더모드"), ("초소형 글자", "작은 글자"), ("페이지 밖", "페이지 밖"), ("문서 속성", "문서 속성"),
         ("주석", "주석"), ("북마크", "북마크"), ("양식 필드", "양식"), ("첨부파일", "첨부파일"), ("Base64", "인코딩"),
         ("전각", "전각"), ("폭 0 문자", "폭 0"), ("한글 자모 분리", "자모")), start=1)]
        + [D("P7-17", "민사: 보이는 본문 지시문", injection("보이는 본문"), doc="민사_준비서면.pdf")],
     "family_docs": ["행정_의견서.pdf", "민사_준비서면.pdf"]},
    {"id": "P8", "title": "파서 대체 경로·손상 PDF·회전 스캔·보고서 직렬화", "code": "document_engine/pdf_parser.py, report_engine/serialize.py",
     "call": ("verification_engine/pipeline.py", "parse_document"), "tests": "test_v4_p8_parser_report.py",
     "defects": [D("P8-1", "손상 PDF 구조 손상 신호(MALFORMED_PDF)", lambda f: code(f) == "MALFORMED_PDF"),
                 D("P8-2", "손상 PDF 본문 추출(날짜 불가능 인용 판정)", lambda f: rule(f) == "FMT.DATE_NOT_ON_CALENDAR" and "2020두12345" in title(f)),
                 D("P8-3", "회전 스캔 쪽 방향 보정 후 판정(2016도54321)", lambda f: rule(f) == "FMT.DATE_NOT_ON_CALENDAR" and "54321" in title(f))]},
]
