"""제14장 Document Forensic Engine.

압축흔적·ELA·문체·이미지 휴리스틱만으로 위조를 단정하지 않는다(부록 C 제6항).
객관적 관찰 사실과 위험도를 제시하고 고의·위조 목적은 사용자 판단사항으로 남긴다.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "forensic_engine.document"

DISCLAIMER = "본 항목은 객관적 관찰사실이며 작성자의 고의나 위조 목적에 관한 판단이 아니다."

PDF_DATE_RE = re.compile(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?")


def _parse_pdf_date(value: str) -> Optional[datetime]:
    m = PDF_DATE_RE.search(str(value))
    if not m:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h, mi, s = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
    try:
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _finding(
    doc: NormalizedDocument,
    type_: FindingType,
    severity: Severity,
    title: str,
    detail: str,
    *,
    grade: EvidenceGrade = EvidenceGrade.C,
    level: ForensicLevel = ForensicLevel.NOTABLE,
    page: Optional[int] = None,
    features: Optional[Dict[str, Any]] = None,
) -> Finding:
    feats = {"deterministic_rule": True, "forensic_signal": 1, **(features or {})}
    return Finding.create(
        type=type_,
        status=VerificationStatus.SUSPICIOUS if severity.rank >= Severity.MEDIUM.rank else VerificationStatus.VERIFIED,
        severity=severity,
        evidence_grade=grade,
        title=title,
        detail=f"{detail} {DISCLAIMER}",
        confidence=confidence_score(feats),
        confidence_features=feats,
        document_id=doc.document_id,
        page=page,
        engine=ENGINE_NAME,
        forensic_level=level,
        tags=["FORENSIC"],
        evidence=[Evidence.create(description=title, grade=grade, document_id=doc.document_id, page=page)],
    )


def scan_document_forensics(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    out.extend(_metadata_timeline(doc))
    out.extend(_page_structure(doc))
    out.extend(_signature(doc))
    out.extend(_image_forensics(doc))
    return out


def _metadata_timeline(doc: NormalizedDocument) -> List[Finding]:
    """생성일이 수정일보다 뒤인 경우 등 메타데이터 시간 이상."""
    out: List[Finding] = []
    created = _parse_pdf_date(doc.metadata.get("CreationDate") or doc.metadata.get("created") or "")
    modified = _parse_pdf_date(doc.metadata.get("ModDate") or doc.metadata.get("modified") or "")
    if created and modified and created > modified:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.MEDIUM,
                "생성일시가 수정일시보다 뒤이다",
                f"생성 {created.isoformat()} / 수정 {modified.isoformat()}. 시스템 시각 오차나 도구 특성으로도 발생한다.",
                grade=EvidenceGrade.A,
                features={"created": created.isoformat(), "modified": modified.isoformat()},
            )
        )
    producer = str(doc.metadata.get("Producer") or "")
    creator = str(doc.metadata.get("Creator") or "")
    if producer and creator and producer.split()[0].lower() != creator.split()[0].lower():
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.INFO,
                "Creator와 Producer가 다른 도구로 기록되어 있다",
                f"Creator={creator[:80]} / Producer={producer[:80]}. 변환·재저장 과정에서 흔히 발생한다.",
                level=ForensicLevel.BENIGN,
            )
        )
    return out


def _page_structure(doc: NormalizedDocument) -> List[Finding]:
    """페이지별 크기·글꼴 구성의 이상치(제14.1장)."""
    out: List[Finding] = []
    if len(doc.pages) < 3:
        return out

    sizes = Counter((round(p.width), round(p.height)) for p in doc.pages if p.width and p.height)
    if len(sizes) > 1:
        dominant, dominant_count = sizes.most_common(1)[0]
        outliers = [p.page_number for p in doc.pages if (round(p.width), round(p.height)) != dominant]
        if outliers and len(outliers) <= max(2, len(doc.pages) // 4):
            out.append(
                _finding(
                    doc,
                    FindingType.PAGE_STRUCTURE_OUTLIER,
                    Severity.MEDIUM,
                    f"페이지 크기가 다른 면이 있다: {outliers}",
                    f"주 페이지 규격 {dominant} ({dominant_count}면)과 다른 면이 관찰된다. 면 교체·삽입 가능성을 확인해야 한다.",
                    grade=EvidenceGrade.A,
                    page=outliers[0],
                    features={"outlier_pages": outliers},
                )
            )

    font_sets = {p.page_number: set(p.attributes.get("fonts") or []) for p in doc.pages}
    all_fonts = Counter(f for fonts in font_sets.values() for f in fonts)
    if all_fonts:
        common = {f for f, n in all_fonts.items() if n >= max(2, len(doc.pages) // 2)}
        odd = [pno for pno, fonts in font_sets.items() if fonts and not (fonts & common)]
        if odd and len(odd) <= max(2, len(doc.pages) // 4):
            out.append(
                _finding(
                    doc,
                    FindingType.PAGE_STRUCTURE_OUTLIER,
                    Severity.MEDIUM,
                    f"본문과 다른 글꼴만 사용된 면이 있다: {odd}",
                    "해당 면이 별도로 작성·교체되었을 가능성을 확인해야 한다.",
                    grade=EvidenceGrade.A,
                    page=odd[0],
                    features={"outlier_pages": odd},
                )
            )
    return out


def _signature(doc: NormalizedDocument) -> List[Finding]:
    """전자서명 존재 및 서명 후 수정 흔적(제14.1장)."""
    out: List[Finding] = []
    if not doc.structure.get("has_signature_field"):
        return out
    incremental = int(doc.structure.get("incremental_updates") or 0)
    if incremental > 1:
        out.append(
            _finding(
                doc,
                FindingType.MODIFIED_AFTER_SIGNATURE,
                Severity.HIGH,
                f"서명 필드가 있는 문서에 incremental update가 {incremental}회 있다",
                "서명 이후 문서가 추가 저장되었을 가능성이 있다. 서명 검증 도구로 서명 범위 확인이 필요하다.",
                grade=EvidenceGrade.C,
                level=ForensicLevel.SUSPICIOUS,
                features={"incremental_updates": incremental},
            )
        )
    else:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.INFO,
                "전자서명 필드가 존재한다",
                "서명 값의 암호학적 검증은 별도 서명 검증 모듈에서 수행한다. 현재는 존재 사실만 기록한다.",
                grade=EvidenceGrade.A,
                level=ForensicLevel.BENIGN,
            )
        )
    return out


def _image_forensics(doc: NormalizedDocument) -> List[Finding]:
    """제14.3장 이미지. 휴리스틱만으로 위조를 단정하지 않는다."""
    out: List[Finding] = []
    if not doc.structure.get("image_size"):
        return out
    dpi = doc.structure.get("dpi")
    if dpi and isinstance(dpi, list) and dpi and float(dpi[0]) < 100:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.INFO,
                f"이미지 해상도가 낮다({dpi[0]}dpi)",
                "저해상도는 OCR 정확도와 세부 판독에 영향을 준다.",
                level=ForensicLevel.BENIGN,
            )
        )
    exif = doc.structure.get("exif") or {}
    if not exif:
        out.append(
            _finding(
                doc,
                FindingType.METADATA_ANOMALY,
                Severity.INFO,
                "이미지에 EXIF가 없다",
                "메신저·캡처·재저장 과정에서 흔히 제거된다. 그 자체로 조작 근거가 되지 않는다.",
                level=ForensicLevel.BENIGN,
            )
        )
    return out


def analyze_image_lsb(path: str) -> Dict[str, Any]:
    """LSB 편중 통계. 스테가노그래피 '후보' 판단에만 사용한다."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return {"suspected": False, "reason": "Pillow 미설치"}
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((256, 256))
            bits = [c & 1 for pixel in im.getdata() for c in pixel]
    except Exception as exc:  # pragma: no cover
        return {"suspected": False, "reason": str(exc)}
    if not bits:
        return {"suspected": False}
    ones = sum(bits) / len(bits)
    # 자연 이미지의 LSB는 0.5 근처. 0.5에 지나치게 수렴하면 페이로드 가능성 신호로만 본다.
    suspected = abs(ones - 0.5) < 0.002 and len(bits) > 20000
    return {"suspected": bool(suspected), "ones_ratio": round(ones, 5), "sample_bits": len(bits)}
