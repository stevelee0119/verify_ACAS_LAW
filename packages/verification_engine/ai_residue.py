"""AI 응답 잔재 신호(v2 Phase 8). 규칙 기반이며 모두 '참고용, 확정 불가'다.

생성형 AI의 답변을 서면에 옮기면 대화형 서두("물론입니다! … 작성해 드리겠습니다"), 마크다운 문법(###, **),
지식 기준일 언급, 면책 안내문("법률 자문을 대체하지 않습니다 … 말씀해 주세요!") 같은 잔재가 남는다. 이것들은
서면 작성 관행에 없는 표지이므로 '객관적 흔적'으로 센다. 상투적 연결어·영문 병기는 사람도 쓰므로 문체 신호로만
표시한다. 어느 것도 사람 작성/AI 작성을 단정하는 근거가 아니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

# 규칙은 코드와 분리한 사전에 둔다(v3 §3-6): config/ai_residue_patterns.yaml
PATTERNS_PATH = Path(__file__).resolve().parents[2] / "config" / "ai_residue_patterns.yaml"
ENGINE_NAME = "verification_engine.ai_residue"
DEFECT_CODE = "AI_RESPONSE_RESIDUE"


@lru_cache(maxsize=1)
def load_rules() -> Tuple[Tuple[str, str, bool, "re.Pattern[str]", int], ...]:
    """(범주, 설명, 객관적 흔적 여부, 패턴, 최소 종류 수)."""
    data = yaml.safe_load(PATTERNS_PATH.read_text(encoding="utf-8")) or {}
    rules = []
    for rule in data.get("rules") or []:
        flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
        rules.append((rule["category"], rule["label"], bool(rule.get("objective")),
                      re.compile(rule["pattern"], flags), int(rule.get("min_kinds") or 1)))
    return tuple(rules)


@dataclass
class Residue:
    category: str
    label: str
    objective: bool
    matches: List[str] = field(default_factory=list)


def scan_residue(text: str) -> List[Residue]:
    out: List[Residue] = []
    for category, label, objective, pattern, min_kinds in load_rules():
        found = []
        for m in pattern.finditer(text or ""):
            fragment = " ".join(m.group(0).split())
            if fragment not in found:
                found.append(fragment)
        if not found or len({re.sub(r"\s+", "", f) for f in found}) < min_kinds:
            continue
        out.append(Residue(category, label, objective, found[:8]))
    return out


def residue_findings(doc: NormalizedDocument, residues: List[Residue],
                     exclude_texts: Optional[List[str]] = None) -> List[Finding]:
    """객관적 잔재를 범주마다 한 건씩 '생성 초안 흔적(DRAFT_ARTIFACT)'으로 싣는다. 세부 코드는 AI_RESPONSE_RESIDUE.

    잔재는 AI 관여의 흔적일 뿐 작성 주체를 단정하지 않는다. 문서 속 지시문(공격 탐지 대상)에 든 글자는 뺀다.
    """
    excluded = [" ".join(t.split()) for t in exclude_texts or [] if t]
    out: List[Finding] = []
    for residue in residues:
        if not residue.objective:
            continue
        matches = [m for m in residue.matches if not any(m in t for t in excluded)]
        if not matches:
            continue
        features = {"deterministic_rule": True, "defect_code": DEFECT_CODE, "rule_id": f"AI_RESIDUE.{residue.category}",
                    "residue_category": residue.category, "matches": matches}
        out.append(Finding.create(
            type=FindingType.DRAFT_ARTIFACT, status=VerificationStatus.SUSPICIOUS, severity=Severity.LOW,
            evidence_grade=EvidenceGrade.A,
            title=f"AI 응답 잔재({DEFECT_CODE}): {residue.label} — '{matches[0][:60]}'",
            detail=(f"서면 작성 관행에 없는 생성형 AI 응답의 흔적({residue.label}) {len(matches)}건이 본문에 남아 있다. "
                    "제출 전 삭제 여부를 확인해야 한다. AI 관여의 흔적일 뿐 작성 주체나 내용의 옳고 그름을 단정하지 않는다."),
            confidence=0.9, confidence_features=features, document_id=doc.document_id, engine=ENGINE_NAME,
            tags=["draft_artifact", "ai_residue", residue.category],
            evidence=[Evidence.create(description=residue.label, grade=EvidenceGrade.A, document_id=doc.document_id,
                                      excerpt=" / ".join(matches[:3])[:300])],
        ))
    return out
