"""제7-A.4장 MM-4 함축형 신호.

해석의 영역이므로 Finding이 아닌 참고 신호(Advisory Signal)로만 제시하고
다음 가드레일을 코드로 강제한다.
- Severity 상한 MEDIUM, Evidence Grade D, Verification Status UNVERIFIED 고정
- 근거 span이 없으면 신호를 생성하지 않는다
- 고의·악의·허위 등 주관적 요소를 단정하는 표현을 생성하지 않는다
- 보고서 본문이 아닌 Advisory Signals 섹션에 배치한다(advisory_only=True)
- 신호 유형별 사용자 비활성화 지원
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    Severity,
    VerificationStatus,
    severity_cap,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.common.textutil import sentences

ENGINE_NAME = "forensic_engine.mm4"

MAX_SEVERITY = Severity.MEDIUM
FIXED_GRADE = EvidenceGrade.D
FIXED_STATUS = VerificationStatus.UNVERIFIED

# 책임 유보: 전문·추정 표현
HEDGING_RE = re.compile(
    r"(들었다|들은\s*바|전해\s*들|추정된다|추정되며|보이는\s*것\s*같|것으로\s*보인다|"
    r"라고\s*알고\s*있|기억나지\s*않|알\s*수\s*없|~로\s*생각된다|사료된다)"
)
# 위협·회유: 본안과 무관한 불이익 언급
COERCIVE_RE = re.compile(
    r"(형사\s*고소|고발\s*하겠|무고죄|명예훼손으로\s*고소|언론에\s*공개|인사\s*조치|"
    r"징계\s*요구|불이익을\s*받게\s*될|손해배상을\s*청구하겠)"
)
# 입증책임 전가
BURDEN_SHIFT_RE = re.compile(
    r"(부존재[를을]?\s*증명|없다는\s*점[을를]\s*(입증|증명)|입증하지\s*못하면|"
    r"반증하지\s*못하는\s*한|스스로\s*증명하여야)"
)
# 절차 지연
DELAY_RE = re.compile(r"(기일\s*(변경|연기)\s*(신청|요청)|기간\s*연장\s*(신청|요청)|속행\s*신청)")
# 자백 근접: 부인하면서 구성요건 사실을 전제로 서술
ADMISSION_RE = re.compile(
    r"(부인한다|사실이\s*아니다|그러한\s*사실이\s*없다)[^.]{0,80}"
    r"(당시|그\s*자리에서|지급하였|송금하였|전달하였|작성하였|서명하였)"
)

SIGNAL_SPECS = [
    ("LIABILITY_HEDGING_SIGNAL", FindingType.LIABILITY_HEDGING_SIGNAL, HEDGING_RE,
     "사실주장을 전문·추정 표현으로 대체한 문장이 관찰된다"),
    ("COERCIVE_LANGUAGE_SIGNAL", FindingType.COERCIVE_LANGUAGE_SIGNAL, COERCIVE_RE,
     "본안과 직접 관련이 낮은 불이익 언급이 관찰된다"),
    ("IMPLICIT_ADMISSION_SIGNAL", FindingType.IMPLICIT_ADMISSION_SIGNAL, ADMISSION_RE,
     "부인 문장과 같은 문장에서 구성요건 관련 사실을 전제로 한 서술이 관찰된다"),
]

DEFAULT_ENABLED: Set[str] = {
    "LIABILITY_HEDGING_SIGNAL",
    "COERCIVE_LANGUAGE_SIGNAL",
    "IMPLICIT_ADMISSION_SIGNAL",
    "ISSUE_EVASION_SIGNAL",
    "SELECTIVE_QUOTATION_SIGNAL",
}

HEDGING_RATIO_THRESHOLD = 0.15
MIN_SENTENCES = 8


@dataclass
class AdvisoryContext:
    """MM-4 산출에 필요한 외부 입력."""

    requested_issues: Optional[List[str]] = None
    """상대방이 요구한 쟁점 목록 (제11장 Claim Graph에서 산출)."""
    truncated_quotations: Optional[List[Dict[str, Any]]] = None
    """제9장 quote_match 결과에서 확인된 인용 절단 목록."""
    enabled_signals: Optional[Set[str]] = None


def _advisory_finding(
    doc: NormalizedDocument,
    type_: FindingType,
    title: str,
    detail: str,
    *,
    block_id: Optional[str],
    page: Optional[int],
    span: Optional[tuple],
    excerpt: str,
    features: Dict[str, Any],
    severity: Severity = Severity.LOW,
) -> Finding:
    feats = {"heuristic_only": True, "llm_semantic_signal": 1, **features}
    return Finding.create(
        type=type_,
        status=FIXED_STATUS,
        severity=severity_cap(severity, MAX_SEVERITY),
        evidence_grade=FIXED_GRADE,
        title=title,
        detail=detail + " 본 신호는 참고용 관찰사실이며 고의·허위·위법 여부에 관한 판단이 아니다.",
        confidence=confidence_score(feats),
        confidence_features=feats,
        document_id=doc.document_id,
        block_id=block_id,
        page=page,
        span=span,
        engine=ENGINE_NAME,
        meta_message_type=MetaMessageType.MM4_IMPLICIT,
        forensic_level=ForensicLevel.NOTABLE,
        advisory_only=True,
        tags=["MM-4", "ADVISORY"],
        evidence=[
            Evidence.create(
                description="근거 문장",
                grade=FIXED_GRADE,
                document_id=doc.document_id,
                block_id=block_id,
                page=page,
                span=span,
                excerpt=excerpt[:300],
            )
        ],
    )


def scan_advisory(doc: NormalizedDocument, context: Optional[AdvisoryContext] = None) -> List[Finding]:
    context = context or AdvisoryContext()
    enabled = context.enabled_signals if context.enabled_signals is not None else DEFAULT_ENABLED
    out: List[Finding] = []

    # 1) 패턴 기반 신호 — 반드시 근거 span과 함께 생성한다
    for name, finding_type, regex, description in SIGNAL_SPECS:
        if name not in enabled:
            continue
        hits = []
        for block in doc.body_blocks():
            for m in regex.finditer(block.text):
                hits.append((block, m))
        if not hits:
            continue
        # 책임 유보는 비율 기준을 함께 적용해 단발성 표현을 배제한다
        if finding_type == FindingType.LIABILITY_HEDGING_SIGNAL:
            all_sentences = sentences(doc.visible_text)
            if len(all_sentences) < MIN_SENTENCES:
                continue
            ratio = len(hits) / max(1, len(all_sentences))
            if ratio < HEDGING_RATIO_THRESHOLD:
                continue
            features = {"hedging_ratio": round(ratio, 3), "hit_count": len(hits),
                        "sentence_count": len(all_sentences)}
            title = f"전문·추정 표현 비율이 {ratio:.0%}로 관찰된다"
        else:
            features = {"hit_count": len(hits)}
            title = description

        block, m = hits[0]
        out.append(
            _advisory_finding(
                doc,
                finding_type,
                title,
                f"{description}. 총 {len(hits)}건.",
                block_id=block.block_id,
                page=block.page,
                span=(m.start(), m.end()),
                excerpt=block.text,
                features=features,
            )
        )

    # 2) 절차 지연은 반복 패턴일 때만
    delay_hits = [(b, m) for b in doc.body_blocks() for m in DELAY_RE.finditer(b.text)]
    if len(delay_hits) >= 2 and "ISSUE_EVASION_SIGNAL" in enabled:
        block, m = delay_hits[0]
        out.append(
            _advisory_finding(
                doc,
                FindingType.ISSUE_EVASION_SIGNAL,
                f"기일 변경·기간 연장 요청이 {len(delay_hits)}회 반복된다",
                "절차 지연으로 볼 수 있는 반복 요청이 관찰된다.",
                block_id=block.block_id,
                page=block.page,
                span=(m.start(), m.end()),
                excerpt=block.text,
                features={"delay_request_count": len(delay_hits)},
            )
        )

    # 3) 입증책임 전가
    burden_hits = [(b, m) for b in doc.body_blocks() for m in BURDEN_SHIFT_RE.finditer(b.text)]
    if burden_hits and "LIABILITY_HEDGING_SIGNAL" in enabled:
        block, m = burden_hits[0]
        out.append(
            _advisory_finding(
                doc,
                FindingType.LIABILITY_HEDGING_SIGNAL,
                "상대방에게 부존재 증명을 요구하는 서술 구조가 관찰된다",
                f"총 {len(burden_hits)}건.",
                block_id=block.block_id,
                page=block.page,
                span=(m.start(), m.end()),
                excerpt=block.text,
                features={"burden_shift_count": len(burden_hits)},
            )
        )

    # 4) 쟁점 회피 — Claim Graph가 제공한 요구 쟁점 목록 대비 응답 누락
    if context.requested_issues and "ISSUE_EVASION_SIGNAL" in enabled:
        body = doc.visible_text
        missing = [issue for issue in context.requested_issues if issue and issue not in body]
        if missing and doc.body_blocks():
            block = doc.body_blocks()[0]
            out.append(
                _advisory_finding(
                    doc,
                    FindingType.ISSUE_EVASION_SIGNAL,
                    f"요구된 쟁점 {len(missing)}건에 대응하는 서술이 확인되지 않는다",
                    f"미대응 쟁점: {', '.join(missing[:5])}.",
                    block_id=block.block_id,
                    page=block.page,
                    span=(0, min(len(block.text), 50)),
                    excerpt=block.text,
                    features={"missing_issue_count": len(missing),
                              "requested_issue_count": len(context.requested_issues)},
                    severity=Severity.MEDIUM,
                )
            )

    # 5) 인용 절단 — 제9장 quote_match 결과와 결합
    if context.truncated_quotations and "SELECTIVE_QUOTATION_SIGNAL" in enabled:
        for item in context.truncated_quotations[:5]:
            block_id = item.get("block_id")
            block = doc.block_by_id(block_id) if block_id else None
            if block is None:
                continue  # 근거 span이 없으면 신호를 생성하지 않는다
            out.append(
                _advisory_finding(
                    doc,
                    FindingType.SELECTIVE_QUOTATION_SIGNAL,
                    "판시사항 중 일부 문장이 생략된 인용이 관찰된다",
                    f"대상: {item.get('citation', '')}. 생략 구간 길이 {item.get('omitted_chars', 0)}자.",
                    block_id=block.block_id,
                    page=block.page,
                    span=item.get("span") or (0, min(len(block.text), 50)),
                    excerpt=block.text,
                    features={"omitted_chars": item.get("omitted_chars", 0)},
                    severity=Severity.MEDIUM,
                )
            )
    return out
