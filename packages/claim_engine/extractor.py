"""제11.1장 Claim Extraction, 제11.3장 Entity Resolution, 제11.4장 Timeline.

Rule 기반으로 먼저 구조화하고, 의미 판단이 필요한 부분만 LLM에 위임한다.
단순 의견(OPINION)은 사실 검증 대상에서 기본 제외한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from packages.common.enums import ClaimType, EntityType
from packages.common.schemas import Claim, Citation, Entity, Event, NormalizedDocument
from packages.common.textutil import sentences

from .calculation import AMOUNT_RE, parse_amounts

# --- Claim 유형 판별 규칙 ----------------------------------------------------
OPINION_RE = re.compile(r"(생각한다|사료된다|보아야\s*한다|타당하다|부당하다|바람직하다|판단된다|여겨진다|믿는다)")
LEGAL_RULE_RE = re.compile(r"(제\s*\d+\s*조|법률\s*제\s*\d+\s*호|규정하고\s*있다|정하고\s*있다|따르면)")
CASE_HOLDING_RE = re.compile(r"(판시하였다|판시한|판결하였다|설시하였다|입장이다|취지이다|보고\s*있다)")
DOCUMENT_EXISTENCE_RE = re.compile(r"(갑\s*제?\s*\d+\s*호증|을\s*제?\s*\d+\s*호증|증\s*제?\s*\d+\s*호|첨부(?:한|된)|제출(?:한|하였다))")
CALCULATION_RE = re.compile(r"(합계|총액|이자|지연손해금|비율|%|원을\s*지급)")
INTERPRETATION_RE = re.compile(r"(해석된다|해석하여야|유권해석|법령해석)")
FACT_RE = re.compile(r"(하였다|했다|이다|였다|당하였다|지급하였다|체결하였다|발생하였다|근무하였다)")

DATE_RE = re.compile(
    r"(?P<y>(?:19|20)\d{2})\s*[.\-년]\s*(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*[일]?"
)
EVENT_KIND_RE = [
    ("CONTRACT", re.compile(r"(계약(?:을)?\s*체결|약정|합의)")),
    ("TERMINATION", re.compile(r"(해지|해제|종료|파기)")),
    ("PAYMENT", re.compile(r"(지급|송금|입금|변제)")),
    ("INCORPORATION", re.compile(r"(설립|법인등기|개업)")),
    ("FILING", re.compile(r"(제출|접수|신청|고소|고발|기소)")),
    ("DECISION", re.compile(r"(선고|판결|결정|처분)")),
    ("INCIDENT", re.compile(r"(사고|발생|폭행|상해|침해|위반)")),
]

PARTY_ROLE_WORDS = {
    "원고", "피고", "피고인", "참고인", "피의자", "증인", "고소인", "고발인",
    "신청인", "피신청인", "채권자", "채무자", "소외", "망",
}
ORG_WORDS = {"주식회사", "유한회사", "합자회사", "재단법인", "사단법인", "법인"}

# 당사자 표기 뒤의 이름. 뒤에 법인 표시가 오면 사람 이름이 아니다.
PERSON_CONTEXT_RE = re.compile(
    r"(?:원고|피고인|피고|참고인|피의자|증인|고소인|고발인|신청인|피신청인|채권자|채무자|망|소외)\s*"
    r"(?!주식회사|유한회사|합자회사|재단법인|사단법인)"
    r"([가-힣]{2,4}?)(?:은|는|이|가|을|를|과|와|의|에게|에|도)?(?![가-힣])"
)
COMPANY_CONTEXT_RE = re.compile(
    r"(?<![가-힣])([가-힣A-Za-z0-9]{2,10})\s*(?:주식회사|㈜)|(?:주식회사|㈜)\s+([가-힣A-Za-z0-9]{1,20})"
)
COURT_CONTEXT_RE = re.compile(r"([가-힣]{2,10}(?:지방|고등|가정|행정|회생|특허|군사)?법원|대법원|헌법재판소)")


def classify_claim(sentence: str) -> ClaimType:
    if OPINION_RE.search(sentence):
        return ClaimType.OPINION
    if CASE_HOLDING_RE.search(sentence):
        return ClaimType.CASE_HOLDING
    if INTERPRETATION_RE.search(sentence):
        return ClaimType.LEGAL_INTERPRETATION
    if LEGAL_RULE_RE.search(sentence):
        return ClaimType.LEGAL_RULE
    if DOCUMENT_EXISTENCE_RE.search(sentence):
        return ClaimType.DOCUMENT_EXISTENCE
    if CALCULATION_RE.search(sentence) and AMOUNT_RE.search(sentence):
        return ClaimType.CALCULATION
    if FACT_RE.search(sentence):
        return ClaimType.FACT
    return ClaimType.OPINION


def extract_claims(doc: NormalizedDocument, citations: Optional[List[Citation]] = None) -> List[Claim]:
    """표시 본문에서 Claim을 추출한다."""
    citations = citations or []
    by_block: Dict[str, List[Citation]] = {}
    for citation in citations:
        if citation.block_id:
            by_block.setdefault(citation.block_id, []).append(citation)

    claims: List[Claim] = []
    for block in doc.visible_blocks():
        for sentence in sentences(block.text):
            if len(sentence) < 10:
                continue
            claim_type = classify_claim(sentence)
            related = [
                c.citation_id
                for c in by_block.get(block.block_id, [])
                if c.raw_text and c.raw_text[:12] in sentence
            ]
            claims.append(
                Claim.create(
                    claim_type,
                    sentence,
                    document_id=doc.document_id,
                    block_id=block.block_id,
                    page=block.page,
                    citation_ids=related,
                    attributes={"length": len(sentence)},
                )
            )
    return claims


def extract_entities(doc: NormalizedDocument) -> List[Entity]:
    """사람·법인·법원 등을 추출한다. 동일 대상 통합은 resolve_entities가 담당한다."""
    found: Dict[Tuple[str, str], Entity] = {}

    def add(entity_type: EntityType, name: str, block, span: Tuple[int, int]) -> None:
        name = name.strip()
        if not name:
            return
        key = (str(entity_type), name)
        entity = found.get(key)
        if entity is None:
            entity = Entity.create(entity_type, name)
            found[key] = entity
        entity.mentions.append(
            {"document_id": doc.document_id, "block_id": block.block_id, "page": block.page, "span": list(span)}
        )

    for block in doc.visible_blocks():
        for m in PERSON_CONTEXT_RE.finditer(block.text):
            add(EntityType.PERSON, m.group(1), block, (m.start(1), m.end(1)))
        for m in COMPANY_CONTEXT_RE.finditer(block.text):
            name = (m.group(1) or m.group(2) or "").strip()
            if name in PARTY_ROLE_WORDS or name in ORG_WORDS:
                continue
            add(EntityType.COMPANY, name, block, (m.start(), m.end()))
        for m in COURT_CONTEXT_RE.finditer(block.text):
            add(EntityType.COURT, m.group(1), block, (m.start(1), m.end(1)))
        for amount in parse_amounts(block.text, block_id=block.block_id, page=block.page):
            add(EntityType.MONEY, amount.raw, block, (amount.start, amount.end))
    return list(found.values())


def resolve_entities(entities: List[Entity]) -> List[Entity]:
    """제11.3장. 동일 대상 가능성이 높은 표현을 프로젝트 단위로 통합한다.

    Confidence가 낮은 Merge는 사용자 확인 대상으로 남긴다.
    """
    merged: List[Entity] = []
    for entity in sorted(entities, key=lambda e: (-len(e.name), e.name)):
        target = None
        for candidate in merged:
            if candidate.type != entity.type:
                continue
            if candidate.name == entity.name:
                target = candidate
                break
            if entity.name in candidate.name or candidate.name in entity.name:
                target = candidate
                break
        if target is None:
            merged.append(entity)
            continue
        confidence = 1.0 if target.name == entity.name else 0.7
        if entity.name not in target.aliases and entity.name != target.name:
            target.aliases.append(entity.name)
        target.mentions.extend(entity.mentions)
        target.merge_confidence = min(target.merge_confidence, confidence)
        target.needs_user_confirmation = target.merge_confidence < 0.9
    return merged


def extract_events(doc: NormalizedDocument) -> List[Event]:
    """제11.4장 Timeline 입력. 날짜와 같은 문장의 사건 서술을 결합한다."""
    events: List[Event] = []
    for block in doc.visible_blocks():
        for sentence in sentences(block.text):
            for m in DATE_RE.finditer(sentence):
                try:
                    value = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
                except ValueError:
                    continue
                kind = "GENERIC"
                for name, regex in EVENT_KIND_RE:
                    if regex.search(sentence):
                        kind = name
                        break
                events.append(
                    Event.create(
                        value,
                        sentence.strip()[:300],
                        document_id=doc.document_id,
                        block_id=block.block_id,
                        page=block.page,
                        event_kind=kind,
                        raw_date_text=m.group(0),
                    )
                )
    return events
