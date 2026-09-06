"""제21.1장 업로드 보안 검사.

MIME/파일크기 검증, Malware Scan 훅, ZIP bomb·XXE·Path traversal 방어.
외부 백신이 없는 환경에서도 최소한의 구조 검사를 수행한다.
"""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

MAX_ZIP_ENTRIES = 5000
MAX_ZIP_RATIO = 200
MAX_TOTAL_UNCOMPRESSED = 400 * 1024 * 1024

# 실행 가능 파일 시그니처는 법률문서로 업로드될 이유가 없다
EXECUTABLE_SIGNATURES = [
    (b"MZ", "Windows 실행파일"),
    (b"\x7fELF", "ELF 실행파일"),
    (b"\xca\xfe\xba\xbe", "Mach-O 실행파일"),
    (b"#!/bin/sh", "셸 스크립트"),
    (b"#!/bin/bash", "셸 스크립트"),
]

ZIP_BASED_SUFFIXES = {".docx", ".docm", ".dotx", ".hwpx", ".xlsx", ".xlsm", ".xltx"}


def scan_upload(filename: str, data: bytes) -> Optional[str]:
    """문제가 있으면 사유 문자열을, 없으면 None을 반환한다."""
    head = data[:64]
    for signature, label in EXECUTABLE_SIGNATURES:
        if head.startswith(signature):
            return f"실행 가능 파일은 업로드할 수 없다({label})"

    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and not data.lstrip()[:8].startswith(b"%PDF"):
        return "PDF 시그니처가 확인되지 않는다"

    if suffix in ZIP_BASED_SUFFIXES:
        if not data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            return "ZIP 기반 문서의 시그니처가 확인되지 않는다"
        issue = _scan_zip(data)
        if issue:
            return issue

    if b"<!ENTITY" in data[:200_000] and b"SYSTEM" in data[:200_000]:
        return "외부 엔티티 선언(XXE 시도 가능)이 포함되어 있다"

    return None


def _scan_zip(data: bytes) -> Optional[str]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return f"ZIP entry 수가 과도하다({len(infos)})"
            total = 0
            for info in infos:
                name = info.filename
                if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                    return f"경로 탈출이 의심되는 entry가 있다: {name}"
                total += info.file_size
                if (
                    info.compress_size > 0
                    and info.file_size / max(1, info.compress_size) > MAX_ZIP_RATIO
                    and info.file_size > 5_000_000
                ):
                    return f"ZIP bomb이 의심되는 entry가 있다: {name}"
            if total > MAX_TOTAL_UNCOMPRESSED:
                return f"압축 해제 크기가 과도하다({total} bytes)"
    except zipfile.BadZipFile:
        return "손상된 ZIP 구조이다"
    return None
