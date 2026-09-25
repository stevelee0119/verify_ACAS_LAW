"""제11.5장 숫자 검증.

손해액, 이자, 기간, 합계, 비율은 LLM이 아닌 Python Calculation Engine으로 검산한다.
문서의 합계와 세부 금액 합산값이 다르면 ARITHMETIC_MISMATCH를 Evidence Grade A로 생성한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "claim_engine.calculation"

AMOUNT_RE = re.compile(
    r"(?<![\d.,])(?P<cur>일금\s*|금\s*|[₩\\￥]\s*|KRW\s*)?(?P<sign>[-−+]?)\s*"
    r"(?P<amount>(?:\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천)\s*)*\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천)?)"
    r"(?:\s*(?P<unit>원정|원))?"
)
AMOUNT_PART_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?")
TOTAL_LABEL_RE = re.compile(r"(합계|총액|총\s*금액|계|소계|합\s*계|총\s*계|지급총액|지급계|지급\s*총액|공제계|공제총액|공제\s*합계|실지급액|차인지급액|총수령액)")
ITEM_LABEL_RE = re.compile(r"(항목|내역|세부|명세)")
PERCENT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*%")
PERCENT_HEADER_RE = re.compile(r"비율|구성비|점유율|%|퍼센트")

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
            has_cur = bool(m.group("cur"))
            has_unit = bool(m.group("unit"))
            has_mult = any(bool(unit) for _, unit in parts)
            if not (has_cur or has_unit or has_mult):
                continue
            # Do not silently parse the tail of an unsupported compound/currency.
            prefix = text[:m.start()]
            if re.search(r"(?:\d[\d,.]*\s*(?:조|경|백|십)|USD|EUR|JPY|[$€¥])\s*$", prefix, re.I):
                continue
            if re.match(r"\s*(?:조|경|백|십)(?=\s*(?:\d|[억만천백십원]|$))", text[m.end():]):
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


def parse_cell_amount(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> Optional[Amount]:
    """표 셀의 금액 파싱: '원'이나 '₩'이 붙은 경우뿐만 아니라 '3,200,000'이나 '0' 같은 순수 숫자도 금액으로 인식한다."""
    t = text.strip()
    if not t:
        return None
    amounts = parse_amounts(t, block_id=block_id, page=page)
    if amounts:
        return amounts[0]
    if re.fullmatch(r"[-−+]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", t):
        try:
            val = Decimal(t.replace(",", "").replace("−", "-"))
            return Amount(val, t, 0, len(t), block_id=block_id, page=page)
        except InvalidOperation:
            return None
    return None


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


def row_cell_final_amount(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> Tuple[Optional[Amount], Optional[CalculationCheck]]:
    """표 셀의 최종 금액과 산식 검증. 단위가 생략된 천 단위 콤마 숫자도 지원한다."""
    if "=" in text:
        left, _, right = text.rpartition("=")
        right_amt = parse_cell_amount(right, block_id=block_id, page=page)
        value = evaluate_expression(left[left.rfind(":") + 1:] if ":" in left else left)
        if right_amt:
            check = None
            if value is not None:
                check = CalculationCheck(kind="FORMULA", stated=right_amt.value, computed=value,
                                         detail=f"산식 '{' '.join(text.split())}'의 계산값 {value:,} / 기재 {right_amt.value:,}")
            return right_amt, check
    amt = parse_cell_amount(text, block_id=block_id, page=page)
    if amt is not None:
        return amt, None
    return None, None


class CalculationEngine:
    """문서에서 합계 진술을 찾아 세부 금액과 검산한다."""

    def verify_document(self, doc: NormalizedDocument) -> List[Finding]:
        findings: List[Finding] = []
        seen_blocks: set = set()
        for block in doc.body_blocks():
            if block.block_type == "table" or block.attributes.get("table_ref"):
                continue  # 표는 _verify_table_totals에서 행 단위로 검산한다
            found = self._verify_block(doc, block)
            if found:
                seen_blocks.add(block.block_id)
            findings.extend(found)
        findings.extend(self._verify_table_totals(doc))
        # 실무 서면은 항목이 줄마다 나뉘므로 줄 단위 내역-합계도 검산한다
        findings.extend(self._verify_line_items(doc, seen_blocks))
        findings = self._deduplicate_totals(merge_same_total(findings))
        findings.extend(self._verify_percentages(doc, findings))
        return findings

    def _deduplicate_totals(self, findings: List[Finding]) -> List[Finding]:
        """합계 검산 중복 제거: 중복·부분 판정 없이 가장 정확하고 포괄적인 한 건만 채택한다(과제 7)."""
        calc_findings: List[Finding] = []
        other_findings: List[Finding] = []
        for f in findings:
            if f.type == FindingType.ARITHMETIC_MISMATCH and (f.confidence_features or {}).get("stated"):
                calc_findings.append(f)
            else:
                other_findings.append(f)

        if len(calc_findings) <= 1:
            return findings

        # 세부 항목 수가 많고(가장 포괄적 검산), 심각도가 높은 것 우선 정렬
        calc_findings.sort(
            key=lambda x: (
                -int((x.confidence_features or {}).get("item_count", 0)),
                -x.severity.rank,
            )
        )

        kept: List[Finding] = []
        for cand in calc_findings:
            cand_feat = cand.confidence_features or {}
            cand_stated = cand_feat.get("stated")
            cand_page = cand.page
            cand_rows = set(cand_feat.get("rows_used") or [])

            duplicate = False
            for existing in kept:
                if _calculation_scope(cand) != _calculation_scope(existing):
                    continue
                ex_feat = existing.confidence_features or {}
                ex_stated = ex_feat.get("stated")
                ex_page = existing.page
                ex_rows = set(ex_feat.get("rows_used") or [])

                # 1) 같은 페이지에서 동일한 stated 금액을 검산한 경우 -> 중복
                if cand_page == ex_page and cand_stated == ex_stated:
                    duplicate = True
                    break
                # 2) rows_used가 서로 포함관계(subset)인 경우 -> 부분 판정이므로 이미 더 큰 쪽이 채택됨
                if cand_page == ex_page and cand_rows and ex_rows:
                    if cand_rows.issubset(ex_rows) or ex_rows.issubset(cand_rows):
                        duplicate = True
                        break

            if not duplicate:
                kept.append(cand)

        return other_findings + kept

    def _verify_percentages(self, doc: NormalizedDocument, totals: List[Finding]) -> List[Finding]:
        """비율(%) 열을 금액 열로 다시 계산한다(v5 3-3). 비율은 합계에서 나온 파생 수치이므로, 틀린 비율이 기재 합계
        기준으로는 맞으면 원인을 합계 칸 오류로 연결하고, 어느 기준으로도 맞지 않으면 비율 자체의 계산 오류로 본다."""
        out: List[Finding] = []
        for table_index, table in enumerate(doc.structure.get("tables") or []):
            cells = [[str(c or "").strip() for c in row] for row in table.get("cells") or []]
            if len(cells) < 3:
                continue
            header = cells[0]
            width = max(len(r) for r in cells)
            pct_share = [sum(1 for r in cells[1:] if i < len(r) and PERCENT_RE.search(r[i])) for i in range(width)]
            pct_cols = [i for i, h in enumerate(header) if PERCENT_HEADER_RE.search(h)] or \
                       [i for i in range(width) if pct_share[i] >= max(2, (len(cells) - 1) // 2)]
            if not pct_cols:
                continue
            pct_col = pct_cols[0]
            amount_cols = [i for i, h in enumerate(header) if AMOUNT_HEADER_RE.search(h) and i != pct_col]
            if not amount_cols:
                counts = [sum(1 for r in cells[1:] if i < len(r) and parse_amounts(r[i])) if i != pct_col else -1
                          for i in range(width)]
                amount_cols = [max(range(width), key=lambda i: (counts[i], i))] if max(counts) > 0 else []
            if not amount_cols:
                continue
            col = amount_cols[-1]
            items, stated = [], None
            for row in cells[1:]:
                if col >= len(row) or pct_col >= len(row):
                    continue
                amount = parse_amounts(row[col])
                if not amount:
                    continue
                if row and TOTAL_LABEL_RE.fullmatch(row[0].replace(" ", "")):
                    stated = amount[-1].value
                    continue
                pct = PERCENT_RE.search(row[pct_col])
                if pct:
                    items.append((row[0], amount[-1].value, Decimal(pct.group("num")), pct.group("num")))
            computed = sum((value for _, value, _, _ in items), Decimal(0))
            if len(items) < 2 or computed <= 0:
                continue
            wrong, derived = [], []
            for label, value, pct, raw in items:
                decimals = len(raw.split(".")[1]) if "." in raw else 0
                tolerance = Decimal("0.5") * (Decimal(10) ** -decimals) + Decimal("0.001")
                by_sum = value / computed * 100
                if abs(pct - by_sum) <= tolerance:
                    continue
                if stated and stated != computed and abs(pct - value / stated * 100) <= tolerance:
                    derived.append(f"{label}: {raw}% (기재 합계 기준 {value / stated * 100:.2f}%, 세부 합산 기준 {by_sum:.2f}%)")
                else:
                    wrong.append(f"{label}: 기재 {raw}% / 계산 {by_sum:.2f}%")
            if not (wrong or derived):
                continue
            table_ref = table.get("table_ref") or f"table-{table_index}"
            cause = next((f for f in totals if f.confidence_features.get("stated") == str(stated)
                          and f.confidence_features.get("table_ref") == table_ref
                          and f.confidence_features.get("table_column") == col), None) if derived else None
            if cause is not None:
                cause.confidence_features.setdefault("derived_effects", []).extend(derived)
            features = {"arithmetic_proof": True, "deterministic_rule": True, "rule_id": "CALC.PERCENT_MISMATCH",
                        "rows": wrong + derived, "computed_total": str(computed),
                        "stated_total": str(stated) if stated is not None else None,
                        "cause": "STATED_TOTAL" if derived and not wrong else "PERCENT_CALCULATION",
                        "cause_finding": cause.finding_id if cause is not None else None}
            title = ("비율(%)이 틀린 합계를 기준으로 계산되었다(원인: 합계 칸 오류)" if derived and not wrong
                     else "비율(%)이 금액으로 다시 계산한 값과 다르다")
            out.append(Finding.create(
                type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.CONTRADICTED, severity=Severity.MEDIUM,
                evidence_grade=EvidenceGrade.A, title=title,
                detail=("비율 열을 금액 열로 다시 계산했다(세부 합산 " + f"{computed:,}원). " + "; ".join((wrong + derived)[:6])
                        + (f". 비율은 기재 합계 {stated:,}원 기준으로 맞으므로 원인은 합계 칸이다." if derived and not wrong else "")),
                confidence=confidence_score(features), confidence_features=features, document_id=doc.document_id,
                page=table.get("page"), engine=ENGINE_NAME, tags=["CALCULATION", "PERCENT"],
                evidence=[Evidence.create(description="비율 열", grade=EvidenceGrade.A, document_id=doc.document_id,
                                          page=table.get("page"), excerpt="; ".join(wrong + derived)[:300])]))
        return out

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
                and not b.attributes.get("table_ref")
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
        # 합계가 속한 문단(직전 빈 줄 이후)으로 묶음을 한정하여 무관한 앞 문단(청구취지 등)을 합산하지 않는다
        prefix = text[:total_match.start()]
        last_break = prefix.rfind("\n\n")
        section_start = (last_break + 2) if last_break != -1 else 0
        section_before = [a for a in before if a.start >= section_start]
        if not after or len(section_before) < 2:
            return []
        stated = after[0]
        check = check_sum(section_before, stated)
        if check.matches:
            return []
        return [self._mismatch_finding(doc, check, block.block_id, block.page, text[section_start:])]

    def _verify_cell_tables(self, doc: NormalizedDocument) -> Tuple[List[Finding], set]:
        """셀 단위 표: 모든 금액 열에 대해 세로 합산(지급총액, 공제계, 합계 등)과 실지급액 산식을 검산한다."""
        findings: List[Finding] = []
        handled = set()

        raw_tables = doc.structure.get("tables") or []
        if not raw_tables:
            return findings, handled

        # Equal column counts do not establish that two tables are continuations.
        tables_to_check = []
        for index, t in enumerate(raw_tables):
            tables_to_check.append({
                "page": t.get("page"),
                "table_ref": t.get("table_ref") or f"table-{index}",
                "cells": [[str(c or "").strip() for c in row] for row in t.get("cells") or []],
            })

        for table in tables_to_check:
            cells = table.get("cells") or []
            if len(cells) < 3:
                continue
            header = cells[0]
            col_count = len(header)

            # 금액이 존재하는 모든 데이터 열 탐색
            candidate_cols = []
            for col_idx in range(1, col_count):
                amounts_in_col = sum(1 for r in cells[1:] if col_idx < len(r) and parse_cell_amount(r[col_idx]))
                if amounts_in_col >= 2:
                    candidate_cols.append(col_idx)

            if not candidate_cols:
                continue

            for col in candidate_cols:
                first_finding = len(findings)
                col_header_name = header[col] if col < len(header) else f"열 {col}"
                total_rows = [r for r in cells[1:] if r and TOTAL_LABEL_RE.search(r[0].replace(" ", ""))]
                grand = total_rows[-1] if total_rows else None
                top: List[Amount] = []
                segment: List[Tuple[Amount, str]] = []
                subtotals: Dict[str, Amount] = {}
                grand_checked = False

                for row in cells[1:]:
                    if col >= len(row):
                        continue
                    row_label = row[0].strip()
                    cell_text = row[col].strip()
                    final, formula = row_cell_final_amount(cell_text)

                    # 산식 행 검산
                    for index, cell in enumerate(row):
                        if index == col or not cell or not parse_cell_amount(cell):
                            continue
                        val = evaluate_expression(cell.split("=")[0]) if "=" in cell or OPERATOR_RE.search(cell) else None
                        if final and val is not None and abs(val - final.value) > TOLERANCE:
                            chk = CalculationCheck(
                                kind="FORMULA", stated=final.value, computed=val,
                                detail=f"'{row_label}' 행 산식 '{cell}'의 계산값 {val:,} / 금액 칸 {final.value:,}"
                            )
                            findings.append(self._formula_finding(doc, chk, None, table.get("page"), " | ".join(row)))

                    if final is None:
                        continue

                    if any(row is r for r in total_rows):
                        # 1) 실지급액/차인지급액 산식 검증 (지급총액 - 공제계 = 실지급액)
                        if any(k in row_label for k in ["실지급", "차인지급", "총수령"]):
                            pay_total = next((v.value for k, v in subtotals.items() if any(p in k for p in ["지급", "총액", "기본"])), None)
                            ded_total = next((v.value for k, v in subtotals.items() if any(d in k for d in ["공제", "세금", "보험"])), None)
                            if pay_total is not None and ded_total is not None:
                                expected_net = pay_total - ded_total
                                if abs(final.value - expected_net) > TOLERANCE:
                                    chk_net = CalculationCheck(
                                        kind="NET_PAY", stated=final.value, computed=expected_net,
                                        detail=f"[{col_header_name}] 실지급액 산식(지급총액 {pay_total:,} - 공제계 {ded_total:,} = {expected_net:,}) / 기재 {final.value:,}"
                                    )
                                    findings.append(self._mismatch_finding(
                                        doc, chk_net, None, table.get("page"),
                                        "\n".join(" | ".join(r) for r in cells), label=f"{col_header_name} {row_label}"
                                    ))
                            # Net pay is a subtraction, not a sum of the preceding subtotals.
                            grand_checked = grand_checked or row is grand
                            continue

                        rows_used = [label for _, label in segment]
                        items = top + [a for a, _ in segment] if row is grand else [a for a, _ in segment]
                        if row is grand:
                            rows_used = [f"{a.raw}" for a in top] + rows_used
                        if len(items) >= 2:
                            check = check_sum(items, final)
                            check.rows = rows_used
                            if not check.matches:
                                excerpt = "\n".join(" | ".join(r) for r in cells)
                                label = "합계" if row is grand else f"{col_header_name} {row_label}"
                                findings.append(self._mismatch_finding(doc, check, None, table.get("page"), excerpt,
                                                                       label=label))
                            grand_checked = grand_checked or row is grand
                        if row is not grand:
                            top.append(final)  # 소계는 위 단계에서 한 항목이 된다
                            segment = []
                        subtotals[row_label] = final
                        continue

                    segment.append((final, f"{row_label}: {final.raw}"))

                if grand_checked:
                    handled.add(table.get("table_ref"))
                for finding in findings[first_finding:]:
                    finding.confidence_features.update(table_ref=table["table_ref"], table_column=col)

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


def _calculation_scope(finding: Finding) -> tuple:
    features = finding.confidence_features or {}
    return (finding.document_id, finding.page, features.get("table_ref") or finding.block_id,
            features.get("table_column"))


def merge_same_total(findings: List[Finding]) -> List[Finding]:
    """같은 합계(기재 금액이 같은 합계 칸)에 대한 합산 판정은 하나만 남긴다(v5 3-5).

    표를 칸 단위로 읽은 판정과 줄 단위로 읽은 판정이 함께 나오면, 줄 단위 쪽은 표 일부만 더해 차액이 틀린다.
    세부 항목을 가장 많이 포함한 판정을 남기고, 나머지는 근거(merged_partial_checks)로만 붙인다.
    """
    groups: dict = {}
    order: List[Finding] = []
    for finding in findings:
        features = finding.confidence_features or {}
        if finding.type != FindingType.ARITHMETIC_MISMATCH or features.get("kind") == "FORMULA" or "stated" not in features \
                or features.get("rule_id") not in (None, "CALC.SUM"):
            order.append(finding)
            continue
        key = (*_calculation_scope(finding), features["stated"])
        if key in groups:
            groups[key].append(finding)
            continue
        groups[key] = [finding]
        order.append(finding)
    out: List[Finding] = []
    for finding in order:
        group = groups.get((*_calculation_scope(finding), (finding.confidence_features or {}).get("stated")))
        if not group or group[0] is not finding:
            out.append(finding)
            continue
        best = max(group, key=lambda f: int(f.confidence_features.get("item_count") or 0))
        others = [f for f in group if f is not best]
        if others:
            best.confidence_features["merged_partial_checks"] = [
                {"computed": f.confidence_features.get("computed"), "item_count": f.confidence_features.get("item_count"),
                 "title": f.title} for f in others]
        out.append(best)
    return out
