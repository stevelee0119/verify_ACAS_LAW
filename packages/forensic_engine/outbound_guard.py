"""제7-A.7장 Outbound Guard (발신 전 자체검사).

동일 엔진을 자기 측 문서에 실행해 잔류 변경이력·코멘트·마스킹 실패·EXIF·템플릿 잔재를
점검하고 정제본을 생성한다. 원본은 Immutable Original로 보존하고(제15.1장)
정제본을 별도 버전으로 등록해 무엇을 제거했는지 감사추적에 남긴다.
"""
from __future__ import annotations

import io
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Finding, NormalizedDocument

from .ooxml_sanitize import sanitize_docx

OUTBOUND_RISK_TAG = "OUTBOUND_RISK"

REMOVABLE_TYPES = {
    FindingType.RESIDUAL_TRACKED_CHANGE,
    FindingType.RESIDUAL_COMMENT,
    FindingType.DELETED_TEXT_RECOVERABLE,
    FindingType.HIDDEN_TEXT_MISMATCH,
    FindingType.AUTHORSHIP_METADATA_LEAK,
    FindingType.GEOLOCATION_METADATA_LEAK,
    FindingType.TEMPLATE_RESIDUE,
    FindingType.REDACTION_FAILURE,
    FindingType.HIDDEN_SHEET_OR_ROW,
    FindingType.TRACKING_CANARY_DETECTED,
}


@dataclass
class OutboundReport:
    risk_items: List[Dict[str, Any]] = field(default_factory=list)
    sanitized_path: Optional[str] = None
    removed: Dict[str, int] = field(default_factory=dict)
    manual_actions: List[str] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_items": self.risk_items,
            "sanitized_path": self.sanitized_path,
            "removed": self.removed,
            "manual_actions": self.manual_actions,
            "finding_count": len(self.findings),
        }


def inspect_outbound(doc: NormalizedDocument, findings: List[Finding]) -> OutboundReport:
    """발신 전 위험 항목을 정리한다."""
    report = OutboundReport()
    for finding in findings:
        if finding.type in REMOVABLE_TYPES or OUTBOUND_RISK_TAG in finding.tags:
            report.risk_items.append(
                {
                    "finding_id": finding.finding_id,
                    "type": str(finding.type),
                    "severity": str(finding.severity),
                    "title": finding.title,
                    "auto_removable": finding.type in REMOVABLE_TYPES,
                }
            )
    if report.risk_items:
        features = {"deterministic_rule": True, "forensic_signal": len(report.risk_items)}
        report.findings.append(
            Finding.create(
                type=FindingType.OUTBOUND_LEAK_RISK,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.HIGH
                if any(i["severity"] in ("CRITICAL", "HIGH") for i in report.risk_items)
                else Severity.MEDIUM,
                evidence_grade=EvidenceGrade.A,
                title=f"발신 전 제거를 검토할 항목 {len(report.risk_items)}건이 있다",
                detail=(
                    "제출·송달 전에 잔류 변경이력·코멘트·마스킹 실패·EXIF·템플릿 잔재를 점검한 결과이다. "
                    "정제본을 생성해도 원본은 Immutable Original로 보존된다."
                ),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine="forensic_engine.outbound",
                forensic_level=ForensicLevel.SUSPICIOUS,
                tags=["OUTBOUND"],
            )
        )
    if any(i["type"] == str(FindingType.REDACTION_FAILURE) for i in report.risk_items):
        report.manual_actions.append(
            "마스킹 실패 항목은 자동 제거가 아니라 원문 재작성 또는 실제 삭제 후 재출력이 필요하다."
        )
    return report


def sanitize(doc: NormalizedDocument, source_path: str, output_path: str) -> OutboundReport:
    """정제본을 생성한다. 원본 파일은 절대 수정하지 않는다(부록 C 제8항)."""
    report = OutboundReport()
    src = Path(source_path)
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    suffix = src.suffix.lower()
    if suffix in (".docx", ".docm", ".dotx"):
        removed = sanitize_docx(src, dst)
        report.removed = removed
        report.sanitized_path = str(dst)
    elif suffix in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"):
        report.removed = _sanitize_image(src, dst)
        report.sanitized_path = str(dst)
    else:
        shutil.copyfile(src, dst)
        report.sanitized_path = str(dst)
        report.manual_actions.append(
            f"{suffix or '해당'} 형식은 자동 정제를 지원하지 않는다. 원본을 그대로 복사했으므로 수동 확인이 필요하다."
        )
    return report


def _sanitize_image(src: Path, dst: Path) -> Dict[str, int]:
    """EXIF·GPS를 제거한 이미지를 생성한다."""
    from PIL import Image

    removed = {"exif": 0, "gps": 0}
    with Image.open(src) as im:
        had_exif = bool(im.getexif())
        data = list(im.getdata())
        clean = Image.new(im.mode, im.size)
        clean.putdata(data)
        clean.save(dst)
        if had_exif:
            removed["exif"] = 1
            removed["gps"] = 1
    return removed
