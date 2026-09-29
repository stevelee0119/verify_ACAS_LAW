"""Bounded, source-local contract calculations. No inferred legal payment obligation."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from packages.claim_engine.deterministic import Input, delay_penalty

NUMBER = r"\d[\d,]*(?:\.\d+)?"
DATE = r"(?P<year>(?:19|20)\d{2})\s*[.년-]\s*(?P<month>\d{1,2})\s*[.월-]\s*(?P<day>\d{1,2})(?:\s*[.일])?"
CONTRACT = re.compile(r"계약\s*번호\s*[:：|]?\s*(?P<id>[A-Za-z가-힣0-9]+(?:-[A-Za-z가-힣0-9]+)+-[A-Za-z0-9]+)"
                      r"(?=$|[\s.,:;()/]|(?:으로|로|의|에|을|를|은|는)(?:\s|$))")
AMOUNT = re.compile(r"계약\s*금액[ \t:：|\n]*(?P<value>" + NUMBER + r")\s*원")
RATES = [
    (re.compile(r"(?P<den>1[,]?000|100)\s*분의\s*(?P<num>" + NUMBER + r")"), None),
    (re.compile(r"(?P<num>" + NUMBER + r")\s*[/÷]\s*(?P<den>1[,]?000|100)(?!\d)"), None),
    (re.compile(r"(?P<num>" + NUMBER + r")\s*%"), Decimal(100)),
]
DATE_PATTERNS = [
    ("ORIGINAL_DEADLINE", re.compile(r"(?:최초|당초|원래)\s*납품\s*기한[은는:：|\s]*" + DATE)),
    ("AMENDED_DEADLINE", re.compile(r"(?:변경된|변경|연장된)\s*납품\s*기한[은는:：|\s]*" + DATE)),
    ("AMENDED_DEADLINE", re.compile(r"납품\s*기한을\s*" + DATE + r"[^\n.]{0,50}연장")),
    ("FINAL_DELIVERY", re.compile(r"최종\s*납품\s*완료일[은는:：|\s]*" + DATE)),
    ("FINAL_DELIVERY", re.compile(DATE + r"[ \t\d:|]*(?:마지막\s*잔량|전량)[^\n]{0,70}(?:인수|검사\s*완료)")),
]
APPROVAL = re.compile(r"변경\s*계약\s*승인\s*(?:문서|번호)\s*[:：|]\s*(?P<value>[가-힣A-Za-z0-9]+(?:-[가-힣A-Za-z0-9]+){2,})")
COUNT = re.compile(r"다음\s*날[^\n]{0,180}까지\s*지체\s*일수[는:：\s]*(?P<value>\d+)일[^\n]{0,25}집계")
POLICY = "SOURCE_STATED_CALENDAR_DAYS_EXCLUDE_DEADLINE_INCLUDE_COMPLETION"


def _decimal(value):
    return Decimal(value.replace(",", ""))


def extract_source_facts(source):
    text = source["text"]
    facts = []

    def add(role, value, match):
        facts.append({"role": role, "value": str(value), "source_ref": {
            **{k: source.get(k) for k in ("source_id", "file_id", "sha256", "revision", "modified_time", "page")},
            "chunk_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "span": list(match.span()), "quote": match.group()}})

    for match in AMOUNT.finditer(text):
        add("PRINCIPAL", _decimal(match["value"]), match)
    for pattern, denominator in RATES:
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 80):match.end()]
            if not re.search(r"지체상금|계약금액", context):
                continue
            rate = _decimal(match["num"]) / (denominator or _decimal(match["den"]))
            if Decimal(0) <= rate <= Decimal(1):
                add("DAILY_RATE", rate, match)
    for role, pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = date(int(match["year"]), int(match["month"]), int(match["day"]))
            except ValueError:
                continue
            add(role, value.isoformat(), match)
    for role, pattern in (("APPROVAL_ID", APPROVAL), ("STATED_DAYS", COUNT)):
        for match in pattern.finditer(text):
            add(role, match["value"], match)
    return facts


def review_contract_calculations(document, sources):
    document_ids = {m["id"] for m in CONTRACT.finditer(document)}
    groups = defaultdict(list)
    for source in sources:
        if source.get("file_id") and source.get("sha256"):
            groups[(source["file_id"], source["sha256"], str(source.get("revision") or ""))].append(source)
    calculations, all_facts, limitations = [], [], []
    for (file_id, digest, revision), chunks in groups.items():
        ids = {m["id"] for s in chunks for m in CONTRACT.finditer(s["text"])}
        if len(ids) != 1 or not ids <= document_ids:
            limitations.append({"file_id": file_id, "reason": "CONTRACT_ID_NOT_UNAMBIGUOUSLY_LINKED"})
            continue
        facts = [f for chunk in chunks for f in extract_source_facts(chunk)]
        all_facts.extend(facts)
        by_role = defaultdict(dict)
        for fact in facts:
            by_role[fact["role"]].setdefault(fact["value"], fact)
        roles = ("PRINCIPAL", "DAILY_RATE", "AMENDED_DEADLINE", "FINAL_DELIVERY", "STATED_DAYS")
        if not all(len(by_role[role]) == 1 for role in roles):
            limitations.append({"file_id": file_id, "reason": "MISSING_OR_CONFLICTING_CALCULATION_INPUTS",
                                "roles": [r for r in roles if len(by_role[r]) != 1]})
            continue
        chosen = {r: next(iter(by_role[r].values())) for r in roles}
        due, end = (date.fromisoformat(chosen[r]["value"]) for r in ("AMENDED_DEADLINE", "FINAL_DELIVERY"))
        principal, rate = (_decimal(chosen[r]["value"]) for r in ("PRINCIPAL", "DAILY_RATE"))
        if end < due or principal <= 0:
            limitations.append({"file_id": file_id, "reason": "INVALID_CALCULATION_INPUTS"})
            continue
        def value(role, parsed, unit=""):
            ref = chosen[role]["source_ref"]
            return Input(role, parsed, unit, source_span=f"{file_id}:{digest}:{ref['span']}")
        calc = delay_penalty(contract_amount=value("PRINCIPAL", principal, "원"),
            daily_rate=value("DAILY_RATE", rate), due_date=value("AMENDED_DEADLINE", due),
            delivery_date=value("FINAL_DELIVERY", end))
        days = int(calc.outputs["delay_days"])
        key = "|".join((next(iter(ids)), file_id, digest, revision))
        calculations.append({**calc.to_dict(),
            "calculation_id": hashlib.sha256(key.encode()).hexdigest()[:24],
            "entity_key": next(iter(ids)), "calculation_status": "RECALCULATED",
            "counting_policy": POLICY, "legal_applicability": "REVIEW_REQUIRED",
            "stated_days": int(chosen["STATED_DAYS"]["value"]),
            "stated_days_match": days == int(chosen["STATED_DAYS"]["value"]),
            "advisory_only": True, "source_refs": [f["source_ref"] for f in chosen.values()],
            "unresolved_assumptions": ["source_authenticity", "contract_exception_rules", "partial_deliveries", "rounding_rule"],
            "note": "참고자료의 날짜 단위 집계 방식에 따른 조건부 검산이다. 귀책·제외 기간·분할납품·감액·공제 적법성은 확정하지 않는다."})
    return {"facts": all_facts, "calculations": calculations, "limitations": limitations}


def link_observations(observations, sources, claims):
    by_id = {s["source_id"]: s for s in sources}
    issues = []
    for item in observations:
        source = by_id[item["source_id"]]
        quote = item["source_quote"]
        source_text = source.get("text", "")
        if quote in source_text:
            idx = source_text.index(quote)
            span = [idx, idx + len(quote)]
        else:
            span = [0, len(quote)]
        refs = {"source_id": item["source_id"], "file_id": source.get("file_id"),
                "sha256": source.get("sha256"), "revision": source.get("revision"),
                "span": span}
        # 마침표·공백·문장부호 차이를 허용하여 관찰을 해당 claim_id에 유연하게 연결
        def _clean_str(s):
            return re.sub(r"[\s.,·~'\"`]+", "", s or "")
        cleaned_claim_quote = _clean_str(item.get("claim_quote", ""))
        claim_ids = []
        if item.get("claim_id") and any(c.get("claim_id") == item["claim_id"] for c in claims):
            claim_ids.append(item["claim_id"])
        for c in claims:
            c_text = c.get("text", "")
            if c.get("claim_id") not in claim_ids:
                if item["claim_quote"] in c_text or (cleaned_claim_quote and cleaned_claim_quote in _clean_str(c_text)):
                    claim_ids.append(c["claim_id"])
        issue_key = "|".join((str(source.get("sha256")), item["claim_quote"], item["source_quote"]))
        issues.append({"issue_id": hashlib.sha256(issue_key.encode()).hexdigest()[:24],
            "claim_ids": claim_ids, "source_refs": [refs], "relationship": item["relationship"],
            "verification_scope": "SOURCE_TEXT_COMPARISON", "advisory_only": True,
            "semantic_validity": "NOT_INDEPENDENTLY_VERIFIED"})
        # A historical deadline and its subsequent amendment can both be true.
        original = re.search(r"(?:최초|당초|원래)[^.]{0,30}(?:기한|납기)", item["claim_quote"])
        amended = re.search(r"(?:변경|연장)", item["source_quote"])
        if original and amended and "CONTRADICTS" == item["relationship"]:
            item["model_relationship"] = item["relationship"]
            item["relationship"] = "CONTEXT"
            item["relationship_detail"] = "AMENDS_DEADLINE_REVIEW_REQUIRED"
            item["explanation"] = "최초 기한과 변경 기한은 병존할 수 있어 단순 모순으로 확정하지 않는다. " + item["explanation"]
            issues[-1].update(relationship="CONTEXT", relationship_detail=item["relationship_detail"])
    return issues
