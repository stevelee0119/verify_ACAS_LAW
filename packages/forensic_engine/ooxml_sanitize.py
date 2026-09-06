"""DOCX 정제본 생성기 (제7-A.7장).

변경이력 수락/거절 대신 '표시 본문만 남기기' 방식으로 안전하게 정제한다.
- w:ins 는 본문으로 승격, w:del 은 제거
- w:vanish 숨김 run 제거
- comments/people/commentsExtended 파트 제거
- core/app/custom properties의 작성자 정보 비움
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Dict

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


COMMENT_PARTS = re.compile(r"word/(comments|commentsExtended|commentsIds|people)\.xml$")
AUTHOR_TAGS = {"creator", "lastModifiedBy", "Company", "Manager", "lastPrinted"}


def sanitize_docx(src: Path, dst: Path) -> Dict[str, int]:
    removed = {"tracked_insert_accepted": 0, "tracked_delete_removed": 0,
               "hidden_run_removed": 0, "comment_part_removed": 0, "metadata_field_cleared": 0}
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            name = info.filename
            data = zin.read(name)

            if COMMENT_PARTS.search(name):
                removed["comment_part_removed"] += 1
                continue

            if name == "word/document.xml":
                root = etree.fromstring(data, parser=parser)
                # 삭제 표시 텍스트 제거
                for dele in root.findall(f".//{_q('del')}"):
                    removed["tracked_delete_removed"] += 1
                    dele.getparent().remove(dele)
                # 삽입 표시는 본문으로 승격
                for ins in root.findall(f".//{_q('ins')}"):
                    parent = ins.getparent()
                    index = list(parent).index(ins)
                    for child in list(ins):
                        parent.insert(index, child)
                        index += 1
                    parent.remove(ins)
                    removed["tracked_insert_accepted"] += 1
                # 숨김 run 제거
                for run in root.findall(f".//{_q('r')}"):
                    rpr = run.find(_q("rPr"))
                    if rpr is None:
                        continue
                    vanish = rpr.find(_q("vanish"))
                    color = rpr.find(_q("color"))
                    white = color is not None and (color.get(_q("val")) or "").upper() in ("FFFFFF", "FFFFFE")
                    if (vanish is not None and vanish.get(_q("val")) not in ("0", "false")) or white:
                        run.getparent().remove(run)
                        removed["hidden_run_removed"] += 1
                # 코멘트 참조 정리
                for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
                    for el in root.findall(f".//{_q(tag)}"):
                        el.getparent().remove(el)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

            elif name in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
                try:
                    root = etree.fromstring(data, parser=parser)
                    for el in root.iter():
                        local = el.tag.split("}")[-1] if isinstance(el.tag, str) else ""
                        if local in AUTHOR_TAGS and el.text:
                            el.text = ""
                            removed["metadata_field_cleared"] += 1
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                except Exception:
                    pass

            zout.writestr(info, data)
    return removed
