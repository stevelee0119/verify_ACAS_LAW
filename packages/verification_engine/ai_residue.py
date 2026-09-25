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


@dataclass(frozen=True)
class ResidueRule:
    """잔재 규칙 한 건. objective(작성 주체 판단의 객관적 흔적)와 report(초안 흔적으로 보고)는 서로 다른 질문이다."""
    category: str
    label: str
    objective: bool
    pattern: "re.Pattern[str]"
    min_kinds: int
    report: bool
    report_min_kinds: int

    def __getitem__(self, index):
        return tuple(self)[index]

    def __iter__(self):
        # 예전 호출부(범주, 설명, 객관 여부, 패턴, 최소 종류 수) 풀기와 호환한다
        return iter((self.category, self.label, self.objective, self.pattern, self.min_kinds))


@lru_cache(maxsize=1)
def weak_report_min_categories() -> int:
    """문체 신호 범주(objective: false)를 초안 흔적으로 보고하려면 서로 다른 보고 대상 범주가 몇 개 함께 나와야 하는가.

    맺음말 한 줄·마크다운 표 하나는 사람도 쓰므로 그것만으로는 보고하지 않는다. 서로 독립인 잔재(예: 마크다운 제목 +
    면책 안내 + 챗봇 맺음말)가 한 문서에 함께 남아 있으면 초안을 그대로 옮긴 흔적으로 보고한다.
    """
    data = yaml.safe_load(PATTERNS_PATH.read_text(encoding="utf-8")) or {}
    return int(data.get("weak_report_min_categories") or 2)


@lru_cache(maxsize=1)
def load_rules() -> Tuple[ResidueRule, ...]:
    """config/ai_residue_patterns.yaml의 규칙. report를 적지 않으면 objective 값을 따른다."""
    data = yaml.safe_load(PATTERNS_PATH.read_text(encoding="utf-8")) or {}
    rules = []
    for rule in data.get("rules") or []:
        flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
        objective = bool(rule.get("objective"))
        rules.append(ResidueRule(rule["category"], rule["label"], objective, re.compile(rule["pattern"], flags),
                                 int(rule.get("min_kinds") or 1), bool(rule.get("report", objective)),
                                 int(rule.get("report_min_kinds") or 1)))
    return tuple(rules)


@dataclass
class Residue:
    category: str
    label: str
    objective: bool
    matches: List[str] = field(default_factory=list)
    # signal: 문체·작성 주체 신호로 셀 만큼(min_kinds 이상) 나왔는가 / reportable: 초안 흔적으로 보고할 대상인가
    signal: bool = True
    reportable: bool = False


# 직접 인용구 패턴 ("...", “...”, 「...」, 『...』)
_DIRECT_QUOTE_RE = re.compile(r'["“「『]([^"”」』]{5,500})["”」』]')


def _mask_direct_quotes(text: str) -> str:
    """직접 인용문구 내부 텍스트를 공백으로 치환하여 작성자 본인의 서술과 인용 대상을 구분한다."""
    if not text:
        return ""
    def _repl(m: re.Match) -> str:
        # 따옴표 기호는 유지하고 내용만 공백 치환
        return text[m.start()] + " " * (m.end() - m.start() - 2) + text[m.end() - 1]
    return _DIRECT_QUOTE_RE.sub(_repl, text)


def scan_residue(
    text: str,
    exclude_texts: Optional[List[str]] = None,
    mask_quotes: bool = True,
) -> List[Residue]:
    """텍스트에서 AI 잔재를 스캔한다.
    
    인용문구 내부 텍스트(mask_quotes=True) 및 공격 탐지 지시문 등 제외 텍스트는 스캔 대상에서 제외한다.
    """
    out: List[Residue] = []
    if not text:
        return out

    target_text = text

    # 제외 텍스트 치환 (예시, 프롬프트 지시문 등)
    if exclude_texts:
        for ex in exclude_texts:
            if ex and ex in target_text:
                target_text = target_text.replace(ex, " " * len(ex))

    if mask_quotes:
        target_text = _mask_direct_quotes(target_text)

    for rule in load_rules():
        found = []
        for m in rule.pattern.finditer(target_text):
            fragment = " ".join(m.group(0).split())
            if fragment not in found:
                found.append(fragment)
        kinds = len({re.sub(r"\s+", "", f) for f in found})
        signal = bool(found) and kinds >= rule.min_kinds
        reportable = bool(found) and rule.report and kinds >= rule.report_min_kinds
        if not (signal or reportable):
            continue
        out.append(Residue(rule.category, rule.label, rule.objective, found[:8], signal=signal, reportable=reportable))
    return out


def residue_findings(doc: NormalizedDocument, residues: List[Residue],
                     exclude_texts: Optional[List[str]] = None) -> List[Finding]:
    """객관적 잔재를 범주마다 한 건씩 '생성 초안 흔적(DRAFT_ARTIFACT)'으로 싣는다. 세부 코드는 AI_RESPONSE_RESIDUE.

    잔재는 AI 관여의 흔적일 뿐 작성 주체를 단정하지 않는다. 문서 속 지시문(공격 탐지 대상)에 든 글자는 뺀다.
    """
    excluded = [" ".join(t.split()) for t in exclude_texts or [] if t]
    # 지시문 안의 글자를 뺀 뒤 남는 보고 대상 잔재(범주별)
    kept = []
    for residue in residues:
        # 작성 주체 판단과 별개로, 제출 서면에 남은 초안 흔적으로 보고할 범주만 싣는다(config의 report)
        if not residue.reportable:
            continue
        matches = [m for m in residue.matches if not any(m in t for t in excluded)]
        if matches:
            kept.append((residue, matches))
    # 문체 신호 범주는 서로 다른 보고 대상 범주가 함께 나올 때만 보고한다(한 범주만으로는 사람도 쓴다)
    corroborated = len({residue.category for residue, _ in kept}) >= weak_report_min_categories()
    out: List[Finding] = []
    for residue, matches in kept:
        if not residue.objective and not corroborated:
            continue
        features = {"deterministic_rule": True, "defect_code": DEFECT_CODE, "rule_id": f"AI_RESIDUE.{residue.category}",
                    "residue_category": residue.category, "matches": matches,
                    "authorship_trace": residue.objective}
        out.append(Finding.create(
            type=FindingType.DRAFT_ARTIFACT, status=VerificationStatus.SUSPICIOUS, severity=Severity.LOW,
            evidence_grade=EvidenceGrade.A,
            title=f"AI 응답 잔재({DEFECT_CODE}): {residue.label} — '{matches[0][:60]}'",
            detail=(f"서면 작성 관행에 없는 생성형 AI 응답의 흔적({residue.label}) {len(matches)}건이 본문에 남아 있다. "
                    "제출 전 삭제 여부를 확인해야 한다. AI 관여의 흔적일 뿐 작성 주체나 내용의 옳고 그름을 단정하지 않는다."
                    + ("" if residue.objective else
                       " 이 범주는 사람도 쓸 수 있어 AI 작성 판단의 객관적 흔적으로는 세지 않는다(서식 결함으로만 보고).")),
            confidence=0.9, confidence_features=features, document_id=doc.document_id, engine=ENGINE_NAME,
            tags=["draft_artifact", "ai_residue", residue.category],
            evidence=[Evidence.create(description=residue.label, grade=EvidenceGrade.A, document_id=doc.document_id,
                                      excerpt=" / ".join(matches[:3])[:300])],
        ))
    return out
