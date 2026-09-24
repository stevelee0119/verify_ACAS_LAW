"""Frozen report payloads shared by every renderer."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from types import SimpleNamespace

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.terminology import EDITABLE_COPY_NOTICE, REVIEW_NOTICE, report_label


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def remove_sealed(value):
    if isinstance(value, list):
        return [remove_sealed(item) for item in value]
    if isinstance(value, dict):
        result = {key: remove_sealed(item) for key, item in value.items()}
        for key in ("sealed_excerpt", "sealed_text", "hidden_text", "deleted_text"):
            if key in result:
                result[key] = None
        if value.get("sealed"):
            for key in ("excerpt", "text", "content", "raw_text"):
                if key in result:
                    result[key] = None
        return result
    return value


def shareable_snapshot(snapshot):
    """Mask known identifiers and detectable PII without rewriting legal terminology."""
    from packages.pii_engine import detect

    source = remove_sealed(copy.deepcopy(snapshot))
    result = source["engine_result"]
    project = (result.get("input_snapshot") or {}).get("project", {})
    names = set(p for p in project.get("parties", []) if isinstance(p, str) and len(p) > 1)
    for doc in result.get("documents", []):
        for entity in doc.get("entities", []):
            if entity.get("type") in ("PERSON", "COMPANY"):
                name = entity.get("text") or entity.get("name") or entity.get("value")
                if isinstance(name, str) and len(name) > 1:
                    names.add(name)
    ordered_names = sorted(names, key=len, reverse=True)
    internal_fields = {"review_note", "memo", "assignee", "lead_reviewer", "represented_party",
                       "storage_key", "path", "raw_response", "response_body", "request_body"}
    # Retain field structure and explicit omissions in the technical appendix.
    def mask(value, key="", path=""):
        if key == "note" and value and not (path.startswith("engine_result.") or "unavailable_sources" in path):
            return "[공유용에서 제외]"
        if key in internal_fields and value:
            return "[공유용에서 제외]"
        if key in {"review_history", "pages", "masked_preview"} and value:
            return [] if isinstance(value, list) else {}
        if isinstance(value, dict):
            return {k: mask(v, k, f"{path}.{k}" if path else k) for k, v in value.items()}
        if isinstance(value, list):
            return [mask(v, key, path) for v in value]
        if not isinstance(value, str):
            return value
        if key in {"created_by", "finalized_by", "updated_by", "reviewed_by", "actor", "sha256",
                   "source_run_hash", "source_snapshot_hash", "snapshot_hash", "response_hash", "head_hash",
                   "preflight_hash", "verification_key", "run_id", "source_run_id", "report_id", "source_report_id"}:
            return value  # Authenticated accountability identifiers are intentional.
        for name in ordered_names:
            value = value.replace(name, "[당사자]")
        for match in sorted(detect(value), key=lambda m: m.start, reverse=True):
            value = value[:match.start] + "[개인정보]" + value[match.end:]
        return value
    projected = mask(source)
    projected["privacy"] = {
        "policy": "SHAREABLE", "sealed_content_included": False,
        "omitted": ["internal notes", "raw page text", "review history", "raw source responses"],
        "notice": "탐지 가능한 개인정보를 마스킹했습니다. 미탐지 정보가 있을 수 있어 외부 전달 전 사람의 확인이 필요합니다.",
    }
    return projected


class FrozenFinding:
    def __init__(self, data):
        self._data = copy.deepcopy(data)
        defaults = {"finding_id": "", "document_id": None, "page": None, "block_id": None,
                    "title": "", "detail": "", "engine": "", "confidence": 0.0, "advisory_only": False}
        self.__dict__.update(defaults | self._data)
        self.type = FindingType(data["type"])
        self.status = VerificationStatus(data.get("status", "UNVERIFIED"))
        self.severity = Severity(data.get("severity", "INFO"))
        self.evidence_grade = EvidenceGrade(data.get("evidence_grade", "U"))
        bbox = data.get("bbox")
        self.bbox = SimpleNamespace(**dict(zip(("x0", "y0", "x1", "y1"), bbox))) if bbox else None

    def to_dict(self, reveal_sealed=False):
        return copy.deepcopy(self._data) if reveal_sealed else remove_sealed(self._data)


_DOCUMENT_DEFAULTS = {"filename": "", "quarantined": False, "rag_indexable": False, "warnings": [],
                      "authorship": {}, "masked_preview": "", "citations": [], "claims": [], "entities": [],
                      "events": [], "engine_data": {}, "source_records": [], "pages": []}


def view_from_snapshot(snapshot, snapshot_hash):
    engine = copy.deepcopy(snapshot["engine_result"])
    view = SimpleNamespace(**engine)
    view.started_at = datetime.fromisoformat(engine["started_at"])
    view.finished_at = datetime.fromisoformat(engine["finished_at"]) if engine.get("finished_at") else None
    view.documents = []
    for item in engine.get("documents", []):
        # 필드가 추가되기 전에 저장된 검증 결과에는 일부 키가 없다. 없는 값 때문에
        # 형식마다 AttributeError로 산출물이 빠지지 않도록 빈 값으로 채운다.
        doc = SimpleNamespace(**(_DOCUMENT_DEFAULTS | item))
        doc.normalized = SimpleNamespace(sha256=item.get("sha256"), parser_name=item.get("parser"))
        doc.findings = [FrozenFinding(f) for f in item.get("findings", [])]
        view.documents.append(doc)
    view.project_findings = [FrozenFinding(f) for f in engine.get("project_findings", [])]
    view.all_findings = [f for d in view.documents for f in d.findings] + view.project_findings
    view.report_metadata = copy.deepcopy(snapshot["report"])
    view.report_metadata.update(snapshot_hash=snapshot_hash,
                                label=report_label(snapshot["report"]["state"], snapshot["report"]["audience"]),
                                review_notice=REVIEW_NOTICE, editable_copy_notice=EDITABLE_COPY_NOTICE)
    view.review_snapshot = copy.deepcopy(snapshot)
    return view


CLAIM_REFERENCE_NOTE = "주장 전문은 documents[].claims에 수록"


def compact_claim_rows(result):
    """부록에서 같은 주장 전문이 네 번 반복되지 않게 참조로 바꾼다.

    주장 전문은 documents[].claims에 이미 있다. 검토표(matrix.claims)와 사전 점검의 두
    목록(incomplete_claim_reviews, unresolved_claims)이 같은 전문을 다시 실어, 큰 사건에서는
    부록의 60%가 중복이었고 PDF·Word·Excel 생성 시간이 그만큼 늘었다. 주장 식별자와
    문서 식별자, 검토 상태는 그대로 두므로 어느 주장인지는 잃지 않는다. 고정본(스냅샷)과
    JSON 내보내기는 바꾸지 않는다.
    """
    review = result.get("review_snapshot") or {}
    rows = [(review.get("matrix") or {}).get("claims") or [],
            (review.get("preflight") or {}).get("incomplete_claim_reviews") or [],
            (review.get("preflight") or {}).get("unresolved_claims") or []]
    for group in rows:
        for row in group:
            claim = row.get("claim") if isinstance(row, dict) else None
            if isinstance(claim, dict):
                row["claim"] = {"claim_id": claim.get("claim_id"), "note": CLAIM_REFERENCE_NOTE}
    return result


def technical_payload(run_result):
    """One complete JSON representation used by PDF, Word and spreadsheet appendices."""
    from .exporters import to_payload
    # 날짜·열거형을 JSON과 같은 문자열로 맞추되, 들여쓰기 없이 한 번만 직렬화한다.
    result = json.loads(json.dumps(to_payload(run_result), ensure_ascii=False, default=str))
    # The static glossary is versioned separately; retain every execution/review field.
    result.pop("terminology", None)
    result.get("review_snapshot", {}).pop("terminology", None)
    return compact_claim_rows(result)


def json_lines(value, prefix=""):
    """Flatten every leaf without discarding empty containers or long strings."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from json_lines(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from json_lines(item, f"{prefix}[{index}]")
    else:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        yield prefix, text


def xml_text(value):
    # XML 1.0 forbids control characters even when escaped by the OOXML library.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "\ufffd", str(value if value is not None else ""))
