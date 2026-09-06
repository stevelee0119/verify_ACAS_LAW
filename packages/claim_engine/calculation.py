"""제11.5장 숫자 검증.

손해액, 이자, 기간, 합계, 비율은 LLM이 아닌 Python Calculation Engine으로 검산한다.
문서의 합계와 세부 금액 합산값이 다르면 ARITHMETIC_MISMATCH를 Evidence Grade A로 생성한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "claim_engine.calculation"

AMOUNT_RE = re.compile(r"(?:금\s*)?(?P<num>\d[\d,]*)\s*(?P<unit>억|천만|백만|만|천)?\s*원")
TOTAL_LABEL_RE = re.compile(r"(합계|총액|총\s*금액|계|소계|합\s*계|총\s*계)")
ITEM_LABEL_RE = re.compile(r"(항목|내역|세부|명세)")
PERCENT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*%")

UNIT_MULTIPLIER = {None: 1, "천": 1_000, "만": 10_000, "백만": 1_000_000, "천만": 10_000_000, "억": 100_000_000}

TOLERANCE = Decimal("0.01")


@dataclass
class Amount:
    value: Decimal
    raw: str
    start: int
    end: int
    block_id: Optional[str] = None
    page: Optional[int] = None


@dataclass
class CalculationCheck:
    kind: str
    stated: Decimal
    computed: Decimal
    items: List[Amount] = field(default_factory=list)
    block_id: Optional[str] = None
    page: Optional[int] = None
    detail: str = ""

    @property
    def matches(self) -> bool:
        return abs(self.stated - self.computed) <= TOLERANCE


def parse_amounts(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> List[Amount]:
    out: List[Amount] = []
    for m in AMOUNT_RE.finditer(text):
        try:
            base = Decimal(m.group("num").replace(",", ""))
        except InvalidOperation:  # pragma: no cover
            continue
        value = base * UNIT_MULTIPLIER.get(m.group("unit"), 1)
        out.append(Amount(value, m.group(0), m.start(), m.end(), block_id, page))
    return out


def check_sum(items: List[Amount], stated: Amount) -> CalculationCheck:
    computed = sum((i.value for i in items), Decimal(0))
    return CalculationCheck(
        kind="SUM",
        stated=stated.value,
        computed=computed,
        items=items,
        block_id=stated.block_id,
        page=stated.page,
        detail=f"세부 {len(items)}건 합산 {computed:,} / 문서 기재 {stated.value:,}",
    )


def simple_interest(principal: Decimal, annual_rate_percent: Decimal, days: int) -> Decimal:
    """연 이율 단리. 민사 실무의 연 단위 일할 계산."""
    return (principal * annual_rate_percent / Decimal(100) * Decimal(days) / Decimal(365)).quantize(Decimal("1"))


def day_count(start: date, end: date, *, inclusive: bool = False) -> int:
    delta = (end - start).days
    return delta + 1 if inclusive else delta


class CalculationEngine:
    """문서에서 합계 진술을 찾아 세부 금액과 검산한다."""

    def verify_document(self, doc: NormalizedDocument) -> List[Finding]:
        findings: List[Finding] = []
        for block in doc.body_blocks():
            if block.block_type == "table":
                continue  # 표는 _verify_table_totals에서 행 단위로 검산한다
            findings.extend(self._verify_block(doc, block))
        findings.extend(self._verify_table_totals(doc))
        return findings

    def _verify_block(self, doc: NormalizedDocument, block) -> List[Finding]:
        text = block.text
        if not TOTAL_LABEL_RE.search(text):
            return []
        amounts = parse_amounts(text, block_id=block.block_id, page=block.page)
        if len(amounts) < 3:
            return []
        total_match = TOTAL_LABEL_RE.search(text)
        assert total_match is not None
        after = [a for a in amounts if a.start >= total_match.start()]
        before = [a for a in amounts if a.start < total_match.start()]
        if not after or len(before) < 2:
            return []
        stated = after[0]
        check = check_sum(before, stated)
        if check.matches:
            return []
        return [self._mismatch_finding(doc, check, block.block_id, block.page, text)]

    def _verify_table_totals(self, doc: NormalizedDocument) -> List[Finding]:
        """표 블록에서 '합계' 행과 나머지 행의 금액을 대조한다."""
        findings: List[Finding] = []
        for block in doc.blocks:
            if block.block_type != "table" or not block.visible:
                continue
            rows = [r for r in block.text.splitlines() if r.strip()]
            if len(rows) < 3:
                continue
            total_rows = [r for r in rows if TOTAL_LABEL_RE.search(r)]
            item_rows = [r for r in rows if not TOTAL_LABEL_RE.search(r)]
            if not total_rows:
                continue
            total_amounts = parse_amounts(total_rows[-1], block_id=block.block_id, page=block.page)
            if not total_amounts:
                continue
            items: List[Amount] = []
            for row in item_rows:
                row_amounts = parse_amounts(row, block_id=block.block_id, page=block.page)
                if row_amounts:
                    items.append(row_amounts[-1])
            if len(items) < 2:
                continue
            check = check_sum(items, total_amounts[-1])
            if not check.matches:
                findings.append(self._mismatch_finding(doc, check, block.block_id, block.page, block.text))
        return findings

    @staticmethod
    def _mismatch_finding(doc: NormalizedDocument, check: CalculationCheck, block_id, page, excerpt: str) -> Finding:
        difference = check.stated - check.computed
        features = {
            "arithmetic_proof": True,
            "deterministic_rule": True,
            "stated": str(check.stated),
            "computed": str(check.computed),
            "difference": str(difference),
            "item_count": len(check.items),
        }
        return Finding.create(
            type=FindingType.ARITHMETIC_MISMATCH,
            status=VerificationStatus.CONTRADICTED,
            severity=Severity.HIGH if abs(difference) > check.computed * Decimal("0.01") else Severity.MEDIUM,
            evidence_grade=EvidenceGrade.A,
            title=f"합계가 세부 금액 합산값과 다르다 (차이 {difference:,}원)",
            detail=(
                f"{check.detail}. 차액 {difference:,}원. "
                "Python 계산엔진으로 검산한 결정론적 결과이다."
            ),
            confidence=confidence_score(features),
            confidence_features=features,
            document_id=doc.document_id,
            block_id=block_id,
            page=page,
            engine=ENGINE_NAME,
            tags=["CALCULATION"],
            evidence=[
                Evidence.create(
                    description="검산 대상 구간",
                    grade=EvidenceGrade.A,
                    document_id=doc.document_id,
                    block_id=block_id,
                    page=page,
                    excerpt=excerpt[:400],
                ),
                Evidence.create(
                    description="세부 금액",
                    grade=EvidenceGrade.A,
                    excerpt=", ".join(f"{a.raw}({a.value:,})" for a in check.items[:10]),
                ),
            ],
        )
