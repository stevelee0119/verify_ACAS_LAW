"""제7-A.3장 MM-3 은닉 채널형.

zero-width canary, homoglyph 표식, 스테가노그래피 후보, QR·바코드, 파일명 규칙 등.
탐지된 URL·QR·인코딩 문자열은 표시와 안전 디코드 결과 보고에 한정하고
접속·실행·Tool 호출은 하지 않는다(부록 C 제9항).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

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
from packages.common.textutil import BIDI_CONTROLS, ZERO_WIDTH

ENGINE_NAME = "forensic_engine.mm3"

URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
TRACKING_PARAM_RE = re.compile(r"[?&](utm_[a-z]+|cid|uid|track|tid|ref)=", re.IGNORECASE)
FILENAME_MARKER_RE = re.compile(r"(copy|dist|배포|사본|v\d+|_[A-Za-z0-9]{8,}_)", re.IGNORECASE)

ZW_CANARY_MIN = 8


def _finding(
    doc: NormalizedDocument,
    type_: FindingType,
    severity: Severity,
    title: str,
    detail: str,
    *,
    level: ForensicLevel,
    sealed: str = "",
    features: Dict[str, Any] | None = None,
    tags: List[str] | None = None,
) -> Finding:
    feats = {"deterministic_rule": True, "forensic_signal": 1, **(features or {})}
    return Finding.create(
        type=type_,
        status=VerificationStatus.SUSPICIOUS,
        severity=severity,
        evidence_grade=EvidenceGrade.A,
        title=title,
        detail=detail,
        confidence=confidence_score(feats),
        confidence_features=feats,
        document_id=doc.document_id,
        engine=ENGINE_NAME,
        meta_message_type=MetaMessageType.MM3_COVERT_CHANNEL,
        forensic_level=level,
        sealed_excerpt=sealed or None,
        tags=(tags or []) + ["MM-3"],
        evidence=[
            Evidence.create(
                description=title,
                grade=EvidenceGrade.A,
                document_id=doc.document_id,
                excerpt=sealed[:200] or None,
                sealed=bool(sealed),
            )
        ],
    )


def scan_covert(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    text = doc.raw_layers.get("raw_text", "") or doc.full_text

    # 1) zero-width canary: 밀집도가 높으면 배포본 식별 표식 가능성
    zw_chars = [c for c in text if c in ZERO_WIDTH or c in BIDI_CONTROLS]
    if len(zw_chars) >= ZW_CANARY_MIN:
        counter = Counter(zw_chars)
        pattern_bits = "".join("1" if c in ("​", "‌") else "0" for c in zw_chars[:64])
        out.append(
            _finding(
                doc,
                FindingType.TRACKING_CANARY_DETECTED,
                Severity.MEDIUM,
                f"zero-width 문자 {len(zw_chars)}개가 규칙적으로 삽입되어 있다",
                "배포본 식별용 canary 또는 유출경로 추적 표식일 수 있다. "
                "수신 문서인 경우 원문을 보존하고 임의로 제거하지 않는다. "
                "자체 문서를 재배포하는 경우 제거 여부를 사용자가 결정한다.",
                level=ForensicLevel.SUSPICIOUS,
                sealed=f"분포={dict(counter)} 비트열(앞 64)={pattern_bits}",
                features={"zero_width_count": len(zw_chars), "distinct_kinds": len(counter)},
                tags=["COVERT_CHANNEL"],
            )
        )

    # 2) 문서 fingerprint 후보: 동일 문서 내 자간·글꼴 크기의 미세 변형
    sizes: List[float] = []
    for block in doc.blocks:
        size = block.attributes.get("size")
        if isinstance(size, (int, float)) and size > 0:
            sizes.append(round(float(size), 2))
    if sizes:
        counter = Counter(sizes)
        rare = [s for s, n in counter.items() if n <= 2 and abs(s - counter.most_common(1)[0][0]) < 0.6]
        if len(rare) >= 3:
            out.append(
                _finding(
                    doc,
                    FindingType.DOCUMENT_FINGERPRINT_SUSPECTED,
                    Severity.LOW,
                    f"글꼴 크기의 미세 변형 {len(rare)}건이 관찰된다",
                    "배포본별 fingerprinting 가능성이 있는 관찰사실이다. 단독으로는 결론을 내리지 않는다.",
                    level=ForensicLevel.NOTABLE,
                    sealed=str(sorted(rare)[:20]),
                    features={"rare_font_sizes": len(rare)},
                )
            )

    # 3) URL / 추적 파라미터: 표시만 하고 접속하지 않는다
    urls = sorted(set(URL_RE.findall(text) + URL_RE.findall(doc.raw_layers.get("metadata_text", ""))))
    tracking = [u for u in urls if TRACKING_PARAM_RE.search(u)]
    hidden_urls = [
        b.text for b in doc.blocks if not b.visible and URL_RE.search(b.text)
    ]
    if tracking or hidden_urls:
        out.append(
            _finding(
                doc,
                FindingType.COVERT_CHANNEL_SUSPECTED,
                Severity.MEDIUM,
                f"추적 파라미터 URL {len(tracking)}건, 비표시 URL {len(hidden_urls)}건이 있다",
                "본 시스템은 탐지된 URL에 접속하거나 실행하지 않는다. 문자열과 안전 디코드 결과만 보고한다.",
                level=ForensicLevel.SUSPICIOUS if hidden_urls else ForensicLevel.NOTABLE,
                sealed="\n".join(tracking + hidden_urls)[:1500],
                features={"tracking_url_count": len(tracking), "hidden_url_count": len(hidden_urls)},
                tags=["NO_NETWORK_ACCESS"],
            )
        )

    # 4) 파일명 규칙
    if FILENAME_MARKER_RE.search(doc.filename):
        out.append(
            _finding(
                doc,
                FindingType.DOCUMENT_FINGERPRINT_SUSPECTED,
                Severity.INFO,
                f"파일명에 배포본 식별 가능 문자열이 있다: {doc.filename}",
                "파일명 규칙 자체가 배포 대상별 식별자로 쓰일 수 있다는 참고정보이다.",
                level=ForensicLevel.BENIGN,
            )
        )

    # 5) 스테가노그래피 후보 (LSB 편중)
    lsb = doc.structure.get("lsb_analysis")
    if lsb and lsb.get("suspected"):
        out.append(
            _finding(
                doc,
                FindingType.STEGANOGRAPHIC_PAYLOAD,
                Severity.MEDIUM,
                "이미지 LSB 분포가 통계적으로 편향되어 있다",
                f"LSB 1의 비율 {lsb.get('ones_ratio')}. 스테가노그래피 가능성이 있는 관찰사실이며 단독으로 확정하지 않는다.",
                level=ForensicLevel.NOTABLE,
                features={"lsb_ones_ratio": lsb.get("ones_ratio")},
            )
        )

    # 6) QR / 바코드 후보 (OCR 텍스트에 URL 형태가 있는 경우 표시만)
    if doc.structure.get("qr_candidates"):
        out.append(
            _finding(
                doc,
                FindingType.COVERT_CHANNEL_SUSPECTED,
                Severity.MEDIUM,
                f"QR·바코드 후보 {len(doc.structure['qr_candidates'])}건이 있다",
                "코드 내용은 디코드 결과만 표시하며 접속·실행하지 않는다.",
                level=ForensicLevel.NOTABLE,
                sealed=str(doc.structure["qr_candidates"])[:1000],
                tags=["NO_NETWORK_ACCESS"],
            )
        )
    return out
