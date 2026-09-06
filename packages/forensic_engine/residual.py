"""제7-A.2장 MM-2 잔류형 검사.

존재 자체를 결정론적으로 증명할 수 있으므로 Finding으로 확정한다.
원문은 봉인(sealed)하여 사용자 확인 전 보고서 본문·LLM Context에 노출하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "forensic_engine.mm2"


def _finding(
    doc: NormalizedDocument,
    type_: FindingType,
    severity: Severity,
    title: str,
    detail: str,
    *,
    level: ForensicLevel,
    sealed: Optional[str] = None,
    features: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    grade: EvidenceGrade = EvidenceGrade.A,
) -> Finding:
    feats = {"deterministic_rule": True, "forensic_signal": 1, **(features or {})}
    return Finding.create(
        type=type_,
        status=VerificationStatus.SUSPICIOUS if severity.rank >= Severity.MEDIUM.rank else VerificationStatus.VERIFIED,
        severity=severity,
        evidence_grade=grade,
        title=title,
        detail=detail,
        confidence=confidence_score(feats),
        confidence_features=feats,
        document_id=doc.document_id,
        engine=ENGINE_NAME,
        meta_message_type=MetaMessageType.MM2_RESIDUAL,
        forensic_level=level,
        sealed_excerpt=sealed,
        tags=tags or [],
        evidence=[
            Evidence.create(
                description=title,
                grade=grade,
                document_id=doc.document_id,
                excerpt=(sealed or "")[:300] or None,
                sealed=bool(sealed),
            )
        ],
    )


AUTHORSHIP_KEYS = {
    "creator", "lastModifiedBy", "Author", "company", "Company", "manager",
    "dc:creator", "cp:lastModifiedBy", "Producer", "Creator",
}
PATH_RE = re.compile(r"([A-Za-z]:\\[^\s\"']+|/(?:Users|home|Volumes)/[^\s\"']+)")


def scan_residual(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    out.extend(_scan_ooxml(doc))
    out.extend(_scan_pdf(doc))
    out.extend(_scan_spreadsheet(doc))
    out.extend(_scan_image(doc))
    out.extend(_scan_common_metadata(doc))
    return out


def _scan_ooxml(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    inserts = doc.structure.get("tracked_inserts") or []
    deletes = doc.structure.get("tracked_deletes") or []
    comments = doc.structure.get("comments") or []
    hidden_runs = doc.structure.get("hidden_runs") or []
    rsids = doc.structure.get("rsids") or []
    custom_xml = doc.structure.get("custom_xml") or {}

    if inserts or deletes:
        authors = sorted({c.get("author", "") for c in inserts + deletes if c.get("author")})
        out.append(
            _finding(
                doc,
                FindingType.RESIDUAL_TRACKED_CHANGE,
                Severity.MEDIUM,
                f"미수락 변경이력 {len(inserts) + len(deletes)}건이 남아 있다",
                f"삽입 {len(inserts)}건, 삭제 {len(deletes)}건. 작성자: {', '.join(authors) or '미상'}. "
                "협의 목적으로 의도적으로 남긴 변경이력일 수 있으므로 단독으로 위·변조 근거가 되지 않는다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(f"[{c.get('author','')}] {c.get('text','')}" for c in (inserts + deletes))[:2000],
                features={"tracked_insert_count": len(inserts), "tracked_delete_count": len(deletes)},
                tags=["MM-2", "PRIVILEGE_CANDIDATE"],
            )
        )
    if deletes:
        out.append(
            _finding(
                doc,
                FindingType.DELETED_TEXT_RECOVERABLE,
                Severity.HIGH,
                f"삭제 표시된 텍스트 {len(deletes)}건이 파일 안에 그대로 남아 있다",
                "w:del 요소의 원문이 복원 가능한 상태이다. 상대방 소송준비자료가 포함될 수 있으므로 열람 전 경고가 필요하다.",
                level=ForensicLevel.SUSPICIOUS,
                sealed="\n".join(c.get("text", "") for c in deletes)[:2000],
                features={"tracked_delete_count": len(deletes)},
                tags=["MM-2", "PRIVILEGE_CANDIDATE"],
            )
        )
    if comments:
        authors = sorted({c.get("author", "") for c in comments if c.get("author")})
        out.append(
            _finding(
                doc,
                FindingType.RESIDUAL_COMMENT,
                Severity.MEDIUM,
                f"잔류 코멘트 {len(comments)}건이 있다",
                f"작성자: {', '.join(authors) or '미상'}. 공동수임 변호사 간 정상 코멘트일 수 있다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(f"[{c.get('author','')}] {c.get('text','')}" for c in comments)[:2000],
                features={"comment_count": len(comments)},
                tags=["MM-2", "PRIVILEGE_CANDIDATE"],
            )
        )
    if hidden_runs:
        out.append(
            _finding(
                doc,
                FindingType.HIDDEN_TEXT_MISMATCH,
                Severity.HIGH,
                f"숨김 서식 텍스트 {len(hidden_runs)}건이 있다",
                "w:vanish·흰색 글꼴·초소형 글꼴로 화면에 표시되지 않는 텍스트가 본문 XML에 존재한다.",
                level=ForensicLevel.SUSPICIOUS,
                sealed="\n".join(f"[{r.get('reason','')}] {r.get('text','')}" for r in hidden_runs)[:2000],
                features={"hidden_run_count": len(hidden_runs)},
                tags=["MM-2"],
            )
        )
    if len(rsids) > 1:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.INFO,
                f"편집세션(rsid) {len(rsids)}개가 관찰된다",
                "여러 편집세션의 흔적이다. 정상 편집에서도 흔히 발생하므로 참고정보로만 제시한다.",
                level=ForensicLevel.BENIGN,
                features={"rsid_count": len(rsids)},
                tags=["MM-2"],
            )
        )
    if custom_xml:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.LOW,
                f"customXml 파트 {len(custom_xml)}건이 포함되어 있다",
                "문서관리시스템이 삽입한 사건정보·고객정보가 남아 있을 수 있다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(f"{k}: {v[:400]}" for k, v in custom_xml.items())[:2000],
                features={"custom_xml_parts": len(custom_xml)},
                tags=["MM-2", "PRIVILEGE_CANDIDATE"],
            )
        )
    return out


def _scan_pdf(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    incremental = int(doc.structure.get("incremental_updates") or 0)
    if incremental > 0:
        out.append(
            _finding(
                doc,
                FindingType.PRIOR_VERSION_RECOVERABLE,
                Severity.HIGH,
                f"incremental update {incremental}회로 이전 세대가 복원 가능하다",
                "PDF에 이전 저장본이 누적되어 있어 이전 상태의 텍스트를 복원할 수 있다. "
                "전자서명 문서에서는 정상 구조일 수 있으므로 서명 정보와 함께 판단한다.",
                level=ForensicLevel.SUSPICIOUS if not doc.structure.get("has_signature_field") else ForensicLevel.NOTABLE,
                features={"incremental_updates": incremental},
                tags=["MM-2"],
            )
        )
    if doc.structure.get("ocg_off_count"):
        out.append(
            _finding(
                doc,
                FindingType.HIDDEN_TEXT_MISMATCH,
                Severity.MEDIUM,
                f"비표시 OCG 레이어 {doc.structure['ocg_off_count']}개가 있다",
                "기본 상태에서 표시되지 않는 선택적 콘텐츠 레이어가 존재한다.",
                level=ForensicLevel.NOTABLE,
                features={"ocg_off_count": doc.structure["ocg_off_count"]},
                tags=["MM-2"],
            )
        )
    annotations = doc.structure.get("annotations") or []
    with_content = [a for a in annotations if str(a.get("contents", "")).strip()]
    if with_content:
        out.append(
            _finding(
                doc,
                FindingType.RESIDUAL_COMMENT,
                Severity.MEDIUM,
                f"Annotation {len(with_content)}건에 내용이 남아 있다",
                "PDF 주석·메모의 내용은 본문 인쇄에서 보이지 않을 수 있다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(f"p{a.get('page')} [{a.get('subtype')}] {a.get('contents')}" for a in with_content)[:2000],
                features={"annotation_count": len(with_content)},
                tags=["MM-2", "PRIVILEGE_CANDIDATE"],
            )
        )
    form_values = [a for a in annotations if str(a.get("field_value", "")).strip()]
    if form_values:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.LOW,
                f"Form field 값 {len(form_values)}건이 남아 있다",
                "AcroForm 필드에 입력값이 저장되어 있다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(f"{a.get('field_name')}={a.get('field_value')}" for a in form_values)[:2000],
                tags=["MM-2"],
            )
        )
    if doc.structure.get("has_embedded_files"):
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.MEDIUM,
                "PDF에 첨부파일이 embedded 되어 있다",
                "본문에 표시되지 않는 첨부파일이 포함되어 있다. 별도 확인이 필요하다.",
                level=ForensicLevel.NOTABLE,
                tags=["MM-2"],
            )
        )
    return out


def _scan_spreadsheet(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    hidden_sheets = doc.structure.get("hidden_sheets") or []
    hidden_rows = doc.structure.get("hidden_rows") or []
    if hidden_sheets or hidden_rows:
        out.append(
            _finding(
                doc,
                FindingType.HIDDEN_SHEET_OR_ROW,
                Severity.MEDIUM,
                f"숨김 시트 {len(hidden_sheets)}개, 숨김 행·열 {len(hidden_rows)}개가 있다",
                f"숨김 시트: {', '.join(hidden_sheets) or '없음'}. 표시되지 않는 데이터가 계산에 반영되었는지 확인이 필요하다.",
                level=ForensicLevel.NOTABLE,
                features={"hidden_sheet_count": len(hidden_sheets), "hidden_row_count": len(hidden_rows)},
                tags=["MM-2"],
            )
        )
    formulas = doc.structure.get("formulas") or []
    broken = [f for f in formulas if "#REF!" in str(f.get("formula", ""))]
    if broken:
        out.append(
            _finding(
                doc,
                FindingType.DELETED_TEXT_RECOVERABLE,
                Severity.MEDIUM,
                f"삭제된 영역을 참조하는 수식 {len(broken)}건이 있다",
                "#REF! 오류는 원본 데이터가 삭제되었음을 시사한다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(f"{f['sheet']}!{f['cell']}: {f['formula']}" for f in broken)[:2000],
                tags=["MM-2"],
            )
        )
    return out


def _scan_image(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    if doc.structure.get("gps"):
        out.append(
            _finding(
                doc,
                FindingType.GEOLOCATION_METADATA_LEAK,
                Severity.HIGH,
                "이미지에 GPS 위치정보가 포함되어 있다",
                "촬영 위치가 노출된다. 군사보안·개인정보 측면의 위험이 있어 발신 전 제거를 검토해야 한다.",
                level=ForensicLevel.SUSPICIOUS,
                sealed=str(doc.structure["gps"])[:1000],
                tags=["MM-2", "OUTBOUND_RISK"],
            )
        )
    exif = doc.structure.get("exif") or {}
    device = {k: v for k, v in exif.items() if k in ("Make", "Model", "Software", "DateTime", "DateTimeOriginal")}
    if device:
        out.append(
            _finding(
                doc,
                FindingType.AUTHORSHIP_METADATA_LEAK,
                Severity.LOW,
                "이미지 EXIF에 기기·소프트웨어 정보가 남아 있다",
                f"{', '.join(f'{k}={v}' for k, v in device.items())[:300]}",
                level=ForensicLevel.NOTABLE,
                tags=["MM-2"],
            )
        )
        software = str(device.get("Software", ""))
        if re.search(r"(photoshop|gimp|paint|affinity|pixelmator)", software, re.I):
            out.append(
                _finding(
                    doc,
                    FindingType.METADATA_ANOMALY,
                    Severity.MEDIUM,
                    f"이미지 편집 소프트웨어 흔적이 있다: {software}",
                    "편집 소프트웨어 사용 사실만으로 위조를 단정하지 않는다. 객관적 관찰사실로만 제시한다.",
                    level=ForensicLevel.NOTABLE,
                    tags=["MM-2"],
                )
            )
    if doc.structure.get("has_embedded_thumbnail"):
        out.append(
            _finding(
                doc,
                FindingType.CROPPED_IMAGE_RESIDUE,
                Severity.MEDIUM,
                "내장 썸네일이 존재한다",
                "잘라내기 이전 상태가 썸네일에 남아 있을 수 있다. 본 이미지와 썸네일의 시각적 대조가 필요하다.",
                level=ForensicLevel.NOTABLE,
                tags=["MM-2"],
            )
        )
    return out


def _scan_common_metadata(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    authorship = {k: v for k, v in doc.metadata.items() if k in AUTHORSHIP_KEYS and str(v).strip()}
    if authorship:
        out.append(
            _finding(
                doc,
                FindingType.AUTHORSHIP_METADATA_LEAK,
                Severity.LOW,
                "문서요약정보에 작성자·회사 정보가 남아 있다",
                ", ".join(f"{k}={v}" for k, v in authorship.items())[:400],
                level=ForensicLevel.NOTABLE,
                features={"authorship_fields": len(authorship)},
                tags=["MM-2", "OUTBOUND_RISK"],
            )
        )
    paths: List[str] = []
    for value in list(doc.metadata.values()) + [doc.raw_layers.get("xml", "")]:
        paths.extend(PATH_RE.findall(str(value)))
    paths = sorted(set(paths))[:20]
    if paths:
        out.append(
            _finding(
                doc,
                FindingType.AUTHORSHIP_METADATA_LEAK,
                Severity.MEDIUM,
                f"저장 경로 정보 {len(paths)}건이 남아 있다",
                "파일 경로에 작성자 계정명·사무소 내부 구조가 노출될 수 있다.",
                level=ForensicLevel.NOTABLE,
                sealed="\n".join(paths),
                tags=["MM-2", "OUTBOUND_RISK"],
            )
        )
    return out
