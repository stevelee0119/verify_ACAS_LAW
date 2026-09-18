"""Conservative, lexical claim structure. Extraction is not factual verification."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from packages.common.schemas import Claim
from .calculation import parse_amounts

IDENTIFIER_PATTERNS = {
    "speaker_id": r"(?:speaker_id|주장자\s*ID)",
    "target_id": r"(?:target_id|상대방\s*ID)",
    "transaction_id": r"(?:transaction_id|거래\s*(?:ID|번호)|계약\s*번호)",
    "object_id": r"(?:object_id|목적물\s*(?:ID|번호))",
    "event_identity": r"(?:event_id|payment_id|지급\s*번호|송금\s*번호|이벤트\s*ID)",
}
IDENTIFIERS = {
    name: re.compile(pattern + r"\s*[:=：]?\s*([A-Za-z0-9][A-Za-z0-9_.:/-]*)", re.I)
    for name, pattern in IDENTIFIER_PATTERNS.items()
}
DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.\-년]\s*(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*일?")
NEGATION_RE = re.compile(r"(?:않았|않는|않다|아니|없다|없었|없음|부인|미지급|미변제|거짓|허위)|\b(?:not|never|deny|denies|denied)\b", re.I)
HEARSAY_RE = re.compile(r"(?:전해\s*들|들었다|들었|전언|라고\s*(?:주장|진술|말)|다고\s*(?:주장|진술|말))|\b(?:allegedly|reportedly|said|according to)\b", re.I)
CONDITIONAL_RE = re.compile(r"(?:만약|가정|경우에는|경우|라면|한다면|하였다면|했으면)|\b(?:if|assuming|provided that)\b", re.I)
ALTERNATIVE_RE = re.compile(r"(?:예비적|선택적|설령|가사)|\b(?:alternatively|in the alternative)\b", re.I)
QUOTE_RE = re.compile(r'["“”‘’「」『』]|\B\x27|\x27\B')
UNKNOWN_RE = re.compile(r"(?:불지|알지\s*못|모른다|확인되지)|\bunknown\b", re.I)
ACTION_PATTERNS = [
    ("CONTRACT", re.compile(r"계약(?:을)?\s*체결|약정|합의|\bcontracted\b", re.I)),
    ("PAYMENT", re.compile(r"지급|송금|입금|변제|\b(?:paid|payment)\b", re.I)),
    ("TERMINATION", re.compile(r"해지|해제|종료|\bterminated\b", re.I)),
    ("INCORPORATION", re.compile(r"설립|법인등기")),
    ("FILING", re.compile(r"접수|신청|고소|기소")),
    ("DECISION", re.compile(r"선고|판결|처분")),
    ("INCIDENT", re.compile(r"사고|폭행|상해|침해")),
]
REFERENCE_RE = re.compile(
    r"(?:(?P<side>갑|을|병|정)\s*제?\s*(?P<number>\d+)\s*호증"
    r"(?P<branches>(?:\s*의\s*\d+)*)|(?P<attachment>별첨|별지|첨부)\s*제?\s*(?P<attachment_number>\d+)\s*호?)"
    r"(?:\s*[,\(]?\s*(?:제\s*|[pP]\.\s*)?(?P<page_start>\d+)"
    r"(?:\s*[~～\-–]\s*(?P<page_end>\d+))?\s*(?:쪽|면|페이지|[pP](?![A-Za-z]))\s*\)?)?"
)


def extract_evidence_references(
    text: str, *, document_id: str | None = None, block_id: str | None = None,
    page: int | None = None, source_run_id: str | None = None,
    document_sha256: str | None = None, offset: int = 0,
) -> list[dict[str, Any]]:
    """Preserve exhibit branches, cited page ranges, and the citing location."""
    references = []
    for match in REFERENCE_RE.finditer(text):
        branches = [int(value) for value in re.findall(r"\d+", match.group("branches") or "")]
        prefix = match.group("side") or match.group("attachment")
        number = int(match.group("number") or match.group("attachment_number"))
        first = int(match.group("page_start")) if match.group("page_start") else None
        last = int(match.group("page_end")) if match.group("page_end") else first
        valid = number > 0 and all(b > 0 for b in branches) and (first is None or 0 < first <= last)
        references.append({
            "key": ":".join([prefix, str(number), *map(str, branches)]),
            "raw_text": match.group(0), "side": match.group("side"),
            "attachment": match.group("attachment"), "number": number, "branches": branches,
            "page_start": first, "page_end": last, "parse_status": "PARSED" if valid else "AMBIGUOUS",
            "document_id": document_id, "block_id": block_id, "page": page,
            "source_run_id": source_run_id, "document_sha256": document_sha256,
            "span": [offset + match.start(), offset + match.end()],
        })
    return references


def structure_claim_text(text: str) -> dict[str, Any]:
    """Return surface-level fields; multiple IDs, dates or amounts stay unresolved."""
    from datetime import date

    out: dict[str, Any] = {}
    identifiers = {}
    ambiguous = False
    for name, pattern in IDENTIFIERS.items():
        values = {m.group(1).rstrip(".") for m in pattern.finditer(text)}
        out[name] = next(iter(values)) if len(values) == 1 else None
        ambiguous |= len(values) > 1
        if out[name]:
            identifiers[name] = out[name]
    out["explicit_identifiers"] = identifiers
    speaker = re.search(r"(?:^|\s)(원고|피고|채권자|채무자|신청인|피신청인)(?:\s+([가-힣]{2,4}?))?(?:은|는|이|가)\s", text)
    target = re.search(r"(원고|피고|채권자|채무자|신청인|피신청인)(?:\s+([가-힣]{2,4}?))?(?:에게|에\s*대하여)", text)
    out["speaker_text"] = " ".join(v for v in speaker.groups() if v) if speaker else None
    out["target_text"] = " ".join(v for v in target.groups() if v) if target else None
    out.update(negated=bool(NEGATION_RE.search(text)), hearsay=bool(HEARSAY_RE.search(text)),
               quoted=bool(QUOTE_RE.search(text)), conditional=bool(CONDITIONAL_RE.search(text)),
               alternative=bool(ALTERNATIVE_RE.search(text)))
    out["stance"] = next((stance for condition, stance in (
        (out["quoted"], "QUOTED"), (out["hearsay"], "REPORTED"),
        (out["alternative"], "ALTERNATIVE"), (out["conditional"], "CONDITIONAL"),
        (bool(UNKNOWN_RE.search(text)), "UNKNOWN"), (out["negated"], "DENIED"),
    ) if condition), "ASSERTED")
    actions = [name for name, pattern in ACTION_PATTERNS if pattern.search(text)]
    out["action"] = actions[0] if len(actions) == 1 else None
    amounts = parse_amounts(text)
    out["amount"] = str(amounts[0].value) if len(amounts) == 1 else None
    out["currency"] = "KRW" if len(amounts) == 1 else None
    out["amount_scope"] = ("TOTAL" if re.search(r"총액|합계|총\s*지급", text) else
                           "PARTIAL" if re.search(r"일부|분할|차\s*지급|차\s*변제", text) else None)
    dates = []
    for match in DATE_RE.finditer(text):
        try:
            dates.append(date(*(int(match.group(k)) for k in ("y", "m", "d"))).isoformat())
        except ValueError:
            ambiguous = True
    out["asserted_date"] = dates[0] if len(dates) == 1 else None
    if ambiguous or len(dates) > 1 or len(amounts) > 1 or len(actions) > 1:
        out["stance"] = "AMBIGUOUS"
    # A rule score is not a probability and says nothing about evidence reliability.
    out["extraction_confidence"] = None
    return out


@dataclass(frozen=True)
class EvidenceItem:
    project_id: str
    reference_key: str
    document_id: str
    source_run_id: str
    document_sha256: str
    available_pages: tuple[int, ...]


@dataclass(frozen=True)
class EvidenceMatch:
    claim_id: str
    reference: dict[str, Any]
    candidates: list[EvidenceItem]
    status: str
    advisory_only: bool = True
    relationship: str = "UNASSESSED"
    evidence_reliability: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def match_evidence_references(
    claims: list[Claim], items: list[EvidenceItem], *, project_id: str,
) -> list[EvidenceMatch]:
    """Locate catalog references only. Never mark a claim VERIFIED or supported."""
    if not project_id:
        raise ValueError("project_id is required")
    index: dict[str, list[EvidenceItem]] = {}
    for item in items:
        if item.project_id == project_id:
            if not item.source_run_id or not item.document_sha256:
                raise ValueError("Evidence items require a preserved run and document hash")
            index.setdefault(item.reference_key, []).append(item)
    results = []
    for claim in claims:
        if claim.project_id != project_id:
            continue
        for reference in claim.evidence_references:
            candidates = index.get(reference.get("key", ""), [])
            if reference.get("parse_status") != "PARSED":
                status = "AMBIGUOUS_REFERENCE"
            elif not candidates:
                status = "REFERENCE_MISSING"
            elif len(candidates) != 1:
                status = "AMBIGUOUS_REFERENCE"
            else:
                first, last = reference.get("page_start"), reference.get("page_end")
                available = set(candidates[0].available_pages)
                covered = bool(available) if first is None else (
                    first <= last and sum(first <= page <= last for page in available) == last - first + 1)
                status = "REFERENCE_LOCATED" if covered else "PAGE_NOT_AVAILABLE"
            results.append(EvidenceMatch(claim.claim_id, reference.copy(), list(candidates), status))
    return results
