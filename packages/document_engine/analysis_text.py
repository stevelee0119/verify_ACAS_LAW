"""Opt-in model input including visible table rows, with explicit coverage."""
from __future__ import annotations

from collections import Counter
from itertools import groupby

from .reading_text import build_reading_text

CONTRACT_VERSION = "analysis-text-v1"


def analysis_text(doc, findings=(), *, limit=12000):
    from packages.verification_engine.sanitized_input import injection_parts, strip_injections

    excluded_ids, instructions = injection_parts(findings, doc)
    table_refs = {b.attributes.get("table_ref") for b in doc.blocks if b.block_type == "table"}
    kept, excluded = [], []
    for block in doc.blocks:
        reason = ("INSTRUCTION" if block.block_id in excluded_ids else
                  "NON_BODY_LAYER" if not block.visible or block.source_layer not in ("visible_text", "ocr_layer") else
                  "RUNNING_HEAD" if block.block_type in ("header", "footer", "running_head") else
                  "DUPLICATE_TABLE_LINE" if block.block_type == "table_line"
                      and block.attributes.get("table_ref") in table_refs else "")
        if reason:
            excluded.append({"block_id": block.block_id, "reason": reason})
        else:
            kept.append(block)
    parts, segments, cursor = [], [], 0
    # Keep prose wrapping behavior; serialize each table row independently.
    def key(block):
        if block.block_type in ("table", "table_line"):
            return ("table", block.attributes.get("table_ref", block.block_id), block.attributes.get("row"))
        return ("prose",)
    for group_key, group in groupby(kept, key=key):
        blocks = list(group)
        if group_key[0] == "prose":
            reading = build_reading_text(doc, blocks)
            text = reading.text
        else:
            cells = blocks[0].attributes.get("cells")
            if cells:
                text = "\n".join(" | ".join(str(c or "") for c in row) for row in cells)
            else:
                columns = {}
                for b in blocks:
                    columns.setdefault(b.attributes.get("column", b.block_id), []).append(b.text)
                text = " | ".join(" ".join(values) for values in columns.values())
        text = strip_injections(text, instructions)
        if not text.strip():
            continue
        if parts:
            cursor += 1
        start = cursor
        parts.append(text)
        cursor += len(text)
        segments.append({"block_ids": [b.block_id for b in blocks], "kind": group_key[0],
                         "span": [start, cursor], "page": blocks[0].page})
    full = "\n".join(parts)
    selected = full[:limit]
    return selected, {"mode": "VISIBLE_PROSE_AND_TABLES", "contract_version": CONTRACT_VERSION,
        "available_chars": len(full), "inspected_chars": len(selected), "omitted_chars": max(0, len(full) - limit),
        "is_full_visible_body": len(full) <= limit and not excluded_ids,
        "is_full_document": len(full) <= limit and not excluded,
        "included_block_counts": dict(Counter(b.block_type for b in kept)),
        "excluded_blocks": excluded, "segments": segments}
