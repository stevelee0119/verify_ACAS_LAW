"""Conservative comparison of explicit claim totals with a single itemized table."""
import re
from decimal import Decimal

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding


def claim_amount_findings(doc):
    from .calculation import parse_amounts, parse_cell_amount

    out = []
    seen_claims = set()
    # Multiple tables/claims and partial claims need a human allocation decision.
    tables = [t for t in doc.structure.get("tables", []) if t.get("cells") and
              any(re.search(r"주장액|손해액|청구액|금액", str(c)) for c in t["cells"][0])]
    if len(tables) != 1:
        return out
    rows = tables[0].get("cells", [])
    if not rows or not isinstance(rows[0], list):
        return out
    header = rows[0]
    columns = [i for i, cell in enumerate(header) if re.search(r"주장액|손해액|청구액|금액", str(cell))]
    if len(columns) != 1:
        return out
    col = columns[0]
    amounts, labels, stated = [], [], None
    for row in rows[1:]:
        if len(row) <= col:
            return []
        label = str(row[0]).strip()
        amount = parse_cell_amount(str(row[col]))
        if amount is None:
            return []
        if re.fullmatch(r"합\s*계|총액|총\s*계", label):
            if stated is not None:
                return []
            stated = amount.value
        else:
            labels.append(label)
            amounts.append(amount.value)
    if stated is None or len(amounts) < 2:
        return out
    computed = sum(amounts, Decimal(0))
    blocks = list(doc.prose_blocks())
    for index, block in enumerate(blocks):
        text = re.sub(r"\s+", " ", block.text)
        if index + 1 < len(blocks) and blocks[index + 1].page == block.page and not re.search(r"[.!?。]$", text):
            text += " " + re.sub(r"\s+", " ", blocks[index + 1].text)
        if re.search(r"일부\s*청구|청구\s*일부|별도\s*청구|예비적|공제|상계", text):
            continue
        for match in re.finditer(r"(?:청구서\s*본문|청구취지)[^.。]{0,70}?(?:청구합니다|청구한다|지급하라)", text):
            values = parse_amounts(match.group())
            # Require an explicit connection to the itemization in the same block.
            if len(values) != 1 or not re.search(r"(?:위|앞|상기)\s*항목.*합산|세부\s*합계", text):
                continue
            claim = values[0].value
            if claim == computed or claim in seen_claims:
                continue
            seen_claims.add(claim)
            out.append(Finding.create(
                type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.CONTRADICTED,
                severity=Severity.HIGH, evidence_grade=EvidenceGrade.A,
                title=f"청구 본문 {claim:,}원과 세부 합산 {computed:,}원이 다르다 (표 합계 {stated:,}원)",
                detail="문서가 같은 항목의 합산과 청구액으로 연결한 금액을 비교했다. 법적으로 인정되는 손해액의 판정은 아니다.",
                document_id=doc.document_id, block_id=block.block_id, page=block.page,
                engine="claim_engine.calculation", confidence=0.95,
                confidence_features={"rule_id": "CALC.CLAIM_TOTAL_MISMATCH", "arithmetic_proof": True,
                    "claim_amount": str(claim), "computed": str(computed), "table_total": str(stated)},
                evidence=[Evidence.create(description="본문과 단일 손해액 표", grade=EvidenceGrade.A,
                    document_id=doc.document_id, page=block.page, excerpt=text[:500])]))
        included = re.search(r"향\s*후\s*치료비[^.。]{0,90}이미\s*합계에\s*포함", text)
        if included and not any(re.search(r"향\s*후|장래|추후|치료비", label) for label in labels):
            out.append(Finding.create(
                type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.SUSPICIOUS,
                severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.C,
                title="향후 치료비가 합계에 포함되었다는 설명과 표 항목을 대조해야 한다",
                detail="단일 손해액 표에 향후 치료비 항목을 찾지 못했다. 다른 항목에 포함했는지, 누락되었는지는 사람이 확인해야 한다.",
                document_id=doc.document_id, block_id=block.block_id, page=block.page,
                engine="claim_engine.calculation", confidence=0.6,
                confidence_features={"rule_id": "CALC.INCLUDED_ITEM_NOT_LISTED", "human_review": True,
                    "table_labels": labels, "claim": included.group()},
                evidence=[Evidence.create(description="포함 주장과 표 항목", grade=EvidenceGrade.C,
                    document_id=doc.document_id, page=block.page, excerpt=included.group())]))
    return out
