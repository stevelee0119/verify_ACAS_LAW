"""Lossless, content-addressed source pooling at the serialization boundary only."""
import hashlib
import json

from .serialize import to_jsonable

MIN_SOURCE_BYTES = 8192


def compact_sources(payload):
    pool = dict(payload.get("source_objects") or {})
    memo = {}

    def intern(value):
        if id(value) in memo:
            return memo[id(value)]
        encoded = json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        if len(encoded) < MIN_SOURCE_BYTES:
            return None
        key = hashlib.sha256(encoded).hexdigest()
        pool.setdefault(key, value)
        memo[id(value)] = key
        return key

    def engine_copy(value):
        if isinstance(value, list):
            return [engine_copy(v) for v in value]
        if not isinstance(value, dict):
            return value
        copied = dict(value)
        for name, child in value.items():
            if name == "official_record" and isinstance(child, dict) and child:
                key = intern(child)
                if key:
                    # Keep the identity and cited text inline for existing report consumers.
                    copied[name] = {k: v for k, v in child.items() if not isinstance(v, (dict, list))
                                    and k not in ("full_text", "text")}
                    cited = (value.get("review", {}).get("provision") or {}).get("text")
                    if cited:
                        copied[name]["text"] = cited
                    copied[name]["source_object_ref"] = key
                    continue
            copied[name] = engine_copy(child)
        return copied

    documents = []
    for original in payload.get("documents", []):
        doc = {**original, "engine_data": engine_copy(original.get("engine_data", {}))}
        records = []
        for source in original.get("source_records", []):
            record = dict(source)
            if isinstance(record.get("payload"), (dict, list)):
                key = intern(record["payload"])
                if key:
                    record["payload"] = {"source_object_ref": key}
            records.append(record)
        doc["source_records"] = records
        documents.append(doc)
    out = {**payload, "documents": documents}
    if pool:
        out.update(source_objects=pool, source_object_schema="sha256-json-v1")
    return out


def resolve_source(payload, record):
    """Read new pooled records and legacy inline records without changing their content."""
    key = record.get("source_object_ref") if isinstance(record, dict) else None
    return payload.get("source_objects", {}).get(key, record) if key else record
