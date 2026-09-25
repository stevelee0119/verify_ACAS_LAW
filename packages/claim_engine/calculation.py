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

AMOUNT_RE = re.compile(r"(?<![\d.,])(?:금\s*)?(?P<sign>[-−+]?)\s*(?P<amount>(?:\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천)\s*)*\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천)?)\s*원")
AMOUNT_PART_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?")
TOTAL_LABEL_RE = re.compile(r"(합계|총액|총\s*금액|계|소계|합\s*계|총\s*계)")
ITEM_LABEL_RE = re.compile(r"(항목|내역|세부|명세)")
PERCENT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*%")

UNIT_MULTIPLIER = {None: 1, "천": 1_000, "만": 10_000, "백만": 1_000_000, "천만": 10_000_000, "억": 100_000_000}

TOLERANCE = Decimal("0.01")
MIN_LINE_ITEMS = 2  # 줄 단위 내역은 최소 2건이 모여야 합계를 검산한다


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
    rows: List[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return abs(self.stated - self.computed) <= TOLERANCE


def parse_amounts(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> List[Amount]:
    out: List[Amount] = []
    for m in AMOUNT_RE.finditer(text):
        try:
            parts = AMOUNT_PART_RE.findall(m.group("amount"))
            if any(not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", number) for number, _ in parts):
                continue
            # Do not silently parse the tail of an unsupported compound/currency.
            prefix = text[:m.start()]
            if re.search(r"(?:\d[\d,.]*\s*(?:조|경|백|십)|USD|EUR|JPY|[$€¥])\s*$", prefix, re.I):
                continue
            units = [UNIT_MULTIPLIER.get(unit or None, 1) for _, unit in parts]
            if any(a <= b for a, b in zip(units, units[1:])):
                continue
            value = sum((Decimal(number.replace(",", "")) * multiplier
                         for (number, _), multiplier in zip(parts, units)), Decimal(0))
            if m.group("sign") in ("-", "−"):
                value = -value
        except InvalidOperation:  # pragma: no cover
            continue
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


OPERATOR_RE = re.compile(r"\s*([+\-−×xX*＋])\s*")
MULTIPLIER_RE = re.compile(r"^\s*[×xX*]\s*(\d[\d,]*(?:\.\d+)?)\s*(?:개월|개|회|일|명|건|배)?")
AMOUNT_HEADER_RE = re.compile(r"(금액|합계|청구액|손해액|피해액|소계|청구\s*금액|총액|계)")


def evaluate_expression(text: str) -> Optional[Decimal]:
    """'3,100,000원 + 1,250,000원', '500,000원 × 3' 같은 산식의 값. 산식이 아니면 None."""
    amounts = parse_amounts(text)
    if not amounts:
        return None
    total = amounts[0].value
    cursor = amounts[0].end
    for amount in amounts[1:]:
        between = text[cursor:amount.start]
        if not between.strip() and amount.raw.lstrip()[:1] in "+-−":
            total += amount.value  # 금액 패턴이 부호를 금액에 붙여 읽었다(값에 부호가 이미 들어 있다)
            cursor = amount.end
            continue
        op = OPERATOR_RE.fullmatch(between)
        if not op:
            return None
        total = total - amount.value if op.group(1) in "-−" else total + amount.value
        cursor = amount.end
    tail = MULTIPLIER_RE.match(text[cursor:])
    if tail:
        total *= Decimal(tail.group(1).replace(",", ""))
        cursor += tail.end()
    elif len(amounts) == 1:
        return None
    return total


def row_final_amount(text: str) -> Tuple[Optional[Amount], Optional[CalculationCheck]]:
    """행의 최종 금액과(있으면) 그 행 산식의 검산 결과. '=' 뒤 금액을 최종 금액으로 본다."""
    amounts = parse_amounts(text)
    if not amounts:
        return None, None
    if "=" in text:
        left, _, right = text.rpartition("=")
        right_amounts = parse_amounts(right)
        value = evaluate_expression(left[left.rfind(":") + 1:] if ":" in left else left)
        if right_amounts:
            final = right_amounts[0]
            check = None
            if value is not None:
                check = CalculationCheck(kind="FORMULA", stated=final.value, computed=value,
                                         detail=f"산식 '{' '.join(text.split())}'의 계산값 {value:,} / 기재 {final.value:,}")
            return Amount(final.value, final.raw, len(left) + 1 + final.start, len(left) + 1 + final.end), check
    if len(amounts) == 1:
        return amounts[0], None
    return None, None


class CalculationEngine:
    """문서에서 합계 진술을 찾아 세부 금액과 검산한다."""

    def verify_document(self, doc: NormalizedDocument) -> List[Finding]:
        findings: List[Finding] = []
        seen_blocks: set = set()
        for block in doc.body_blocks():
            if block.block_type == "table":
                continue  # 표는 _verify_table_totals에서 행 단위로 검산한다
            found = self._verify_block(doc, block)
            if found:
                seen_blocks.add(block.block_id)
            findings.extend(found)
        findings.extend(self._verify_table_totals(doc))
        # 실무 서면은 항목이 줄마다 나뉘므로 줄 단위 내역-합계도 검산한다
        findings.extend(self._verify_line_items(doc, seen_blocks))
        return findings

    def _verify_line_items(self, doc: NormalizedDocument, seen_blocks: set) -> List[Finding]:
        """연속된 금액 줄 다음에 오는 합계 줄을 검산한다.

        같은 면에서 금액이 하나씩 적힌 줄이 연이어 나오고 그 뒤에 합계 줄이 오는
        서면 표준 형식을 대상으로 한다. 중간에 금액 없는 줄이 끼면 묶음을 끊어
        서로 무관한 금액을 합산하지 않는다.
        """
        findings: List[Finding] = []
        for page in doc.pages:
            blocks = [
                b for b in page.blocks
                if b.visible and b.block_type != "table" and b.text.strip()
                and b.source_layer in ("visible_text", "ocr_layer")
            ]
            run: List[Amount] = []
            for block in blocks:
                if block.block_id in seen_blocks:
                    run = []
                    continue
                amounts = parse_amounts(block.text, block_id=block.block_id, page=block.page)
                is_total = bool(TOTAL_LABEL_RE.search(block.text))

                if is_total and amounts and len(run) >= MIN_LINE_ITEMS:
                    check = check_sum([a for a, _ in run], amounts[-1])
                    check.rows = [label for _, label in run]
                    if not check.matches:
                        excerpt = "\n".join(
                            [label for _, label in run] + [f"{TOTAL_LABEL_RE.search(block.text).group(0)} {amounts[-1].raw}"]
                        )
                        findings.append(self._mismatch_finding(doc, check, block.block_id, block.page, excerpt))
                    run = []
                    continue

                # 행마다 최종 금액을 쓴다. 산식 행('a원 + b원 = c원')은 '=' 뒤 금액을 쓰고 산식은 따로 검산한다(J3).
                final, formula = row_final_amount(block.text) if amounts else (None, None)
                if formula is not None and not formula.matches:
                    findings.append(self._formula_finding(doc, formula, block.block_id, block.page, block.text))
                if is_total:
                    run = []
                elif final is not None:
                    final.block_id, final.page = block.block_id, block.page
                    run.append((final, " ".join(block.text.split())[:120]))
                else:
                    run = []  # 금액 없는 줄이나 최종 금액을 가를 수 없는 줄에서 묶음을 끊는다
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

    def _verify_cell_tables(self, doc: NormalizedDocument) -> Tuple[List[Finding], set]:
        """셀 단위 표: 금액 열(머리글)을 찾아 행마다 최종 금액을 쓰고, 산식 칸은 금액 칸과 대조한다(J3)."""
        findings: List[Finding] = []
        handled = set()
        for table in doc.structure.get("tables") or []:
            cells = [[str(c or "").strip() for c in row] for row in table.get("cells") or []]
            if len(cells) < 3:
                continue
            header = cells[0]
            amount_cols = [i for i, h in enumerate(header) if AMOUNT_HEADER_RE.search(h)]
            if not amount_cols:
                counts = [sum(1 for r in cells[1:] if i < len(r) and parse_amounts(r[i])) for i in range(len(header))]
                amount_cols = [max(range(len(header)), key=lambda i: (counts[i], i))] if any(counts) else []
            if not amount_cols:
                continue
            col = amount_cols[-1]
            # 소계 행은 바로 앞 소계(또는 표 머리) 이후 항목의 합이고, 마지막 합계 행은 최상위 항목(소계는 하나로)의 합이다.
            total_rows = [r for r in cells[1:] if r and TOTAL_LABEL_RE.fullmatch(r[0].replace(" ", ""))]
            grand = total_rows[-1] if total_rows else None
            top: List[Amount] = []
            segment: List[Tuple[Amount, str]] = []
            grand_checked = False
            for row in cells[1:]:
                if col >= len(row):
                    continue
                final, formula = row_final_amount(row[col])
                if final is None:
                    continue
                if any(row is r for r in total_rows):
                    rows_used = [label for _, label in segment]
                    items = top + [a for a, _ in segment] if row is grand else [a for a, _ in segment]
                    if row is grand:
                        rows_used = [f"{a.raw}" for a in top] + rows_used
                    if len(items) >= 2:
                        check = check_sum(items, final)
                        check.rows = rows_used
                        if not check.matches:
                            excerpt = "\n".join(" | ".join(r) for r in cells)
                            label = "합계" if row is grand else f"{row[0]}"
                            findings.append(self._mismatch_finding(doc, check, None, table.get("page"), excerpt,
                                                                   label=label))
                        grand_checked = grand_checked or row is grand
                    if row is not grand:
                        top.append(final)  # 소계는 위 단계에서 한 항목이 된다
                        segment = []
                    continue
                segment.append((final, f"{row[0]}: {final.raw}"))
                for index, cell in enumerate(row):
                    if index == col or not cell or not parse_amounts(cell):
                        continue
                    value = evaluate_expression(cell.split("=")[0]) if "=" in cell or OPERATOR_RE.search(cell) else None
                    if value is not None and abs(value - final.value) > TOLERANCE:
                        check = CalculationCheck(kind="FORMULA", stated=final.value, computed=value,
                                                 detail=f"'{row[0]}' 행 산식 '{cell}'의 계산값 {value:,} / 금액 칸 {final.value:,}")
                        findings.append(self._formula_finding(doc, check, None, table.get("page"), " | ".join(row)))
            if grand_checked:
                handled.add(table.get("table_ref"))
        return findings, handled

    def _verify_table_totals(self, doc: NormalizedDocument) -> List[Finding]:
        """표 블록에서 '합계' 행과 나머지 행의 금액을 대조한다."""
        findings, handled = self._verify_cell_tables(doc)
        for block in doc.blocks:
            if block.block_type != "table" or not block.visible:
                continue
            if block.attributes.get("table_ref") in handled:
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
    def _formula_finding(doc: NormalizedDocument, check: CalculationCheck, block_id, page, excerpt: str) -> Finding:
        difference = check.stated - check.computed
        features = {"arithmetic_proof": True, "deterministic_rule": True, "stated": str(check.stated),
                    "computed": str(check.computed), "difference": str(difference), "kind": "FORMULA",
                    "rule_id": "CALC.FORMULA"}
        return Finding.create(
            type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.CONTRADICTED, severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.A, title=f"산식의 계산 결과가 기재 금액과 다르다 (차이 {difference:,}원)",
            detail=f"{check.detail}. Python 계산엔진으로 검산한 결정론적 결과이다.",
            confidence=confidence_score(features), confidence_features=features, document_id=doc.document_id,
            block_id=block_id, page=page, engine=ENGINE_NAME, tags=["CALCULATION"],
            evidence=[Evidence.create(description="산식이 적힌 행", grade=EvidenceGrade.A, document_id=doc.document_id,
                                      block_id=block_id, page=page, excerpt=excerpt[:300])])

    @staticmethod
    def _mismatch_finding(doc: NormalizedDocument, check: CalculationCheck, block_id, page, excerpt: str,
                          label: str = "합계") -> Finding:
        difference = check.stated - check.computed
        features = {
            "arithmetic_proof": True,
            "deterministic_rule": True,
            "stated": str(check.stated),
            "computed": str(check.computed),
            "difference": str(difference),
            "item_count": len(check.items),
            # 판정 근거에 쓴 행(J3). 산식 행은 '=' 뒤 최종 금액으로 셌다.
            "rows_used": list(getattr(check, "rows", []) or [f"{a.raw}" for a in check.items]),
        }
        return Finding.create(
            type=FindingType.ARITHMETIC_MISMATCH,
            status=VerificationStatus.CONTRADICTED,
            severity=Severity.HIGH if abs(difference) > check.computed * Decimal("0.01") else Severity.MEDIUM,
            evidence_grade=EvidenceGrade.A,
            title=f"{label}가 세부 금액 합산값과 다르다 (차이 {difference:,}원)",
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
