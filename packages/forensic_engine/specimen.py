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

from packages.common.anonymization import is_masked_digits
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
# 아래 패턴은 모두 "공백을 제거한 텍스트"에 적용한다.
# 한국어 OCR은 글자 사이에 공백을 넣는다("가 상 의 예시 문 서"). 원문 그대로
# 대조하면 실제 문서에서 6개 중 4개를 놓친다. 공백을 지우고 보면 모두 잡힌다.
SPECIMEN_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"가상의?(예시|샘플|견본)?(문서|서식|계약서|인물)"), "가상 문서 고지"),
    (re.compile(r"실존(인물|법인|부동산)[^.\n]{0,20}(무관|아닙니다|아니)"), "실존 무관 고지"),
    (re.compile(r"법적효력(이)?(없|미발생)"), "법적 효력 없음 고지"),
    (re.compile(r"(예시|연습|실습|교육|시연|데모)용?(서식|문서|자료|목적)"), "연습용 서식 고지"),
    (re.compile(r"(샘플|견본|SAMPLE|SPECIMEN|DUMMY)(문서|계약서)", re.IGNORECASE), "견본 표기"),
    (re.compile(r"실제계약시에는"), "실제 계약 아님 안내"),
]

# 항목 옆에 붙는 "(예시)" 표기. 본문 고지와 달리 개별 값에 붙는다.
INLINE_SPECIMEN_RE = re.compile(r"\((예시|샘플|견본|가상|example|sample)\)", re.IGNORECASE)

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


DOCUMENT_LABELS = {"COMPLAINT": "소장", "BRIEF": "준비서면", "ANSWER": "답변서", "APPEAL": "항소·상고이유서",
                   "OPINION_LETTER": "의견서", "CRIMINAL_COMPLAINT": "고소·고발장", "CONTRACT": "계약서",
                   "REPORT": "보고서"}


def _document_label(doc: NormalizedDocument) -> str:
    """보고서 문구에 쓸 문서 종류. 종류를 모르면 '제출·체결 문서'."""
    from packages.claim_engine.classification import document_kind
    # 제목 줄로 판단한다. 바닥글·고지문의 '테스트용' 표기가 문서 종류를 가리지 않게 한다.
    for block in doc.prose_blocks()[:3]:
        label = DOCUMENT_LABELS.get(document_kind([block.text]))
        if label:
            return label
    return "제출·체결 문서"


def _with_ro(noun: str) -> str:
    """'…로/으로': 받침이 있으면(ㄹ 제외) '으로'."""
    last = noun[-1] if noun else ""
    if "가" <= last <= "힣":
        final = (ord(last) - 0xAC00) % 28
        return noun + ("으로" if final not in (0, 8) else "로")
    return noun + "로"


def is_placeholder_number(digits: str) -> bool:
    body = re.sub(r"\D", "", digits or "")
    return _is_sequential(body) or _is_repeated(body)


_WS_RE = re.compile(r"\s+")


def compact(text: str) -> str:
    """공백을 모두 지운다. OCR이 넣은 글자 사이 공백을 무력화한다."""
    return _WS_RE.sub("", text or "")


def _search_units(doc: NormalizedDocument) -> List[Tuple[str, Any]]:
    """검사 단위. 줄 단위와 페이지 단위를 함께 제공한다.

    줄 단위만 보면 두 줄에 걸친 고지 문구를 놓치고, 페이지 단위만 보면
    어느 줄에서 나왔는지 잃는다. 둘 다 훑고 중복은 매치 문자열로 제거한다.
    """
    units: List[Tuple[str, Any]] = []
    pages: Dict[Any, List[Any]] = {}
    # 개별 단위는 머리글·바닥글도 포함해 검사한다.
    for block in doc.body_blocks(include_running_heads=True):
        units.append((compact(block.text), block))
        if getattr(block, "block_type", "") != "running_head":
            pages.setdefault(block.page, []).append(block)
    # 두 줄 이상 걸친 본문 고지는 머리글·바닥글을 뺀 본문 블록끼리만 합쳐서 검사한다.
    for blocks in pages.values():
        if len(blocks) > 1:
            units.append((compact("".join(b.text for b in blocks)), blocks[0]))
    return units


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
    units = _search_units(doc)
    if not units:
        return findings

    # --- 1) 예시 고지 문구 ------------------------------------------------
    declared: Dict[Tuple[str, str], Any] = {}
    testbed_watermark_only = True
    for text, block in units:
        for pattern, label in SPECIMEN_PATTERNS:
            match = pattern.search(text)
            if match:
                declared.setdefault((label, match.group(0)), block)
                is_running = getattr(block, "block_type", "") == "running_head" or getattr(block, "source_layer", "") in ("running_head", "header", "footer")
                is_test_watermark = ("검증프로그램" in text or "테스트용" in text or "시험용" in text or "평가용" in text)
                if not (is_running or is_test_watermark):
                    testbed_watermark_only = False

    if declared:
        labels = sorted({label for label, _ in declared})
        (first_label, first_excerpt), first_block = next(iter(declared.items()))
        features = {
            "deterministic_rule": True,
            "forensic_signal": len(declared),
            "declared_labels": labels,
            "testbed_watermark_only": testbed_watermark_only,
        }
        severity = Severity.INFO if testbed_watermark_only else Severity.HIGH
        findings.append(
            _finding(
                finding_type=FindingType.SPECIMEN_DOCUMENT_DECLARED,
                severity=severity,
                grade=EvidenceGrade.A if not testbed_watermark_only else EvidenceGrade.C,
                title=("테스트 환경 워터마크 표기 확인" if testbed_watermark_only
                       else "문서 스스로 예시·연습용임을 밝히고 있다"),
                detail=(
                    f"검증 및 시험 환경 헤더 표기가 확인된다 ({', '.join(labels)})."
                    if testbed_watermark_only else
                    f"{', '.join(labels)} 표기가 확인된다. "
                    "문서 내부의 명시적 고지이므로 추정이 아니라 기재사실이다. "
                    f"이 문서를 실제 {_with_ro(_document_label(doc))} 취급해서는 안 된다."
                ),
                doc=doc,
                features=features,
                excerpt=first_excerpt,
                block_id=first_block.block_id,
                page=first_block.page,
                level=ForensicLevel.NOTABLE if testbed_watermark_only else ForensicLevel.CRITICAL,
            )
        )
        if testbed_watermark_only:
            findings[-1].advisory_only = True

    # --- 2) 주민등록번호 검증부호 ----------------------------------------
    invalid_rrns: Dict[str, Any] = {}
    checked: set = set()
    for text, block in units:
        for match in RRN_RE.finditer(text):
            rrn = f"{match.group(1)}-{match.group(2)}"
            valid = rrn_is_valid(rrn)
            if valid is None:
                continue
            checked.add(rrn)
            if not valid:
                invalid_rrns.setdefault(rrn, block)
    if invalid_rrns:
        rrn, block = next(iter(invalid_rrns.items()))
        # 원문 전체를 증거에 남기지 않는다. 앞 6자리와 성별코드까지만 남긴다.
        masked = f"{rrn[:6]}-{rrn[7]}{'*' * 6}"
        features = {
            "deterministic_rule": True,
            "forensic_signal": len(invalid_rrns),
            "checked_count": len(checked),
            "invalid_count": len(invalid_rrns),
        }
        findings.append(
            _finding(
                finding_type=FindingType.INVALID_IDENTIFIER,
                severity=Severity.HIGH,
                grade=EvidenceGrade.A,
                title=f"실재할 수 없는 주민등록번호가 기재되어 있다 ({len(invalid_rrns)}건)",
                detail=(
                    f"확인한 {len(checked)}건 중 {len(invalid_rrns)}건이 검증부호 규칙을 만족하지 않는다. "
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
    placeholders: Dict[Tuple[str, str], Any] = {}
    for text, block in units:
        for match in PHONE_RE.finditer(text):
            tail = match.group(2) + match.group(3)
            # 010-0000-0000은 비식별 처리한 번호다. 예시·자리표시 번호로 보지 않는다.
            if is_placeholder_number(tail) and not is_masked_digits(tail):
                placeholders.setdefault(("전화번호", match.group(0)), block)
        for match in INLINE_SPECIMEN_RE.finditer(text):
            placeholders.setdefault(("항목별 예시 표기", match.group(0)), block)
    if placeholders:
        (kind, excerpt), block = next(iter(placeholders.items()))
        kinds = sorted({k for k, _ in placeholders})
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
