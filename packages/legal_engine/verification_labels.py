"""인용별 '확인 완료' 라벨(v3 D4).

- VERIFIED_CITATION: 판례의 존재, 서지(법원·선고일·사건번호·사건명·재판형식), 직접 인용문 일치를 모두 확인했다.
  직접 인용문이 없으면 존재와 서지만 본다. 다수·반대의견 귀속이나 판시 방향에 문제가 있으면 붙이지 않는다.
- VERIFIED_PROVISION: 조문 존재와 문서가 주장한 내용(수치 포함, 주장 없음 포함)이 시행 버전과 일치한다.
  기준일이 없으면 현행 버전 기준으로 일치를 확인하고, 사건 기준일의 시행 버전 확인은 권고로만 덧붙인다.
- 사건 적용성은 이 라벨과 따로 APPLICABILITY_UNREVIEWED로 둔다.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from packages.common.enums import VerificationStatus

CURRENT_VERSION_ADVISORY = "현행 버전 기준 일치 — 사건 기준일의 시행 버전 확인 권고(판정 보류 사유 아님)"
STOP = (VerificationStatus.CONTRADICTED, VerificationStatus.NOT_FOUND)


def provision_label(levels: Dict[str, str], status: VerificationStatus,
                    as_of: Optional[str]) -> Tuple[VerificationStatus, Optional[str], str]:
    if status in STOP:
        return status, None, ""
    identity = levels.get("existence") == "VERIFIED" and levels.get("article", "VERIFIED") == "VERIFIED"
    if not identity or levels.get("content") not in ("VERIFIED", "NOT_ASSERTED"):
        return status, None, ""
    if levels.get("temporal") == "VERIFIED":
        return VerificationStatus.VERIFIED, "VERIFIED_PROVISION", ""
    if not as_of:
        return VerificationStatus.VERIFIED, "VERIFIED_PROVISION", CURRENT_VERSION_ADVISORY
    return status, None, ""


def citation_label(levels: Dict[str, str], status: VerificationStatus,
                   has_quote: bool) -> Tuple[VerificationStatus, Optional[str]]:
    demoted = VerificationStatus.PARTIALLY_VERIFIED if status == VerificationStatus.VERIFIED else status
    if status in STOP or levels.get("format") == "INVALID" or levels.get("opinion"):
        return demoted, None
    if levels.get("level1") != "VERIFIED" or levels.get("level2") != "VERIFIED":
        return demoted, None
    if has_quote and levels.get("level3") != "VERIFIED":
        return demoted, None
    return VerificationStatus.VERIFIED, "VERIFIED_CITATION"
