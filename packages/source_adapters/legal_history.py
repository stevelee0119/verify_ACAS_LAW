"""Effective-version and provision parsing for the official eflaw contract.

Contracts checked against open.law.go.kr/LSO/openApi/guideResult.do:
lsEfYdListGuide, lsEfYdInfoGuide, lsEfYdJoListGuide (2026-09-18).
lsHistory is HTML-only; eflaw with nw=1,2,3 provides structured history.
An MST identifies an amendment; MST + efYd identifies an effective version.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any


def legal_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text) or re.fullmatch(
        r"(\d{4})[-.]\s*(\d{1,2})[-.]\s*(\d{1,2})\.?", text
    )
    if not match:
        return None
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


def today_korea() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("br", "p", "div", "li"):
            self.parts.append("\n")


def body_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(filter(None, (body_text(v) for v in value)))
    if value is None:
        return ""
    if not isinstance(value, (str, int)):
        raise ValueError("Unsupported body text shape")
    parser = _Text()
    parser.feed(unescape(str(value)))
    return "".join(parser.parts).strip()


def objects(value: Any) -> list[dict]:
    if value is None or value == "":
        return []
    rows = value if isinstance(value, list) else [value]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Unsupported collection shape")
    return rows


def provision_number(value: Any) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    match = re.fullmatch(r"(?:제)?\s*(\d+)\s*(?:조|항|호)?(?:\s*의\s*(\d+))?[.)]?", text)
    if not match:
        return None
    return str(int(match[1])) + (f"의{int(match[2])}" if match[2] else "")


def select_version(records: list[dict], as_of: str) -> dict:
    """Select a textual version only; never infer substantive applicability."""
    when = legal_date(as_of)
    if not when:
        raise ValueError("A valid explicit reference date is required")
    if not records:
        raise ValueError("No historical versions were returned")
    identities = {str(r.get("law_id") or "").lstrip("0") for r in records}
    if len(identities) != 1 or "" in identities:
        raise ValueError("Ambiguous or missing law identity")
    unique: dict[tuple, dict] = {}
    for row in records:
        start = legal_date(row.get("effective_from"))
        promulgated = legal_date(row.get("promulgation_date"))
        mst = str(row.get("version_id") or "")
        if not start or not promulgated or not mst.isdigit():
            raise ValueError("History contains missing or invalid version dates/identifiers")
        key = (mst, start)
        if key in unique and unique[key] != row:
            raise ValueError("Conflicting duplicate historical version")
        unique[key] = row
    eligible = [r for r in unique.values() if r["effective_from"] <= when]
    if not eligible:
        raise ValueError("No effective version covers the requested date")
    latest = max(r["effective_from"] for r in eligible)
    choices = [r for r in eligible if r["effective_from"] == latest]
    if len(choices) != 1:
        raise ValueError("Multiple versions share the requested effective boundary")
    chosen = dict(choices[0])
    if chosen["promulgation_date"] > when:
        raise ValueError("Retroactive commencement requires legal review")
    if "폐지" in str(chosen.get("amendment_type") or ""):
        raise ValueError("Repeal boundary requires legal review")
    next_dates = [r["effective_from"] for r in unique.values() if r["effective_from"] > latest]
    chosen.update(
        requested_as_of=when, effective_until=min(next_dates) if next_dates else None,
        version_selection="EXACT", history_complete=True,
        version_history=[{k: r.get(k) for k in (
            "law_id", "version_id", "effective_from", "promulgation_date", "amendment_type"
        )} for r in sorted(unique.values(), key=lambda r: r["effective_from"])],
    )
    return chosen


def _children(raw: dict, key: str, number_key: str, text_key: str, level: str) -> list[dict]:
    out = []
    for item in objects(raw.get(key)):
        number = (str(item.get(number_key) or "").rstrip(".) ") if level == "subitem"
                  else provision_number(item.get(number_key)))
        node = {"number": number, "text": body_text(item.get(text_key)), "raw": item}
        if not number and not (level == "paragraph" and number_key not in item):
            raise ValueError(f"Missing {level} number")
        if level == "paragraph":
            node["items"] = _children(item, "호", "호번호", "호내용", "item")
        if level == "item":
            node["subitems"] = _children(item, "목", "목번호", "목내용", "subitem")
        out.append(node)
    return out


def parse_law_body(payload: Any, selected: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid law detail response")
    root = payload.get("법령") or payload.get("LawService")
    if not isinstance(root, dict):
        raise ValueError("Missing law detail root")
    basic = root.get("기본정보")
    if not isinstance(basic, dict):
        raise ValueError("Missing law detail identity")
    identity = str(basic.get("법령ID") or "").lstrip("0")
    if identity != str(selected.get("law_id") or "").lstrip("0") or not identity:
        raise ValueError("Detail law identity differs from the selected history")
    for raw_key, normalized in (("시행일자", "effective_from"), ("공포일자", "promulgation_date")):
        if legal_date(basic.get(raw_key)) != selected.get(normalized):
            raise ValueError("Detail dates differ from the selected effective version")
    for key in ("법령일련번호", "MST"):
        if basic.get(key) is not None and str(basic[key]) != str(selected["version_id"]):
            raise ValueError("Detail MST differs from requested MST")
    if selected.get("promulgation_number") and str(basic.get("공포번호")) != selected["promulgation_number"]:
        raise ValueError("Detail promulgation number differs from selected history")
    if basic.get("공포법령여부") == "Y":
        raise ValueError("Promulgation text cannot establish effective text")
    section = root.get("조문")
    if not isinstance(section, dict) or "조문단위" not in section:
        raise ValueError("Missing complete article body")
    articles = []
    for raw in objects(section["조문단위"]):
        if raw.get("조문여부") in ("전문", "N"):
            continue
        number = provision_number(raw.get("조문번호"))
        branch = str(raw.get("조문가지번호") or "0")
        if not number or not branch.isdigit():
            raise ValueError("Invalid article number")
        if int(branch):
            number += f"의{int(branch)}"
        text = body_text(raw.get("조문내용"))
        deleted = raw.get("조문제개정유형") == "삭제" or bool(re.fullmatch(
            r"(?:제\s*\d+\s*조(?:의\d+)?\s*(?:\([^)]*\))?\s*)?삭제(?:\s*<[^>]*>)?", text))
        articles.append({
            "number": number, "title": body_text(raw.get("조문제목")),
            "text": text, "deleted": deleted,
            "effective_from": legal_date(raw.get("조문시행일자")),
            "effective_date_raw": raw.get("조문시행일자"),
            "paragraphs": _children(raw, "항", "항번호", "항내용", "paragraph"),
            "items": _children(raw, "호", "호번호", "호내용", "item"), "raw": raw,
        })
    supplements = []
    section = root.get("부칙")
    supplementary_complete = isinstance(section, dict) and "부칙단위" in section
    if supplementary_complete:
        for raw in objects(section["부칙단위"]):
            text = body_text(raw.get("부칙내용"))
            if not text:
                supplementary_complete = False
            supplements.append({
                "promulgation_date": legal_date(raw.get("부칙공포일자")),
                "promulgation_number": str(raw.get("부칙공포번호") or ""),
                "text": text, "raw": raw,
                "transitional": bool(re.search(r"경과조치|적용례|종전의|적용에 관한|소급", text)),
            })
    return {
        **selected, "provisions": articles, "articles": [a["number"] for a in articles],
        "body_complete": True, "supplementary_provisions": supplements,
        "supplementary_complete": supplementary_complete,
        "transitional_review_needed": any(s["transitional"] for s in supplements),
        "enforcement_note": body_text(basic.get("조문시행일자문자열")),
        "temporal_scope": "EXACT_EFFECTIVE_VERSION", "applicability_advisory_only": True,
        "detail_raw": payload,
    }


def select_provision(law: dict, article: str, paragraph: str | None = None,
                     item: str | None = None, subitem: str | None = None) -> dict:
    path = {"article": provision_number(article), "paragraph": provision_number(paragraph),
            "item": provision_number(item), "subitem": subitem}
    if not path["article"] or (paragraph and not path["paragraph"]) or (item and not path["item"]):
        return {"status": "UNVERIFIED", "path": path, "reason": "Unsupported provision locator"}
    rows = law.get("provisions", [])
    node = None
    article_node = None
    for level, collection in (("article", None), ("paragraph", "paragraphs"),
                              ("item", "items"), ("subitem", "subitems")):
        wanted = path[level]
        if not wanted:
            continue
        if collection:
            rows = node.get(collection, []) if node else []
            if level == "item" and node and not paragraph and not rows:
                implicit = [p for p in node.get("paragraphs", []) if p["number"] is None]
                rows = implicit[0].get("items", []) if len(implicit) == 1 else []
        matches = [r for r in rows if r["number"] == wanted]
        if len(matches) != 1:
            return {"status": "UNVERIFIED", "path": path,
                    "reason": "Missing or ambiguous provision; no parent-text fallback"}
        node = matches[0]
        if level == "article":
            article_node = node
            if node.get("deleted"):
                return {"status": "DELETED", "path": path, "text": node["text"],
                        "reason": "Provision is deleted in the selected version"}
    def full_text(part: dict) -> str:
        pieces = [part.get("text", "")]
        for key in ("paragraphs", "items", "subitems"):
            pieces.extend(full_text(child) for child in part.get(key, []))
        return "\n".join(filter(None, pieces))
    text = full_text(node) if node else ""
    return {"status": "VERIFIED" if text else "UNVERIFIED", "path": path, "text": text,
            "article_effective_from": article_node.get("effective_from") if article_node else None,
            "article_effective_date_raw": article_node.get("effective_date_raw") if article_node else None}
