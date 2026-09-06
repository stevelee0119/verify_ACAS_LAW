"""HWPX / HWP Parser.

HWPX는 OWPML(ZIP+XML) 구조를 직접 읽는다.
Binary HWP는 native parse를 시도하고 실패 시 UNSUPPORTED로 표시하여
전체 Job을 실패시키지 않는다(제14.2장, 제10장 Graceful Degradation).
"""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List

from packages.common.schemas import Block, NormalizedDocument, Page, new_id

from .base import DocumentParser, ParserError
from .ooxml_common import local_name, parse_xml, read_entries, safe_open_zip


class HwpxParser(DocumentParser):
    name = "HwpxParser"
    extensions = [".hwpx"]
    mime_types = ["application/hwp+zip", "application/vnd.hancom.hwpx"]

    def parse(self, path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type or self.mime_types[0],
            sha256=sha256,
            parser_name=self.name,
        )
        try:
            zf = safe_open_zip(path)
        except Exception as exc:
            raise ParserError(f"HWPX ZIP 처리 실패: {exc}") from exc

        visible: List[str] = []
        hidden: List[str] = []
        xml_parts: List[str] = []
        page = Page(page_number=1)

        with zf:
            doc.structure["zip_entries"] = [i.filename for i in zf.infolist()]
            entries = read_entries(zf, lambda n: n.endswith(".xml"))
            sections = {k: v for k, v in entries.items() if "section" in k.lower()}
            for name in sorted(sections):
                data = sections[name]
                xml_parts.append(data.decode("utf-8", "replace"))
                try:
                    root = parse_xml(data)
                except Exception as exc:
                    doc.parse_warnings.append(f"{name} 파싱 실패: {exc}")
                    continue
                for para in root.iter():
                    if local_name(para.tag) != "p":
                        continue
                    text = "".join(t.text or "" for t in para.iter() if local_name(t.tag) == "t")
                    text = text.strip()
                    if not text:
                        continue
                    page.blocks.append(
                        Block(block_id=new_id("B"), text=text, page=1, source_layer="visible_text")
                    )
                    visible.append(text)

            # 메모/주석/설정
            for name, data in entries.items():
                low = name.lower()
                if any(k in low for k in ("memo", "comment", "annotation")):
                    xml_parts.append(data.decode("utf-8", "replace"))
                    try:
                        root = parse_xml(data)
                    except Exception:
                        continue
                    texts = [t.text.strip() for t in root.iter() if local_name(t.tag) == "t" and t.text and t.text.strip()]
                    for t in texts:
                        page.blocks.append(
                            Block(
                                block_id=new_id("B"),
                                text=t,
                                page=1,
                                source_layer="xml",
                                block_type="comment",
                                visible=False,
                                attributes={"part": name},
                            )
                        )
                        hidden.append(t)
                if "content.hpf" in low or "meta" in low or "version" in low:
                    xml_parts.append(data.decode("utf-8", "replace"))

            meta = entries.get("Contents/content.hpf") or entries.get("META-INF/container.xml")
            if meta:
                try:
                    root = parse_xml(meta)
                    for el in root.iter():
                        tag = local_name(el.tag)
                        if el.text and el.text.strip() and tag in ("title", "creator", "date", "publisher", "subject"):
                            doc.metadata[tag] = el.text.strip()
                except Exception:
                    pass

        doc.pages.append(page)
        doc.raw_layers["rendered_text"] = "\n".join(visible)
        doc.raw_layers["raw_text"] = "\n".join(visible + hidden)
        doc.raw_layers["hidden_text"] = "\n".join(hidden)
        doc.raw_layers["xml"] = "\n".join(xml_parts)
        doc.raw_layers["metadata_text"] = "\n".join(f"{k}: {v}" for k, v in doc.metadata.items())
        return doc


class HwpParser(DocumentParser):
    """Binary HWP 5.x. CFB 컨테이너의 BodyText 스트림을 zlib 해제해 텍스트만 추출한다."""

    name = "HwpParser"
    extensions = [".hwp"]
    mime_types = ["application/x-hwp", "application/haansofthwp"]

    def parse(self, path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type or self.mime_types[0],
            sha256=sha256,
            parser_name=self.name,
        )
        raw = Path(path).read_bytes()
        if not raw.startswith(b"\xd0\xcf\x11\xe0"):
            doc.parse_warnings.append("HWP CFB 시그니처가 아니다. 형식 확인 필요.")
        texts: List[str] = []
        try:
            texts = _extract_hwp_text(raw)
        except Exception as exc:
            doc.parse_warnings.append(f"HWP native parse 실패: {exc}")

        if not texts:
            doc.parse_warnings.append(
                "Binary HWP 본문 추출에 실패했다. isolated conversion fallback(HWPX/PDF 변환) 후 재업로드가 필요하며, "
                "현재 문서의 본문 검증 항목은 UNVERIFIED로 처리한다."
            )
            doc.structure["unsupported_body"] = True

        page = Page(page_number=1)
        for t in texts:
            page.blocks.append(Block(block_id=new_id("B"), text=t, page=1, source_layer="visible_text"))
        doc.pages.append(page)
        joined = "\n".join(texts)
        doc.raw_layers["rendered_text"] = joined
        doc.raw_layers["raw_text"] = joined
        return doc


def _extract_hwp_text(raw: bytes) -> List[str]:
    """의존성 없이 zlib 스트림에서 UTF-16LE 한글 텍스트를 복원하는 보수적 추출기."""
    results: List[str] = []
    for m in re.finditer(rb"\x78\x9c|\x78\x01|\x78\xda", raw):
        start = m.start()
        try:
            data = zlib.decompressobj().decompress(raw[start : start + 2_000_000])
        except Exception:
            continue
        if len(data) < 20:
            continue
        try:
            text = data.decode("utf-16-le", "ignore")
        except Exception:
            continue
        cleaned = re.sub(r"[\x00-\x1f]+", " ", text)
        for chunk in re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9\s·.,()\[\]:;\-~%\"'“”‘’/]{6,}", cleaned):
            s = chunk.strip()
            if len(s) >= 8 and s not in results:
                results.append(s)
    return results[:5000]
