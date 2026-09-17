"""가상·예시 문서 식별 (제11장 문서 진정성).

AI가 생성한 연습용 계약서·소장 등은 실제 문서와 형식이 거의 같아 육안으로
구별하기 어렵다. 그러나 다음 세 가지는 문서 자체에서 결정론적으로 확인된다.

1. 문서가 스스로 밝힌 예시 고지 문구
2. 검증규칙(체크섬)을 위반하는 식별번호 — 특히 주민등록번호
3. 순차·반복 숫자로 만든 자리표시자 식별번호

셋 모두 "AI가 작성했다"는 판단이 아니다. 문체 통계와 달리 객관적 관찰사실이며,
"이 문서에 실재하지 않는 식별번호가 쓰였다"는 것까지만 말한다. 누가 왜 만들었는지는
이용자가 판단한다(부록 C 제5항).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "forensic_engine.specimen"

# ---------------------------------------------------------------------------
# 1) 예시·연습용 고지 문구
#
# 문서가 스스로 "실제가 아니다"라고 적어 둔 경우이다. 가장 강한 신호이면서
# 동시에 가장 놓치기 쉽다. 사람은 본문만 읽고 머리말·꼬리말을 넘기기 때문이다.
# ---------------------------------------------------------------------------
SPECIMEN_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"가상의?\s*(예시|샘플|견본)?\s*(문서|서식|계약서|인물)"), "가상 문서 고지"),
    (re.compile(r"실존\s*(인물|법인|부동산)[^.\n]{0,20}(무관|아닙니다|아니)"), "실존 무관 고지"),
    (re.compile(r"법적\s*효력(이)?\s*(없|미발생)"), "법적 효력 없음 고지"),
    (re.compile(r"(예시|연습|실습|교육|시연|데모)\s*용?\s*(서식|문서|자료|목적)"), "연습용 서식 고지"),
    (re.compile(r"(샘플|견본|SAMPLE|SPECIMEN|DUMMY|TEMPLATE)\s*(문서|계약서)?", re.IGNORECASE), "견본 표기"),
    (re.compile(r"실제\s*계약\s*시에는"), "실제 계약 아님 안내"),
]

# 항목 옆에 붙는 "(예시)" 표기. 본문 고지와 달리 개별 값에 붙는다.
INLINE_SPECIMEN_RE = re.compile(r"\(\s*(예시|샘플|견본|가상|example|sample)\s*\)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# 2) 주민등록번호 검증부호
#
# 주민등록번호 13자리의 마지막 자리는 앞 12자리로부터 계산되는 검증부호이다.
# 이 규칙을 만족하지 못하는 번호는 실재할 수 없다. 창작된 번호는 거의 예외 없이
# 여기서 걸린다.
# ---------------------------------------------------------------------------
RRN_RE = re.compile(r"(?<!\d)(\d{6})\s*[-–]\s*([1-8]\d{6})(?!\d)")
RRN_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]


def rrn_check_digit(digits: str) -> Optional[int]:
    """앞 12자리로부터 검증부호를 계산한다."""
    body = re.sub(r"\D", "", digits or "")
    if len(body) < 12:
        return None
    total = sum(int(d) * w for d, w in zip(body[:12], RRN_WEIGHTS))
    return (11 - (total % 11)) % 10


def rrn_is_valid(rrn: str) -> Optional[bool]:
    """검증부호가 맞는지 본다. 자릿수가 모자라면 판단하지 않는다(None)."""
    body = re.sub(r"\D", "", rrn or "")
    if len(body) != 13:
        return None
    expected = rrn_check_digit(body)
    return expected is not None and expected == int(body[12])


# ---------------------------------------------------------------------------
# 3) 자리표시자 식별번호
#
# 1234567, 0000000, 2345-6789 처럼 순차·반복으로 만든 숫자이다.
# 실제 번호가 우연히 이런 형태일 수 있으므로 단독으로는 근거가 약하다.
# ---------------------------------------------------------------------------
PHONE_RE = re.compile(r"(?<!\d)(01[016789])[-\s]?(\d{3,4})[-\s]?(\d{4})(?!\d)")


def _is_sequential(digits: str) -> bool:
    """오름차순 또는 내림차순으로 연속된 숫자인지 본다."""
    if len(digits) < 4:
        return False
    deltas = {int(digits[i + 1]) - int(digits[i]) for i in range(len(digits) - 1)}
    return deltas in ({1}, {-1})


def _is_repeated(digits: str) -> bool:
    return len(digits) >= 4 and len(set(digits)) == 1


def is_placeholder_number(digits: str) -> bool:
    body = re.sub(r"\D", "", digits or "")
    return _is_sequential(body) or _is_repeated(body)


# ---------------------------------------------------------------------------
def _finding(
    *,
    finding_type: FindingType,
    severity: Severity,
    grade: EvidenceGrade,
    title: str,
    detail: str,
    doc: NormalizedDocument,
    features: Dict[str, Any],
    excerpt: Optional[str] = None,
    block_id: Optional[str] = None,
    page: Optional[int] = None,
    level: ForensicLevel = ForensicLevel.NOTABLE,
) -> Finding:
    return Finding.create(
        type=finding_type,
        status=VerificationStatus.SUSPICIOUS,
        severity=severity,
        evidence_grade=grade,
        title=title,
        detail=detail,
        confidence=confidence_score(features),
        confidence_features=features,
        document_id=doc.document_id,
        block_id=block_id,
        page=page,
        engine=ENGINE_NAME,
        forensic_level=level,
        tags=["FORENSIC", "SPECIMEN"],
        evidence=[
            Evidence.create(
                description=title,
                grade=grade,
                document_id=doc.document_id,
                block_id=block_id,
                page=page,
                excerpt=excerpt,
                supports=True,
            )
        ],
    )


def scan_specimen(doc: NormalizedDocument) -> List[Finding]:
    """문서가 가상·예시 문서인지 보여주는 객관적 신호를 모은다."""
    findings: List[Finding] = []
    blocks = doc.body_blocks()
    if not blocks:
        return findings

    # --- 1) 예시 고지 문구 ------------------------------------------------
    declared: List[Tuple[str, str, Any]] = []
    for block in blocks:
        for pattern, label in SPECIMEN_PATTERNS:
            match = pattern.search(block.text)
            if match:
                declared.append((label, match.group(0).strip(), block))
    if declared:
        labels = sorted({label for label, _, _ in declared})
        first_label, first_excerpt, first_block = declared[0]
        features = {
            "deterministic_rule": True,
            "forensic_signal": len(declared),
            "declared_labels": labels,
        }
        findings.append(
            _finding(
                finding_type=FindingType.SPECIMEN_DOCUMENT_DECLARED,
                severity=Severity.HIGH,
                grade=EvidenceGrade.A,
                title="문서 스스로 예시·연습용임을 밝히고 있다",
                detail=(
                    f"{', '.join(labels)} 표기가 {len(declared)}곳에서 확인된다. "
                    "문서 내부의 명시적 고지이므로 추정이 아니라 기재사실이다. "
                    "이 문서를 실제 계약서로 취급해서는 안 된다."
                ),
                doc=doc,
                features=features,
                excerpt=first_excerpt,
                block_id=first_block.block_id,
                page=first_block.page,
                level=ForensicLevel.CRITICAL,
            )
        )

    # --- 2) 주민등록번호 검증부호 ----------------------------------------
    invalid_rrns: List[Tuple[str, Any]] = []
    checked = 0
    for block in blocks:
        for match in RRN_RE.finditer(block.text):
            rrn = f"{match.group(1)}-{match.group(2)}"
            valid = rrn_is_valid(rrn)
            if valid is None:
                continue
            checked += 1
            if not valid:
                invalid_rrns.append((rrn, block))
    if invalid_rrns:
        rrn, block = invalid_rrns[0]
        # 원문 전체를 증거에 남기지 않는다. 앞 6자리와 성별코드까지만 남긴다.
        masked = f"{rrn[:6]}-{rrn[7]}{'*' * 6}"
        features = {
            "deterministic_rule": True,
            "forensic_signal": len(invalid_rrns),
            "checked_count": checked,
            "invalid_count": len(invalid_rrns),
        }
        findings.append(
            _finding(
                finding_type=FindingType.INVALID_IDENTIFIER,
                severity=Severity.HIGH,
                grade=EvidenceGrade.A,
                title=f"실재할 수 없는 주민등록번호가 기재되어 있다 ({len(invalid_rrns)}건)",
                detail=(
                    f"확인한 {checked}건 중 {len(invalid_rrns)}건이 검증부호 규칙을 만족하지 않는다. "
                    "주민등록번호 13번째 자리는 앞 12자리로부터 계산되는 검증부호이므로, "
                    "이를 만족하지 않는 번호는 발급될 수 없다. 창작된 번호이거나 오기이다. "
                    f"예: {masked}"
                ),
                doc=doc,
                features=features,
                excerpt=masked,
                block_id=block.block_id,
                page=block.page,
                level=ForensicLevel.SUSPICIOUS,
            )
        )

    # --- 3) 자리표시자 번호 ----------------------------------------------
    placeholders: List[Tuple[str, str, Any]] = []
    for block in blocks:
        for match in PHONE_RE.finditer(block.text):
            tail = match.group(2) + match.group(3)
            if is_placeholder_number(tail):
                placeholders.append(("전화번호", match.group(0), block))
        for match in INLINE_SPECIMEN_RE.finditer(block.text):
            placeholders.append(("항목별 예시 표기", match.group(0), block))
    if placeholders:
        kind, excerpt, block = placeholders[0]
        kinds = sorted({k for k, _, _ in placeholders})
        features = {
            "deterministic_rule": True,
            "forensic_signal": len(placeholders),
            "kinds": kinds,
        }
        findings.append(
            _finding(
                finding_type=FindingType.PLACEHOLDER_IDENTIFIER,
                severity=Severity.MEDIUM,
                grade=EvidenceGrade.C,
                title=f"자리표시자로 보이는 번호·표기가 있다 ({len(placeholders)}건)",
                detail=(
                    f"{', '.join(kinds)}에서 순차·반복 숫자 또는 예시 표기가 확인된다. "
                    "실제 번호가 우연히 이런 형태일 수 있으므로 단독으로는 근거가 약하다. "
                    f"예: {excerpt}"
                ),
                doc=doc,
                features=features,
                excerpt=excerpt,
                block_id=block.block_id,
                page=block.page,
            )
        )
    return findings
