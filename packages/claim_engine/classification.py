"""주장 문장의 위치(구간)와 유형 분류.

같은 문장 모양이라도 문서 안의 위치에 따라 검증 대상이 아니다. 제목·목차·작성 안내·
시험 안내는 주장이 아니고, 문서 속 지시문은 공격 탐지 대상이며, 따옴표 속 인용은
화자의 주장이 아니다. 먼저 구간을 가르고, 그다음 유형을 정한다.

유형
  FACT                  사실 서술(과거 사건, 자료의 존재·내용, 수치)
  LEGAL_RULE            법령 문언·조문 내용의 서술
  CASE_HOLDING          판례 취지 서술
  LEGAL_INTERPRETATION  해석례·유권해석 서술
  LEGAL_ARGUMENT        당사자의 법적 평가 주장(위법·무효·취소되어야 함 등)
  OPINION               평가·의견(생각한다·타당하다 등)
  DOCUMENT_EXISTENCE    증거·첨부 존재 서술
  CALCULATION           금액·이율 계산
  DOCUMENT_META         제목·목차·작성/시험 안내
  ADVERSARIAL_INSTRUCTION 검증기·모델에 대한 명령
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from packages.common.enums import ClaimType

TERMINAL_RE = re.compile(r"(다|요|음|함|임|까|죠|오|라|니다|습니다)\s*[.!?。]?\s*[\"”’」』)]*\s*$")
GUIDE_RE = re.compile(
    r"(테스트|시험\s*(?:용|자료|문서|안내)|검증용|합성\s*(?:자료|문서)|예시\s*(?:자료|문서)|샘플|유의\s*사항|작성\s*요령|"
    r"(?:본|이)\s*(?:문서|자료|파일|서면)(?:는|은)\s*[^.]{0,40}(?:위하여|위해|목적|작성|구성|포함|만든|만들))"
)
HEADING_PREFIX_RE = re.compile(r"^\s*(?:[IVX]+\.|\d+(?:\.\d+)*[.)]|[가-하][.)]|제\s*\d+\s*[장절]|[A-Z]-\d+|[■□▶▷◆◇●○※]|\[[^\]]{1,20}\])")
QUOTE_SPAN_RE = re.compile(r"[\"“「『][^\"”」』]{8,}[\"”」』]")

OPINION_RE = re.compile(r"(생각한다|사료된다|보아야\s*한다|타당하다|바람직하다|판단된다|여겨진다|믿는다|보인다|의문이다|의심된다)")
LEGAL_ARGUMENT_RE = re.compile(
    r"(위법(?:하다|하므로|한\s*처분|이다)|무효(?:이다|이므로|임|로\s*보아야)|취소(?:되어야|하여야|를\s*구한다)|"
    r"부당하다|적법하다|위반(?:하였다|한다|된다|하여)|재량권[^.]{0,10}(?:일탈|남용)|하자가\s*(?:있|존재)|"
    r"요건을\s*(?:갖추지|충족하지)|효력이\s*없|책임이\s*있|배상할\s*의무|청구권이\s*있)"
)
PAST_FACT_RE = re.compile(r"(였다|했다|됐다|되었다|었다|았다|하였다|받았다|보냈다|작성했다|작성하였다|기재되어\s*있다)")
EXISTENCE_FACT_RE = re.compile(r"(있다|없다|존재한다|기재되어|적혀|입증한다|증명한다|확인된다|나타난다|수정됐|수정되었|변경됐|변경되었)")
EVIDENCE_NOUN_RE = re.compile(r"(녹음|녹취|파일|해시|점수표|사진|영상|기록|문서|자료|보고서|계약서|영수증|진술서|메시지|원본|사본)")


def segment_kind(text: str, *, block_type: str = "paragraph", source_layer: str = "visible_text",
                 table_ref: Any = None) -> str:
    """문장이 놓인 구간의 종류."""
    stripped = text.strip()
    if source_layer == "ocr_layer":
        return "OCR_TEXT"
    if block_type == "table" or table_ref:
        return "TABLE"
    if GUIDE_RE.search(stripped):
        return "DOCUMENT_GUIDE"
    if not TERMINAL_RE.search(stripped) and (len(stripped) <= 80 or HEADING_PREFIX_RE.match(stripped)):
        return "HEADING"
    quoted = sum(len(m.group(0)) for m in QUOTE_SPAN_RE.finditer(stripped))
    if quoted >= 0.6 * len(stripped):
        return "QUOTATION"
    return "BODY"


def is_adversarial_instruction(text: str) -> bool:
    """검증기·모델에 명령하는 문구인지. 지시문을 설명·언급하는 문구는 제외한다."""
    from packages.adversarial_engine.classifier import classify
    from packages.common.enums import AdversarialClass

    result = classify(text)
    return (result.label != AdversarialClass.BENIGN_CONTENT
            and bool(result.features.get("imperative")) and not result.features.get("descriptive_mention"))


def classify_sentence(sentence: str, segment: str, base_rules) -> ClaimType:
    """구간을 먼저 보고, 본문일 때만 문장 유형 규칙을 적용한다.

    base_rules는 기존 규칙(판례 취지·법령 문언·해석·증거 존재·계산)을 담은 함수다.
    """
    if is_adversarial_instruction(sentence):
        return ClaimType.ADVERSARIAL_INSTRUCTION
    if segment in ("HEADING", "DOCUMENT_GUIDE"):
        return ClaimType.DOCUMENT_META
    if OPINION_RE.search(sentence):
        return ClaimType.OPINION
    rule_based = base_rules(sentence)
    if rule_based in (ClaimType.CASE_HOLDING, ClaimType.LEGAL_INTERPRETATION, ClaimType.LEGAL_RULE):
        return rule_based
    if LEGAL_ARGUMENT_RE.search(sentence):
        return ClaimType.LEGAL_ARGUMENT
    if rule_based in (ClaimType.DOCUMENT_EXISTENCE, ClaimType.CALCULATION):
        return rule_based
    if PAST_FACT_RE.search(sentence) or (EXISTENCE_FACT_RE.search(sentence) and EVIDENCE_NOUN_RE.search(sentence)):
        return ClaimType.FACT
    return rule_based


def document_kind(first_lines: Iterable[str]) -> str:
    """앞부분 몇 줄로 문서 종류를 가늠한다. 판단 근거가 없으면 UNKNOWN."""
    head = " ".join(list(first_lines)[:8])
    for kind, pattern in (
        ("TEST_MATERIAL", r"테스트|시험\s*자료|검증용|합성"),
        ("COMPLAINT", r"소\s*장"), ("BRIEF", r"준\s*비\s*서\s*면"), ("ANSWER", r"답\s*변\s*서"),
        ("APPEAL", r"항소이유서|상고이유서"), ("OPINION_LETTER", r"의견서"),
        ("CRIMINAL_COMPLAINT", r"고소장|고발장"), ("CONTRACT", r"계약서"), ("REPORT", r"보고서"),
    ):
        if re.search(pattern, head):
            return kind
    return "UNKNOWN"


def link_claim_evidence(claims: List[Any], attachment_items: List[Dict[str, Any]]) -> None:
    """주장과 그 근거 자료의 첨부 상태를 잇는다. 자료가 없으면 '검증되지 않은 사실'로 둔다."""
    by_claim: Dict[str, List[Dict[str, Any]]] = {}
    by_reference: Dict[str, Dict[str, Any]] = {}
    for item in attachment_items:
        for claim_id in item.get("linked_claim_ids") or []:
            by_claim.setdefault(claim_id, []).append(item)
        if item.get("reference"):
            by_reference[re.sub(r"\s+", "", str(item["reference"]))] = item
    for claim in claims:
        linked = list(by_claim.get(claim.claim_id, []))
        for reference in claim.evidence_references or []:
            hit = by_reference.get(re.sub(r"\s+", "", str(reference.get("raw_text") or "")))
            if hit and hit not in linked:
                linked.append(hit)
        if not linked:
            continue
        statuses = {item["status"] for item in linked}
        claim.attributes["evidence_items"] = [{"name": i["name"], "status": i["status"]} for i in linked]
        claim.attributes["evidence_relationship"] = (
            "EVIDENCE_NOT_PROVIDED" if "NOT_PROVIDED" in statuses else
            "REFERENCE_MISSING" if "REFERENCE_MISSING" in statuses else
            "ATTACHED_NOT_ASSESSED" if "ATTACHED" in statuses else "UNVERIFIED")
        if claim.type == ClaimType.FACT and statuses & {"NOT_PROVIDED", "REFERENCE_MISSING"}:
            claim.attributes["fact_status"] = "UNVERIFIED_FACT"
