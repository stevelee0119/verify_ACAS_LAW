"""Comparison-only source fragments for exhibit mentions; no parser text edits."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import unicodedata
from typing import Any

from packages.document_engine.reading_text import ReadingText
from .exhibits import LEAD_RE, parse_exhibits


def _mapped_characters(text: str) -> tuple[str, list[int]] | None:
    """NFKC characters with offsets into the original physical line."""
    if not isinstance(text, str):
        return None
    chars, offsets = [], []
    for index, char in enumerate(text):
        for normalized in unicodedata.normalize("NFKC", char):
            chars.append(normalized)
            offsets.append(index)
    normalized = "".join(chars)
    # Cross-character composition cannot be mapped by this local map.
    if normalized != unicodedata.normalize("NFKC", text):
        return None
    return normalized, offsets


def _identity(ref):
    return ref["party"], ref["number"], tuple(ref.get("branches") or [])


class SourceParagraph:
    def __init__(self, fragments: list[dict[str, Any]]):
        self.fragments = fragments
        self.mapped = [_mapped_characters(f["text"]) for f in fragments]
        self.starts, cursor = [], 0
        for mapped in self.mapped:
            self.starts.append(cursor)
            cursor += len(mapped[0]) + 1
        self.text = " ".join(mapped[0] for mapped in self.mapped)

    def between(self, start: int, end: int) -> list[dict[str, Any]]:
        out = []
        index = max(0, bisect_right(self.starts, start) - 1)
        for position in range(index, len(self.fragments)):
            fragment, mapped, cursor = self.fragments[position], self.mapped[position], self.starts[position]
            if cursor >= end:
                break
            text, offsets = mapped
            left, right = max(0, start - cursor), min(len(text), end - cursor)
            if left < right:
                first, last = offsets[left], offsets[right - 1] + 1
                out.append({**fragment, "text": fragment["text"][first:last],
                            "source_start": fragment["source_start"] + first,
                            "source_end": fragment["source_start"] + last})
        return out

    def mentions(self, original_items):
        refs = parse_exhibits(self.text)
        if [_identity(ref) for ref, _ in original_items] != [_identity(ref) for ref in refs]:
            return {}
        spans = sorted({ref["span"] for ref in refs})
        ends = {span: spans[i + 1][0] if i + 1 < len(spans) else len(self.text)
                for i, span in enumerate(spans)}
        out = {}
        for (original, _), ref in zip(original_items, refs):
            start, end = ref["span"][1], ends[ref["span"]]
            lead = LEAD_RE.match(self.text[start:end])
            start += lead.end() if lead else 0
            fragments = self.between(start, end)
            out[(original["span"], _identity(original))] = source_mention(fragments)
        return out


def source_mention(fragments: list[dict[str, Any]]) -> dict[str, Any]:
    """Each inserted space is a physical boundary, not a guessed word join."""
    return {"tail": " ".join(unicodedata.normalize("NFKC", f["text"]) for f in fragments).strip(),
            "fragments": fragments}


def extend_mention(source: dict[str, Any], fragments: list[dict[str, Any]]) -> None:
    source["fragments"].extend(fragments)
    source["dirty"] = True
    source.pop("roles", None)


def source_tail(source: dict[str, Any]) -> str:
    if source.pop("dirty", False):
        source["tail"] = " ".join(unicodedata.normalize("NFKC", f["text"])
                                  for f in source["fragments"]).strip()
    return source["tail"]


class ExhibitSourceIndex:
    def __init__(self, reading: ReadingText):
        self.reading = reading
        self.starts = [s.start for s in reading.segments]
        self.cache: dict[int, Any] = {}

    def _aligned_lines(self, segment):
        block = segment.block
        if id(block) in self.cache:
            return self.cache[id(block)]
        lines = block.attributes.get("lines") or [block.text]
        if not isinstance(lines, (list, tuple)):
            self.cache[id(block)] = None
            return None
        fragments, identity, physical_starts = [], [], []
        for index, line in enumerate(lines):
            text = line.get("text", "") if isinstance(line, dict) else str(line)
            mapped = _mapped_characters(text)
            if mapped is None:
                self.cache[id(block)] = None
                return None
            normalized, offsets = mapped
            positions = [i for i, char in enumerate(normalized) if not char.isspace()]
            physical_starts.append(len(identity))
            identity.extend(normalized[i] for i in positions)
            fragments.append(({"text": text, "block_id": block.block_id, "page": block.page,
                               "source_layer": block.source_layer,
                               "line_index": index, "source_start": 0, "source_end": len(text),
                               "bbox": line.get("bbox") if isinstance(line, dict) else
                               block.bbox.as_tuple() if block.bbox else None},
                              [offsets[i] for i in positions]))
        visible = self.reading.text[segment.start:segment.end]
        mapped = _mapped_characters(visible)
        if mapped is None:
            result = None
        else:
            normalized, offsets = mapped
            positions = [i for i, char in enumerate(normalized) if not char.isspace()]
            key = "".join(normalized[i] for i in positions)
            result = (fragments, physical_starts, [offsets[i] for i in positions]) if key == "".join(identity) else None
        self.cache[id(block)] = result
        return result

    def paragraph(self, start: int, end: int):
        fragments = []
        index = max(0, bisect_right(self.starts, start) - 1)
        for position in range(index, len(self.reading.segments)):
            segment = self.reading.segments[position]
            if segment.start >= end:
                break
            if segment.end <= start:
                continue
            aligned = self._aligned_lines(segment)
            if aligned is None:
                return None
            physical, physical_starts, positions = aligned
            left = bisect_left(positions, max(0, start - segment.start))
            right = bisect_left(positions, min(segment.end, end) - segment.start)
            first_line = max(0, bisect_right(physical_starts, left) - 1)
            for line_index in range(first_line, len(physical)):
                fragment, offsets = physical[line_index]
                cursor = physical_starts[line_index]
                if cursor >= right:
                    break
                a, b = max(0, left - cursor), min(len(offsets), right - cursor)
                if a < b:
                    first, last = offsets[a], offsets[b - 1] + 1
                    fragments.append({**fragment, "text": fragment["text"][first:last],
                                      "source_start": first, "source_end": last})
        return SourceParagraph(fragments) if fragments else None


def mention_identity(ref):
    return ref["span"], _identity(ref)
