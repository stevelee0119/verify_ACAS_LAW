"""DOCX Parser.

본문·표·머리말/꼬리말·각주·주석을 각각 Block으로 남기고,
w:vanish(숨김 서식), w:ins/w:del(미수락 변경이력), customXml, core/app properties를
structure에 담아 제7-A장 MM-2 포렌식에 전달한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from packages.common.schemas import Block, NormalizedDocument, Page, new_id

from .base import DocumentParser, ParserError
from .ooxml_common import local_name, parse_xml, read_entries, safe_open_zip, w


def _para_text(node, include_deleted: bool = True) -> str:
    parts: List[str] = []
    for t in node.iter():
        tag = local_name(t.tag)
        if tag in ("t", "delText") and t.text:
            if tag == "delText" and not include_deleted:
                continue
            parts.append(t.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
    return "".join(parts)


def _run_is_hidden(run) -> bool:
    rpr = run.find(w("rPr"))
    if rpr is None:
        return False
    vanish = rpr.find(w("vanish"))
    if vanish is not None and vanish.get(w("val")) not in ("0", "false"):
        return True
    return False


def _run_is_white(run) -> bool:
    rpr = run.find(w("rPr"))
    if rpr is None:
        return False
    color = rpr.find(w("color"))
    if color is not None and (color.get(w("val")) or "").upper() in ("FFFFFF", "FFFFFE"):
        return True
    return False


def _run_font_size(run) -> float:
    rpr = run.find(w("rPr"))
    if rpr is None:
        return 0.0
    sz = rpr.find(w("sz"))
    if sz is None:
        return 0.0
    try:
        return float(sz.get(w("val"), "0")) / 2.0  # half-point
    except ValueError:
        return 0.0


class DocxParser(DocumentParser):
    name = "DocxParser"
    extensions = [".docx", ".docm", ".dotx"]
    mime_types = [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-word.document.macroenabled.12",
    ]

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
            raise ParserError(f"DOCX ZIP 처리 실패: {exc}") from exc

        with zf:
            entries = read_entries(zf, lambda n: n.endswith(".xml") or n.endswith(".rels"))
            doc.structure["zip_entries"] = [i.filename for i in zf.infolist()]
            media = [i.filename for i in zf.infolist() if i.filename.startswith("word/media/")]
            doc.structure["embedded_media"] = media

            page = Page(page_number=1)
            xml_layer_parts: List[str] = []
            hidden_parts: List[str] = []
            visible_parts: List[str] = []

            body = entries.get("word/document.xml")
            if body is None:
                raise ParserError("word/document.xml 없음")
            xml_layer_parts.append(body.decode("utf-8", "replace"))
            root = parse_xml(body)

            tracked_inserts: List[Dict[str, Any]] = []
            tracked_deletes: List[Dict[str, Any]] = []
            hidden_runs: List[Dict[str, Any]] = []
            rsids: set[str] = set()

            for para in root.iter(w("p")):
                text = _para_text(para, include_deleted=False)
                in_table = any(local_name(a.tag) == "tbl" for a in para.iterancestors())
                runs = list(para.iter(w("r")))
                hidden_run_texts = []
                for run in runs:
                    rtext = _para_text(run)
                    if not rtext.strip():
                        continue
                    reason = None
                    if _run_is_hidden(run):
                        reason = "W_VANISH"
                    elif _run_is_white(run):
                        reason = "WHITE_FONT"
                    elif 0 < _run_font_size(run) < 3.5:
                        reason = f"TINY_FONT({_run_font_size(run)}pt)"
                    if reason:
                        hidden_run_texts.append(rtext)
                        hidden_runs.append({"text": rtext, "reason": reason})
                    rsid = run.get(w("rsidR")) or run.get(w("rsidRDefault"))
                    if rsid:
                        rsids.add(rsid)

                for ins in para.iter(w("ins")):
                    t = _para_text(ins)
                    if t.strip():
                        tracked_inserts.append(
                            {"text": t, "author": ins.get(w("author"), ""), "date": ins.get(w("date"), "")}
                        )
                for dele in para.iter(w("del")):
                    t = _para_text(dele)
                    if t.strip():
                        tracked_deletes.append(
                            {"text": t, "author": dele.get(w("author"), ""), "date": dele.get(w("date"), "")}
                        )

                visible_text = text
                for h in hidden_run_texts:
                    visible_text = visible_text.replace(h, "")
                if visible_text.strip():
                    page.blocks.append(
                        Block(
                            block_id=new_id("B"),
                            text=visible_text.strip(),
                            page=1,
                            source_layer="visible_text",
                            block_type="table" if in_table else "paragraph",
                        )
                    )
                    visible_parts.append(visible_text.strip())
                for h in hidden_run_texts:
                    page.blocks.append(
                        Block(
                            block_id=new_id("B"),
                            text=h.strip(),
                            page=1,
                            source_layer="hidden_text",
                            block_type="paragraph",
                            visible=False,
                            attributes={"hidden_reason": next(
                                (r["reason"] for r in hidden_runs if r["text"] == h), "HIDDEN"
                            )},
                        )
                    )
                    hidden_parts.append(h.strip())

            # 머리말/꼬리말/각주/미주/주석
            for entry_name, data in entries.items():
                base = entry_name.split("/")[-1]
                kind = None
                if base.startswith("header"):
                    kind = "header"
                elif base.startswith("footer"):
                    kind = "footer"
                elif base.startswith("footnotes"):
                    kind = "footnote"
                elif base.startswith("endnotes"):
                    kind = "footnote"
                elif base.startswith("comments"):
                    kind = "comment"
                if not kind:
                    continue
                xml_layer_parts.append(data.decode("utf-8", "replace"))
                try:
                    sub = parse_xml(data)
                except Exception:
                    continue
                for para in sub.iter(w("p")):
                    t = _para_text(para).strip()
                    if not t:
                        continue
                    page.blocks.append(
                        Block(
                            block_id=new_id("B"),
                            text=t,
                            page=1,
                            source_layer="visible_text" if kind in ("header", "footer", "footnote") else "xml",
                            block_type=kind,
                            visible=kind != "comment",
                            attributes={"part": entry_name},
                        )
                    )
                    if kind == "comment":
                        hidden_parts.append(t)
                    else:
                        visible_parts.append(t)

            comments_xml = entries.get("word/comments.xml")
            comments: List[Dict[str, Any]] = []
            if comments_xml is not None:
                try:
                    croot = parse_xml(comments_xml)
                    for c in croot.iter(w("comment")):
                        comments.append(
                            {
                                "id": c.get(w("id"), ""),
                                "author": c.get(w("author"), ""),
                                "date": c.get(w("date"), ""),
                                "text": _para_text(c).strip(),
                            }
                        )
                except Exception as exc:  # pragma: no cover
                    doc.parse_warnings.append(f"comments.xml 파싱 실패: {exc}")

            # core / app properties
            props: Dict[str, Any] = {}
            for prop_file in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
                data = entries.get(prop_file)
                if data is None:
                    continue
                xml_layer_parts.append(data.decode("utf-8", "replace"))
                try:
                    proot = parse_xml(data)
                except Exception:
                    continue
                for el in proot.iter():
                    tag = local_name(el.tag)
                    if el.text and el.text.strip() and tag not in ("Properties", "coreProperties"):
                        props[tag] = el.text.strip()
                    if tag == "property":
                        pname = el.get("name")
                        pval = "".join(x.text or "" for x in el.iter() if x.text)
                        if pname:
                            props[f"custom:{pname}"] = pval.strip()
            doc.metadata.update(props)

            custom_xml = {k: v.decode("utf-8", "replace") for k, v in entries.items() if k.startswith("customXml/")}
            doc.structure.update(
                {
                    "tracked_inserts": tracked_inserts,
                    "tracked_deletes": tracked_deletes,
                    "hidden_runs": hidden_runs,
                    "comments": comments,
                    "rsids": sorted(rsids),
                    "custom_xml": custom_xml,
                    "properties": props,
                }
            )
            doc.pages.append(page)

        doc.raw_layers["rendered_text"] = "\n".join(visible_parts)
        doc.raw_layers["raw_text"] = "\n".join(visible_parts + hidden_parts)
        doc.raw_layers["hidden_text"] = "\n".join(hidden_parts)
        doc.raw_layers["xml"] = "\n".join(xml_layer_parts)
        doc.raw_layers["metadata_text"] = "\n".join(f"{k}: {v}" for k, v in doc.metadata.items())
        return doc
