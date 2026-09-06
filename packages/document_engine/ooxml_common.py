"""OOXML/HWPX 공통 ZIP·XML 안전 처리.

제21.1장 ZIP bomb·XXE·Path traversal 방어를 파서 계층에서 강제한다.
"""
from __future__ import annotations

import zipfile
from typing import Dict, List, Optional

MAX_TOTAL_UNCOMPRESSED = 400 * 1024 * 1024
MAX_RATIO = 200
MAX_ENTRIES = 5000


class ZipSafetyError(Exception):
    pass


def safe_open_zip(path: str) -> zipfile.ZipFile:
    zf = zipfile.ZipFile(path)
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ZipSafetyError(f"ZIP entry 수 초과: {len(infos)}")
    total = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            raise ZipSafetyError(f"경로 탈출 의심 entry: {name}")
        total += info.file_size
        if info.compress_size > 0 and info.file_size / max(1, info.compress_size) > MAX_RATIO and info.file_size > 5_000_000:
            raise ZipSafetyError(f"ZIP bomb 의심 entry: {name}")
    if total > MAX_TOTAL_UNCOMPRESSED:
        raise ZipSafetyError(f"압축 해제 크기 초과: {total}")
    return zf


def parse_xml(data: bytes):
    """외부 엔티티를 차단한 XML 파서(XXE 방어)."""
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    return etree.fromstring(data, parser=parser)


def read_entries(zf: zipfile.ZipFile, predicate) -> Dict[str, bytes]:
    out: Dict[str, bytes] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        if predicate(info.filename):
            try:
                out[info.filename] = zf.read(info.filename)
            except Exception:
                continue
    return out


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def local_name(tag: str) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) and "}" in tag else str(tag)
