"""청구 구조 검토(PLEADING_STRUCTURE_REVIEW): 양립할 수 없는 청구의 단순 병합 여부 확인 요청.

청구취지 안에 서로 반대되는 전제를 가진 청구(config/legal_rules/pleading_premise_pairs.yaml의 대립쌍)가 함께 있고,
주위적·예비적 표지가 없으면 법률가 확인이 필요한 항목으로 알린다(SUSPICIOUS, 근거등급 C). 병합 형태의
적법성은 판정하지 않는다. 특정 사건의 문구가 아니라 대립쌍 표를 데이터로 관리한다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text

from .legal_rules import _items, _sections

ENGINE_NAME = "legal_engine.pleading_structure"
PAIRS_PATH = Path(__file__).resolve().parents[2] / "config" / "legal_rules" / "pleading_premise_pairs.yaml"


@lru_cache(maxsize=1)
def load_pairs() -> Dict[str, Any]:
    try:
        return yaml.safe_load(PAIRS_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def pleading_structure_findings(doc: NormalizedDocument) -> List[Finding]:
    table = load_pairs()
    relief = _sections(build_reading_text(doc).text)["RELIEF"]
    if not relief.strip():
        return []
    ordering = re.compile(table.get("ordering_markers") or r"주위적|예비적")
    if ordering.search(relief):
        return []  # 순위를 붙인 예비적 병합은 이 검토의 대상이 아니다
    items = _items(relief)
    basis = table.get("basis") or []
    out: List[Finding] = []
    for pair in table.get("pairs") or []:
        a_re, b_re = re.compile(pair["premise_a"]), re.compile(pair["premise_b"])
        a_items = [item for item in items if a_re.search(item)]
        b_items = [item for item in items if b_re.search(item)]
        if not a_items or not b_items:
            continue
        features = {"deterministic_rule": True, "rule_id": f"PLEADING_STRUCTURE_REVIEW.{pair['id']}",
                    "verdict_label": "PLEADING_STRUCTURE_REVIEW", "pair": pair["id"], "human_review": True,
                    "basis": basis, "claims": [a_items[0][:200], b_items[0][:200]]}
        out.append(Finding.create(
            type=FindingType.LEGAL_ARGUMENT_INVALID, status=VerificationStatus.SUSPICIOUS, severity=Severity.MEDIUM,
            evidence_grade=EvidenceGrade.C,
            title=f"청구 구조 확인 필요(PLEADING_STRUCTURE_REVIEW): {pair['label']}",
            detail=(f"{pair['explanation']} 청구취지에 두 청구가 주위적·예비적 구분 없이 함께 있다. "
                    "양립할 수 없는 청구를 단순 병합한 것인지, 병합 형태를 법률가가 확인해야 한다. 판정이 아닌 확인 요청이다."),
            confidence=0.5, confidence_features=features, document_id=doc.document_id, engine=ENGINE_NAME,
            tags=["LEGAL", "PLEADING_STRUCTURE"],
            evidence=[Evidence.create(description="청구취지 항목", grade=EvidenceGrade.C, document_id=doc.document_id,
                                      excerpt=f"{a_items[0][:140]} / {b_items[0][:140]}")]))
    return out
