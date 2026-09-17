"""문서 AI 관여 흔적 분석 (설계서 v1.0 제7·8장).

문서 파일에서 AI 사용에 관한 출처 기록과 제작 도구 정보를 추출하고,
"확인할 수 있는 사실"과 "추정"을 구분해 제시한다.

이 모듈이 하지 않는 것을 먼저 적어 둔다. 판정의 안전은 금지사항에서 나온다.

- 흔적이 없다는 결과를 사람이 작성했다는 증거로 바꾸지 않는다. 그래서
  판정값에 HUMAN에 해당하는 항목 자체가 없다(제1.1장).
- 제작 프로그램이 Word·한글·ReportLab이라는 사실로 작성 주체를 정하지 않는다.
- 삽입 이미지나 첨부의 기록을 문서 본문의 AI 작성으로 확대하지 않는다(제7.1장).
- 검증기를 구현하지 않은 검사는 후보를 발견했더라도 unsupported이며,
  '검증됨'으로 표시하지 않는다(F06).
- 간접 근거를 합산해 확률로 표시하지 않는다(제8.4장).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packages.common.enums import (
    AIInvolvementVerdict,
    CheckStatus,
    ProvenanceAction,
    ProvenanceScope,
)
from packages.common.schemas import NormalizedDocument

ENGINE_NAME = "forensic_engine.ai_provenance"
RULE_VERSION = "2026-09-17.1"

# ---------------------------------------------------------------------------
# AI 서비스·모델 표기
#
# 이 표기가 메타데이터에 있다는 것은 "AI 관련 문자열이 존재한다"는 사실일 뿐이다.
# 문서 속성은 누구나 편집할 수 있으므로 그 자체로는 진위가 확인되지 않는다.
# ---------------------------------------------------------------------------
AI_TOOL_RE = re.compile(
    r"(chatgpt|openai|gpt-[0-9]|claude|anthropic|gemini|bard|copilot|llama|mistral|"
    r"stable\s*diffusion|midjourney|dall[\s\-]?e|firefly|sora|perplexity|wrtn|뤼튼)",
    re.IGNORECASE,
)

# 출처 기록(Content Credentials) 후보. 존재 확인일 뿐 검증이 아니다.
PROVENANCE_HINT_RE = re.compile(r"(c2pa|content\s*credentials|contentauth|provenance)", re.IGNORECASE)

# 범용 제작 도구. AI와 무관하며 작성 주체의 근거가 되지 않는다(규칙 R04).
GENERIC_TOOL_RE = re.compile(
    r"(microsoft\s*word|libreoffice|openoffice|hancom|한글|hwp|reportlab|pdfkit|wkhtmltopdf|"
    r"ghostscript|acrobat|pages|google\s*docs|pandoc|latex|pdftex|quartz|skia)",
    re.IGNORECASE,
)

# 메타데이터 중 '제작 도구'를 담는 키
TOOL_KEYS = {"producer", "creator", "creatortool", "application", "generator", "appversion"}
# 메타데이터 중 '사람'을 담는 키. 인증된 신원이 아니다.
AUTHOR_KEYS = {"author", "creator", "lastmodifiedby", "last_modified_by", "lastsavedby", "제작자", "작성자"}


@dataclass
class Observation:
    """관측된 사실 하나. 원래 값과 위치를 함께 보관한다(F03)."""

    scope: ProvenanceScope
    category: str
    raw_value: str
    normalized_value: str
    locator: Dict[str, Any]
    is_ai_specific: bool = False
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": str(self.scope),
            "category": self.category,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "locator": self.locator,
            "is_ai_specific": self.is_ai_specific,
            "detail": self.detail,
        }


@dataclass
class Check:
    """검사 하나의 수행 상태(F11). 무엇을 못 했는지가 결과의 일부다."""

    scope: ProvenanceScope
    check_type: str
    status: CheckStatus
    reason_code: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": str(self.scope),
            "check_type": self.check_type,
            "status": str(self.status),
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


@dataclass
class ScopeAssessment:
    """범위 하나에 대한 판정(제8.1장)."""

    scope: ProvenanceScope
    verdict: AIInvolvementVerdict
    actions: List[ProvenanceAction] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    observations: List[Observation] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": str(self.scope),
            "verdict": str(self.verdict),
            "actions": [str(a) for a in self.actions],
            "reason_codes": self.reason_codes,
            "observations": [o.to_dict() for o in self.observations],
            "limitations": self.limitations,
            "message": self.message,
        }


@dataclass
class AIProvenanceResult:
    assessments: List[ScopeAssessment] = field(default_factory=list)
    checks: List[Check] = field(default_factory=list)
    rule_version: str = RULE_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "assessments": [a.to_dict() for a in self.assessments],
            "checks": [c.to_dict() for c in self.checks],
            "notice": (
                "이 결과는 확인 가능한 기록의 분석이며, 기록이 없는 AI 사용을 배제하지 않습니다."
            ),
        }

    def verdict_for(self, scope: ProvenanceScope) -> Optional[AIInvolvementVerdict]:
        for assessment in self.assessments:
            if assessment.scope == scope:
                return assessment.verdict
        return None


# ---------------------------------------------------------------------------
# 사용자 표시 문구 (제11.1장)
# ---------------------------------------------------------------------------
MESSAGES = {
    AIInvolvementVerdict.VERIFIED_AI_RECORD: "해당 범위의 AI 관여에 관한 검증된 출처 기록이 있습니다.",
    AIInvolvementVerdict.AI_INDICATION_UNVERIFIED: (
        "수정 가능한 문서 속성에 AI 관련 표기가 있습니다. 진위는 확인되지 않았습니다."
    ),
    AIInvolvementVerdict.INCONCLUSIVE: "AI 작성 및 수정 여부를 판단할 수 없습니다.",
    AIInvolvementVerdict.UNAVAILABLE: "해당 범위는 분석할 수 없었습니다.",
}


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _scan_metadata(doc: NormalizedDocument) -> List[Observation]:
    """메타데이터에서 AI 표기와 제작 도구를 뽑는다. 둘은 성격이 전혀 다르다."""
    out: List[Observation] = []
    for key, value in (doc.metadata or {}).items():
        text = _normalize(value)
        if not text:
            continue
        lowered = str(key).lower()
        locator = {"kind": "metadata", "key": str(key)}

        ai_match = AI_TOOL_RE.search(text)
        if ai_match:
            # 도구 키인지 사람 키인지에 따라 뜻이 다르므로 구분해 남긴다.
            where = "제작 도구 속성" if lowered in TOOL_KEYS else (
                "작성자 속성" if lowered in AUTHOR_KEYS else "문서 속성"
            )
            out.append(
                Observation(
                    scope=ProvenanceScope.FILE_CONTAINER,
                    category="ai_indication_metadata",
                    raw_value=text,
                    normalized_value=ai_match.group(0).lower(),
                    locator=locator,
                    is_ai_specific=True,
                    detail=f"{where}에 AI 관련 표기가 있다. 문서 속성은 편집할 수 있어 진위가 확인되지 않는다.",
                )
            )
            continue

        if lowered in TOOL_KEYS and GENERIC_TOOL_RE.search(text):
            out.append(
                Observation(
                    scope=ProvenanceScope.FILE_CONTAINER,
                    category="producer_metadata",
                    raw_value=text,
                    normalized_value=_normalize(GENERIC_TOOL_RE.search(text).group(0)),
                    locator=locator,
                    is_ai_specific=False,
                    detail="기록된 제작 도구이다. 작성 주체를 보여주지 않는다.",
                )
            )
    return out


def _scan_provenance_candidates(doc: NormalizedDocument) -> List[Observation]:
    """출처 기록(C2PA 등) 후보를 찾는다. 찾았다는 사실만 기록한다."""
    out: List[Observation] = []
    if doc.structure.get("c2pa"):
        out.append(
            Observation(
                scope=ProvenanceScope.FILE_CONTAINER,
                category="provenance_manifest_candidate",
                raw_value="c2pa",
                normalized_value="c2pa",
                locator={"kind": "structure", "key": "c2pa"},
                is_ai_specific=False,
                detail="출처 기록 후보가 존재한다. 서명·자산 결합은 검증하지 않았다.",
            )
        )
    for key, value in (doc.metadata or {}).items():
        text = _normalize(value)
        if text and PROVENANCE_HINT_RE.search(text):
            out.append(
                Observation(
                    scope=ProvenanceScope.FILE_CONTAINER,
                    category="provenance_manifest_candidate",
                    raw_value=text,
                    normalized_value=_normalize(PROVENANCE_HINT_RE.search(text).group(0)).lower(),
                    locator={"kind": "metadata", "key": str(key)},
                    is_ai_specific=False,
                    detail="출처 기록 후보 문자열이다. 서명 검증기는 구현되지 않았다.",
                )
            )
    return out


def _body_readable(doc: NormalizedDocument) -> bool:
    return bool(doc.body_blocks())


def analyze_ai_provenance(doc: NormalizedDocument) -> AIProvenanceResult:
    """범위별로 AI 관여 흔적을 판정한다."""
    result = AIProvenanceResult()
    metadata_observations = _scan_metadata(doc)
    provenance_candidates = _scan_provenance_candidates(doc)

    # --- 검사 상태 --------------------------------------------------------
    result.checks.append(
        Check(
            scope=ProvenanceScope.FILE_CONTAINER,
            check_type="metadata",
            status=CheckStatus.SUCCEEDED if doc.metadata else CheckStatus.NOT_FOUND,
            detail="문서 속성 추출",
        )
    )
    body_blocked = bool(doc.structure.get("body_extraction_failed")) or not _body_readable(doc)
    result.checks.append(
        Check(
            scope=ProvenanceScope.DOCUMENT_TEXT,
            check_type="text_extract",
            status=CheckStatus.BLOCKED if body_blocked else CheckStatus.SUCCEEDED,
            reason_code="BODY_NOT_EXTRACTED" if body_blocked else "",
            detail="본문 추출",
        )
    )
    # 출처 검증기는 아직 없다. 후보를 찾았더라도 unsupported이며 not_found가 아니다.
    result.checks.append(
        Check(
            scope=ProvenanceScope.FILE_CONTAINER,
            check_type="provenance_validate",
            status=CheckStatus.UNSUPPORTED,
            reason_code="PROVENANCE_VALIDATOR_UNSUPPORTED",
            detail=(
                f"출처 기록 후보 {len(provenance_candidates)}건을 발견했으나 서명·자산 결합 검증기가 "
                "구현되지 않았다. 검증됨으로 표시하지 않는다."
                if provenance_candidates
                else "서명·자산 결합 검증기가 구현되지 않았다."
            ),
        )
    )

    # --- file_container 판정 ---------------------------------------------
    ai_indications = [o for o in metadata_observations if o.is_ai_specific]
    container_observations = metadata_observations + provenance_candidates
    if ai_indications:
        container_verdict = AIInvolvementVerdict.AI_INDICATION_UNVERIFIED
        container_reasons = ["AI_INDICATION_IN_EDITABLE_METADATA", "PROVENANCE_NOT_VALIDATED"]
    else:
        container_verdict = AIInvolvementVerdict.INCONCLUSIVE
        container_reasons = ["NO_AI_RECORD_FOUND"]
        if any(o.category == "producer_metadata" for o in container_observations):
            container_reasons.insert(0, "TOOL_METADATA_NOT_AUTHORSHIP")
    result.assessments.append(
        ScopeAssessment(
            scope=ProvenanceScope.FILE_CONTAINER,
            verdict=container_verdict,
            reason_codes=container_reasons,
            observations=container_observations,
            limitations=["PROVENANCE_VALIDATOR_UNSUPPORTED"],
            message=MESSAGES[container_verdict],
        )
    )

    # --- document_text 판정 ----------------------------------------------
    #
    # 본문에 연결된 검증 기록이 있어야 본문을 판정할 수 있다. 현재는 출처 검증기가
    # 없으므로 본문이 VERIFIED_AI_RECORD가 되는 경로 자체가 존재하지 않는다.
    # 파일 컨테이너의 AI 표기를 본문 근거로 끌어오지 않는 것이 이 분리의 목적이다.
    if body_blocked:
        text_verdict = AIInvolvementVerdict.UNAVAILABLE
        text_reasons = ["BODY_NOT_EXTRACTED"]
    else:
        text_verdict = AIInvolvementVerdict.INCONCLUSIVE
        text_reasons = ["NO_VERIFIED_RECORD_FOR_TEXT"]
        if ai_indications:
            # 컨테이너에 표기가 있어도 본문 귀속의 근거는 아니다.
            text_reasons.append("CONTAINER_INDICATION_NOT_TEXT_EVIDENCE")
    result.assessments.append(
        ScopeAssessment(
            scope=ProvenanceScope.DOCUMENT_TEXT,
            verdict=text_verdict,
            reason_codes=text_reasons,
            observations=[],
            limitations=["PROVENANCE_VALIDATOR_UNSUPPORTED"]
            + (["BODY_NOT_EXTRACTED"] if body_blocked else []),
            message=MESSAGES[text_verdict],
        )
    )

    # --- 삽입 이미지 ------------------------------------------------------
    image_count = int(doc.structure.get("image_count") or 0)
    if image_count:
        result.checks.append(
            Check(
                scope=ProvenanceScope.EMBEDDED_IMAGE,
                check_type="asset_provenance",
                status=CheckStatus.UNSUPPORTED,
                reason_code="ASSET_PROVENANCE_UNSUPPORTED",
                detail=f"삽입 이미지 {image_count}개의 개별 출처 검증은 구현되지 않았다.",
            )
        )
        result.assessments.append(
            ScopeAssessment(
                scope=ProvenanceScope.EMBEDDED_IMAGE,
                verdict=AIInvolvementVerdict.UNAVAILABLE,
                reason_codes=["ASSET_PROVENANCE_UNSUPPORTED"],
                limitations=["ASSET_PROVENANCE_UNSUPPORTED"],
                message=MESSAGES[AIInvolvementVerdict.UNAVAILABLE],
            )
        )
    return result
