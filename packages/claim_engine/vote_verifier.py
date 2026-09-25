# -*- coding: utf-8 -*-
"""표결 인원 및 정족수 정합성 검증 엔진 (COUNT / VOTE_CONTRADICTION).

징계위원회, 이사회, 총회 등 의결 절차에서 재적 인원, 출석 인원,
찬성·반대·기권 인원 간의 산술적/논리적 모순(출석/표결 인원 > 재적 인원 등)을 검증한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "claim_engine.vote_verifier"

# 예: "재적 5명 중 ... 찬성 4, 반대 2", "재적 5명 전원 출석, 찬성 4·반대 2", "재적위원 5명 ... 찬성 4명, 반대 2명"
VOTE_PATTERN_RE = re.compile(
    r"(?:재적|총원|정원)\s*(?:위원|의원|이사|인원|위원수)?\s*(?P<total>\d{1,4})\s*명[^.\n]{0,150}?"
    r"찬성\s*(?P<yes>\d{1,4})\s*(?:명|표|인)?[^.\n]{0,30}?"
    r"반대\s*(?P<no>\d{1,4})\s*(?:명|표|인)?"
    r"(?:[^.\n]{0,30}?기권\s*(?P<abstain>\d{1,4})\s*(?:명|표|인)?)?"
)


def verify_vote_counts(doc: NormalizedDocument) -> List[Finding]:
    """문서 내 의결 및 표결 인원수의 산술적 정합성을 검증한다."""
    findings: List[Finding] = []
    blocks = doc.body_blocks()
    if not blocks:
        return findings

    # 단일 블록 및 인접 2~3개 블록 결합 텍스트 검사 단위 생성
    units: List[Tuple[str, Any]] = []
    for i in range(len(blocks)):
        units.append((blocks[i].text, blocks[i]))
        if i + 1 < len(blocks):
            joined_2 = f"{blocks[i].text} {blocks[i+1].text}"
            units.append((joined_2, blocks[i]))
        if i + 2 < len(blocks):
            joined_3 = f"{blocks[i].text} {blocks[i+1].text} {blocks[i+2].text}"
            units.append((joined_3, blocks[i]))

    seen_matches = set()
    for text, block in units:
        if not text:
            continue

        for m in VOTE_PATTERN_RE.finditer(text):
            total_members = int(m.group("total"))
            yes_votes = int(m.group("yes"))
            no_votes = int(m.group("no"))
            abstain_votes = int(m.group("abstain")) if m.group("abstain") else 0

            match_key = (total_members, yes_votes, no_votes, abstain_votes)
            if match_key in seen_matches:
                continue
            seen_matches.add(match_key)

            cast_votes = yes_votes + no_votes + abstain_votes

            if cast_votes > total_members:
                matched_str = m.group(0)
                features = {
                    "deterministic_rule": True,
                    "total_members": total_members,
                    "yes_votes": yes_votes,
                    "no_votes": no_votes,
                    "abstain_votes": abstain_votes,
                    "cast_votes": cast_votes,
                    "excess_votes": cast_votes - total_members,
                    "rule_id": "claim_engine.vote_verifier:VOTE_COUNT_EXCEEDED",
                }
                findings.append(
                    Finding.create(
                        type=FindingType.FACT_CONTRADICTION,
                        status=VerificationStatus.CONTRADICTED,
                        severity=Severity.HIGH,
                        evidence_grade=EvidenceGrade.A,
                        title=f"표결 인원수 모순: 표결 합계 {cast_votes}명 > 재적 {total_members}명",
                        detail=(
                            f"본문에 기재된 의결 내용에서 재적 인원은 {total_members}명이나, "
                            f"표결 인원(찬성 {yes_votes}명 + 반대 {no_votes}명"
                            + (f" + 기권 {abstain_votes}명" if abstain_votes else "")
                            + f" = 총 {cast_votes}명)이 재적 인원을 초과하여 산술적 모순이 발생한다."
                        ),
                        confidence=1.0,
                        confidence_features=features,
                        document_id=doc.document_id,
                        block_id=block.block_id,
                        page=block.page,
                        engine=ENGINE_NAME,
                        tags=["FACT", "COUNT", "VOTE_CONTRADICTION", "ARITHMETIC"],
                        evidence=[
                            Evidence.create(
                                description="재적 인원 초과 표결 모순",
                                grade=EvidenceGrade.A,
                                document_id=doc.document_id,
                                block_id=block.block_id,
                                page=block.page,
                                excerpt=matched_str,
                                supports=True,
                            )
                        ],
                    )
                )

    return findings
