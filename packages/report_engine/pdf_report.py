"""제20.3장 검증보고서 PDF 및 Highlight PDF.

보고서 구성:
 검증개요·대상문서·방법론 / 핵심 CRITICAL·HIGH / 판례·법령·유권해석·학술자료 검증표 /
 사실관계·논리·문서간 모순 / AI 작성 분석 / 문서 포렌식·전자서명 /
 메타 지시어·Prompt Injection 결과 / 미검증 항목·사용하지 못한 Source /
 방법론상 한계 / Chain of Custody Manifest
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.common.enums import MM4_ADVISORY_TYPES, Severity
from .snapshot import json_lines, technical_payload, xml_text

KOREAN_FONT = "HYSMyeongJo-Medium"


def _register_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    embedded = "ACASKorean"
    if embedded in pdfmetrics.getRegisteredFontNames():
        return embedded
    for candidate in (os.getenv("LV_REPORT_FONT_PATH", ""), "C:/Windows/Fonts/malgun.ttf",
                      "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"):
        if candidate and Path(candidate).is_file():
            try:
                pdfmetrics.registerFont(TTFont(embedded, candidate))
                return embedded
            except (OSError, ValueError):
                continue

    try:
        pdfmetrics.getFont(KOREAN_FONT)
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT))
    return KOREAN_FONT


def _styles():
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    font = _register_font()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=font, fontSize=18, leading=24),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=font, fontSize=13, leading=18, spaceBefore=14),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=font, fontSize=11, leading=15, spaceBefore=8),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontName=font, fontSize=9, leading=13, alignment=TA_LEFT),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontName=font, fontSize=7.5, leading=10),
    }


# 내장 CID 폰트(HYSMyeongJo-Medium)가 표현하지 못하는 문자를 대체한다.
GLYPH_FALLBACK = {
    "\u00b7": "\u30fb",  # MIDDLE DOT -> KATAKANA MIDDLE DOT
    "\u20a9": "원",        # WON SIGN
    "\u223c": "~",         # TILDE OPERATOR
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
}


def _sanitize(text: str) -> str:
    for source, target in GLYPH_FALLBACK.items():
        text = text.replace(source, target)
    return text


def _escape(text: Any) -> str:
    return (
        _sanitize(xml_text(text))
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_report_pdf(
    run_result: Any,
    *,
    project: Optional[Dict[str, Any]] = None,
    manifest: Optional[Dict[str, Any]] = None,
    reveal_sealed: bool = False,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = _styles()
    font = _register_font()
    project = project or {}
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title="ACASia_LAW 법률문서 검증보고서",
    )
    story: List[Any] = []
    findings = run_result.all_findings
    main_findings = [f for f in findings if not f.advisory_only and f.type not in MM4_ADVISORY_TYPES]
    advisory_findings = [f for f in findings if f.advisory_only or f.type in MM4_ADVISORY_TYPES]

    def table(rows: List[List[str]], widths: List[float]) -> Any:
        data = [[Paragraph(_escape(cell), styles["small"]) for cell in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1, splitInRow=1)
        t.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B0B0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECF2")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (-1, -1), font),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return t

    # --- 표지 / 1. 검증개요 ------------------------------------------------
    story.append(Paragraph("ACASia_LAW 법률문서 검증시스템", styles["title"]))
    story.append(Paragraph("법률문서 검증보고서", styles["h1"]))
    metadata = getattr(run_result, "report_metadata", {})
    if metadata:
        story.append(Paragraph(_escape(metadata["label"]), styles["h1"]))
        for key in ("source_run_id", "source_run_hash", "snapshot_hash", "export_snapshot_hash",
                    "created_by", "created_at", "finalized_by", "finalized_at", "note", "review_notice"):
            if metadata.get(key) is not None:
                story.append(Paragraph(_escape(f"{key}: {metadata[key]}"), styles["small"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(_escape("1. 검증개요·대상문서·방법론"), styles["h1"]))
    overview = [
        ["항목", "내용"],
        ["프로젝트", f"{project.get('name', '-')} / 사건번호 {project.get('case_number', '-')}"],
        ["법원·기관", str(project.get("court", "-"))],
        ["검증 Run", run_result.run_id],
        ["상태", str(run_result.state)],
        ["Verification Key", run_result.verification_key],
        ["생성시각(UTC)", datetime.utcnow().isoformat(timespec="seconds")],
        ["대상 문서", ", ".join(d.filename for d in run_result.documents) or "-"],
        [
            "방법론",
            "공식 Source·결정론적 엔진을 우선 적용하고(Source First), 의미 비교·반대검증에만 LLM을 사용한다. "
            "문서는 UNTRUSTED EVIDENCE로 취급하며 문서 내 문자열은 시스템 지침이 되지 않는다. "
            "위조·진정성립·고의에 관한 최종 법적 평가는 사용자에게 있다(Human Final Decision).",
        ],
    ]
    story.append(table(overview, [90, 400]))

    story.append(Paragraph(_escape("문서별 무결성"), styles["h2"]))
    integrity = [["문서", "SHA-256", "파서", "격리", "경고"]]
    for d in run_result.documents:
        integrity.append(
            [
                d.filename,
                d.normalized.sha256 if d.normalized else "-",
                d.normalized.parser_name if d.normalized else "-",
                "QUARANTINED" if d.quarantined else "-",
                str(len(d.warnings)),
            ]
        )
    story.append(table(integrity, [110, 180, 90, 60, 40]))

    # --- 2. 핵심 CRITICAL / HIGH -------------------------------------------
    story.append(Paragraph(_escape("2. 핵심 CRITICAL·HIGH 사항"), styles["h1"]))
    critical = [f for f in main_findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]
    if critical:
        rows = [["위험도", "유형", "등급", "확신도", "내용"]]
        for f in sorted(critical, key=lambda x: -x.severity.rank):
            rows.append(
                [str(f.severity), str(f.type), str(f.evidence_grade), f"{f.confidence:.2f}",
                 f"{f.title}\n{f.detail}"]
            )
        story.append(table(rows, [50, 110, 34, 40, 256]))
    else:
        story.append(Paragraph("CRITICAL·HIGH 등급 항목이 없다.", styles["body"]))

    # --- 3. 법률 인용 검증표 ------------------------------------------------
    story.append(Paragraph(_escape("3. 판례·법령·유권해석·학술자료 검증표"), styles["h1"]))
    citation_rows = [["문서", "면", "인용", "구분", "검증결과", "근거등급"]]
    for d in run_result.documents:
        verdict_by_id = {v["citation_id"]: v for v in (d.engine_data.get("legal_verdicts") or [])}
        for citation in d.citations:
            verdict = verdict_by_id.get(citation["citation_id"], {})
            citation_rows.append(
                [
                    d.filename,
                    str(citation.get("page") or "-"),
                    (citation.get("raw_text") or ""),
                    str(citation.get("type")),
                    verdict.get("status", "UNVERIFIED"),
                    "A" if verdict.get("official_record") else "U",
                ]
            )
    if len(citation_rows) > 1:
        story.append(table(citation_rows, [80, 24, 170, 60, 90, 44]))
    else:
        story.append(Paragraph("추출된 법률 인용이 없다.", styles["body"]))

    # --- 4. 사실관계·논리·문서간 모순 ---------------------------------------
    story.append(Paragraph(_escape("4. 사실관계·논리·문서간 모순"), styles["h1"]))
    story.append(_section_table(table, main_findings, {"FACT_CONTRADICTION", "CROSS_DOCUMENT_CONTRADICTION",
                                                       "TIMELINE_CONTRADICTION", "ARITHMETIC_MISMATCH"}, styles))

    # --- 5. AI 작성 분석 및 법률 주장 타당성 검토 -----------------------
    story.append(Paragraph(_escape("5. AI 작성 분석 및 법률 주장 타당성 검토"), styles["h1"]))
    ai_rows = [["문서", "AI 진단", "확신도", "판정 근거"]]
    for d in run_result.documents:
        det = getattr(d, "ai_detector_result", {}) or {}
        a = d.authorship or {}
        verdict_str = det.get("verdict") or a.get("verdict", "-")
        score_str = f"{det.get('score'):.2f}" if "score" in det else str(a.get("score", "-"))
        reasons_str = "; ".join(det.get("reasons", [])) if det.get("reasons") else " ".join(a.get("notes", []))
        ai_rows.append([d.filename, verdict_str, score_str, reasons_str])
    story.append(table(ai_rows, [90, 80, 40, 280]))
    from .model_opinions import model_opinion_rows

    opinion_rows = model_opinion_rows(run_result.documents)
    if opinion_rows:
        story.append(Spacer(1, 4))
        story.append(Paragraph(_escape("모델별 AI 작성 판정"), styles["h2"]))
        story.append(table([["문서", "모델", "판정", "점수", "근거"], *opinion_rows], [80, 70, 70, 30, 240]))

    # AI 환각 및 법률 주장 타당성 대조표
    all_hallucination_rows = []
    for d in run_result.documents:
        for row in getattr(d, "ai_hallucination_table", []) or []:
            all_hallucination_rows.append([
                d.filename + " " + str(row.get("location", "")),
                str(row.get("claim_text", ""))[:120] + "\n(" + str(row.get("cited_authority", "")) + ")",
                str(row.get("ai_generation_basis", ""))[:120],
                str(row.get("legal_reasoning", ""))[:140] + "\n[대응] " + str(row.get("recommended_counteraction", ""))[:100],
                str(row.get("validity_verdict", "")),
            ])
    if all_hallucination_rows:
        story.append(Spacer(1, 4))
        story.append(Paragraph(_escape("AI 임의 생성(환각) 및 법률적 주장 타당성 대조표"), styles["h2"]))
        h_table_rows = [["위치", "문서 주장 / 인용", "AI 생성 근거", "법리적 검토 및 반박 근거", "평가"]] + all_hallucination_rows
        story.append(table(h_table_rows, [65, 110, 105, 150, 60]))

    # --- 6. 문서 포렌식·전자서명 --------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph(_escape("6. 문서 포렌식·전자서명"), styles["h1"]))
    story.append(_section_table(table, main_findings, {"METADATA_ANOMALY", "PAGE_STRUCTURE_OUTLIER",
                                                       "SIGNATURE_INVALID", "MODIFIED_AFTER_SIGNATURE",
                                                       "PRIOR_VERSION_RECOVERABLE", "REDACTION_FAILURE",
                                                       "RESIDUAL_TRACKED_CHANGE", "RESIDUAL_COMMENT",
                                                       "DELETED_TEXT_RECOVERABLE", "HIDDEN_SHEET_OR_ROW",
                                                       "AUTHORSHIP_METADATA_LEAK", "GEOLOCATION_METADATA_LEAK",
                                                       "TEMPLATE_RESIDUE", "CROPPED_IMAGE_RESIDUE",
                                                       "PRIVILEGE_EXPOSURE_RISK"}, styles))

    # --- 7. 메타 지시어 / Prompt Injection ---------------------------------
    story.append(Paragraph(_escape("7. 메타 지시어·Prompt Injection 검사 결과"), styles["h1"]))
    adversarial_types = {
        "PROMPT_INJECTION_SUSPECTED", "HIDDEN_INSTRUCTION", "META_INSTRUCTION", "SYSTEM_OVERRIDE_ATTEMPT",
        "ROLE_OVERRIDE_ATTEMPT", "VERIFICATION_SUPPRESSION", "OUTPUT_MANIPULATION_ATTEMPT", "ENCODED_INSTRUCTION",
        "UNICODE_SMUGGLING", "OCR_LAYER_INJECTION", "METADATA_INJECTION", "MULTIMODAL_INJECTION",
        "HIDDEN_TEXT_MISMATCH", "OCR_LAYER_MISMATCH", "TOOL_MANIPULATION_ATTEMPT", "DATA_EXFILTRATION_INSTRUCTION",
    }
    story.append(_section_table(table, main_findings, adversarial_types, styles))
    story.append(
        Paragraph(
            _escape(
                "탐지된 지시형 문자열은 자료로만 취급되었고 검증 절차·Source 우선순위·Tool 권한에 영향을 주지 않았다. "
                "봉인된 원문은 사용자 열람 요청 시에만 공개되며 열람 사실은 감사추적에 기록된다."
            ),
            styles["body"],
        )
    )

    # --- 8. 미검증 항목 / 사용하지 못한 Source -------------------------------
    story.append(Paragraph(_escape("8. 미검증 항목 및 사용하지 못한 Source"), styles["h1"]))
    unverified_rows = [["구분", "대상", "사유"]]
    for item in run_result.unverified_items:
        unverified_rows.append([item.get("kind", "-"), (item.get("raw_text") or item.get("document_id") or "-"),
                                (item.get("reason") or "-")])
    for source in run_result.unavailable_sources:
        unverified_rows.append(["source", source.get("name", "-"), f"{source.get('status', 'UNVERIFIED')} {source.get('note', '')}"])
    if len(unverified_rows) > 1:
        story.append(table(unverified_rows, [50, 190, 250]))
    else:
        story.append(Paragraph("미검증 항목이 없다.", styles["body"]))

    # --- 9. 참고 신호 (MM-4) — 본문과 분리 ----------------------------------
    story.append(Paragraph(_escape("9. 참고 신호 (Advisory Signals, MM-4)"), styles["h1"]))
    story.append(
        Paragraph(
            _escape(
                "아래 항목은 해석의 영역에 속하는 참고 신호이다. Severity 상한 MEDIUM, Evidence Grade D, "
                "Verification Status UNVERIFIED로 고정되며, 이 신호만으로 허위·고의·위법을 단정하지 않는다."
            ),
            styles["body"],
        )
    )
    if advisory_findings:
        rows = [["유형", "근거 위치", "내용"]]
        for f in advisory_findings:
            rows.append([str(f.type), f"{f.document_id or '-'} p{f.page or '-'} {f.block_id or ''}",
                         f"{f.title} / {f.detail}"])
        story.append(table(rows, [120, 110, 260]))
    else:
        story.append(Paragraph("해당 없음.", styles["body"]))

    # --- 10. 방법론상 한계 --------------------------------------------------
    story.append(Paragraph("10. 방법론상 한계", styles["h1"]))
    for line in [
        "공식 Source에서 확인되지 않는 인용은 '존재하지 않는다'는 의미가 아니다. 미공개 판결이나 DB 수록 범위 밖일 수 있다.",
        "AI 작성 여부는 확률적 추정이며, 문체 유사성만으로 특정 AI 제품이 작성했다고 확정하지 않는다.",
        "포렌식 휴리스틱 한두 개만으로 위조를 단정하지 않는다. 제시된 것은 객관적 관찰사실과 위험도이다.",
        "OCR·파서 한계로 일부 텍스트가 누락될 수 있으며, 그 경우 관련 항목은 미검증으로 표시된다.",
        "API Key 미설정·외부 장애 시 해당 Source 검증은 수행되지 않고 미검증으로 남는다.",
        "본 보고서는 검증 보조자료이며 진정성립·위조·고의에 관한 최종 판단은 사용자에게 있다.",
    ]:
        story.append(Paragraph(f"• {_escape(line)}", styles["body"]))

    # --- 11. Chain of Custody ----------------------------------------------
    story.append(Paragraph("11. Chain of Custody Manifest", styles["h1"]))
    if manifest:
        story.append(
            table(
                [
                    ["항목", "값"],
                    ["이벤트 수", str(manifest.get("event_count"))],
                    ["전체 체인 무결성", "정상" if manifest.get("chain_valid") is True else
                     "손상" if manifest.get("chain_valid") is False else "미검증 (사건별 기록만 조회)"],
                    ["Head Hash", str(manifest.get("head_hash"))],
                    ["생성시각", str(manifest.get("generated_at"))],
                ],
                [90, 400],
            )
        )
    else:
        story.append(Paragraph("Manifest가 제공되지 않았다.", styles["body"]))

    story.append(Paragraph("12. 실행 범위 및 기술적 부록", styles["h1"]))
    snapshot = getattr(run_result, "input_snapshot", {})
    context = snapshot.get("context", {})
    story.append(table([["항목", "실행 당시 설정"],
        ["범위 변경 번호", str(snapshot.get("scope_revision", "기록 없음"))],
        ["검증 프로필", str(context.get("profile", "기록 없음"))],
        ["외부 AI 정책", str(context.get("external_ai_policy", "기록 없음"))],
        ["법령 기준일", str(context.get("case_date") or "미지정: 시행법 적합성 미검증")],
        ["판정 한계", "VERIFIED는 해당 검사 단계의 확인 결과이며 문서 전체의 적법성 보증이 아니다. 신뢰도 지표는 통계적으로 보정된 확률이 아니다."]], [100, 390]))
    for item in run_result.documents:
        for verdict in item.engine_data.get("legal_verdicts", []):
            story.append(Paragraph(_escape(f"{item.filename} / {verdict.get('citation_id')}: {verdict.get('levels')}"), styles["small"]))
        for coverage in item.engine_data.get("page_coverage", []):
            story.append(Paragraph(_escape(f"{item.filename}: {coverage}"), styles["small"]))
        for record in item.source_records:
            source = record.to_dict() if hasattr(record, "to_dict") else record
            story.append(Paragraph(_escape(f"Source: {source.get('adapter')} / {source.get('retrieved_at')} / SHA-256 {source.get('response_hash')} / {source.get('url')}"), styles["small"]))
        for review in item.engine_data.get("semantic_reviews", []):
            story.append(Paragraph(_escape(f"AI 참고 의견 / {review.get('citation_id')} / 근거 문구 대조 {review.get('source_quotes_validated', False)}: {review.get('reason')}"), styles["small"]))
    executions = getattr(run_result, "model_executions", [])
    story.append(Paragraph(_escape(f"모델 호출 기록: {executions}" if executions else "실행된 모델 호출 없음. 의미·법리 적용 검토를 완료한 것으로 해석할 수 없음."), styles["small"]))
    story.append(Paragraph("실행에 저장된 검토 기록", styles["h2"]))
    for finding in findings:
        data = finding.to_dict()
        story.append(Paragraph(_escape(f"{finding.title}: {data.get('review_status', 'NEEDS_REVIEW')} / {data.get('review_note', '')}"), styles["small"]))
    snapshot = getattr(run_result, "review_snapshot", {})
    story.append(Paragraph("13. 사람의 검토 기록", styles["h1"]))
    rows = [["항목", "시스템 결과", "검토 진행", "검토 의견", "담당자와 메모"]]
    for item in snapshot.get("workflow", []):
        rows.append([item.get("finding_id"), item.get("system_status"), item.get("workflow_state"),
                     item.get("decision"), f"{item.get('updated_by', '')} / {item.get('note', '')}"])
    story.append(table(rows, [105, 70, 80, 80, 155]))
    story.append(Paragraph("14. 쟁점과 주장 및 증거 관계", styles["h1"]))
    for issue in snapshot.get("matrix", {}).get("issues", []):
        story.append(Paragraph(_escape(f"{issue.get('title')} / {issue.get('legal_basis', '')}"), styles["body"]))
        story.append(Paragraph(_escape(f"요건사실: {issue.get('elements', [])} / 기준일: {issue.get('reference_date')}"), styles["body"]))
    rows = [["주장", "쟁점과 입장", "증거 검토", "연결 증거와 부족 자료"]]
    for item in snapshot.get("matrix", {}).get("claims", []):
        assessment = item.get("assessment", {})
        rows.append([item["claim"].get("text", ""), f"{assessment.get('issue_id', '')} / {assessment.get('position', 'UNASSESSED')}",
                     item.get("review_status", "UNASSESSED"),
                     f"{assessment.get('evidence_links', [])} / {assessment.get('missing_material', '')}"])
    story.append(table(rows, [140, 95, 85, 170]))
    story.append(Paragraph("15. 전체 기술 기록", styles["h1"]))
    story.append(Paragraph(_escape("실행 당시 기록된 검사 상태와 사용 불가 단계, 전체 출처, 모델 실행, 증거 및 검토 스냅샷을 수록합니다. 기록 부재는 검사 성공을 뜻하지 않습니다. 공유용에서 제외한 내용은 공유 정책에 표시합니다."), styles["body"]))
    for path, value in json_lines(technical_payload(run_result)):
        story.append(Paragraph(_escape(path), styles["small"]))
        for offset in range(0, max(1, len(value)), 1600):
            story.append(Paragraph(_escape(value[offset:offset + 1600]), styles["small"]))
    document.build(story)
    return buffer.getvalue()


def _section_table(table_fn, findings: List[Any], types: set, styles) -> Any:
    from reportlab.platypus import Paragraph

    selected = [f for f in findings if str(f.type) in types]
    if not selected:
        return Paragraph("해당 항목이 없다.", styles["body"])
    rows = [["위험도", "유형", "등급", "위치", "내용"]]
    for f in sorted(selected, key=lambda x: -x.severity.rank):
        rows.append(
            [
                str(f.severity),
                str(f.type),
                str(f.evidence_grade),
                f"p{f.page or '-'}",
                f"{f.title} / {f.detail}",
            ]
        )
    return table_fn(rows, [50, 118, 30, 32, 260])


def build_highlight_pdf(source_pdf: bytes, findings: List[Any]) -> bytes:
    """제20.2장 Highlight PDF. 원본은 수정하지 않고 사본에 주석을 덧그린다."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    reader = PdfReader(io.BytesIO(source_pdf))
    writer = PdfWriter()
    color_by_severity = {
        "CRITICAL": colors.Color(1, 0, 0, alpha=0.28),
        "HIGH": colors.Color(1, 0.5, 0, alpha=0.26),
        "MEDIUM": colors.Color(1, 0.85, 0, alpha=0.24),
        "LOW": colors.Color(0.2, 0.6, 1, alpha=0.20),
        "INFO": colors.Color(0.6, 0.6, 0.6, alpha=0.18),
    }
    by_page: Dict[int, List[Any]] = {}
    for finding in findings:
        if finding.page and finding.bbox:
            by_page.setdefault(finding.page, []).append(finding)

    for index, page in enumerate(reader.pages, start=1):
        page_findings = by_page.get(index)
        if page_findings:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            overlay_buffer = io.BytesIO()
            overlay = canvas.Canvas(overlay_buffer, pagesize=(width, height))
            for finding in page_findings:
                bbox = finding.bbox
                overlay.setFillColor(color_by_severity.get(str(finding.severity), color_by_severity["INFO"]))
                # pdfplumber 좌표(top 기준)를 PDF 좌표(bottom 기준)로 변환
                y0 = height - bbox.y1
                overlay.rect(bbox.x0, y0, max(2.0, bbox.x1 - bbox.x0), max(2.0, bbox.y1 - bbox.y0),
                             fill=1, stroke=0)
            overlay.save()
            overlay_buffer.seek(0)
            overlay_page = PdfReader(overlay_buffer).pages[0]
            page.merge_page(overlay_page)
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
