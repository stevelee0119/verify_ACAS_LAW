"""제6.1장 Parser Interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from packages.common.schemas import NormalizedDocument


class DocumentParser(ABC):
    name: str = "base"
    extensions: List[str] = []
    mime_types: List[str] = []

    def supports(self, mime_type: str, filename: str = "") -> bool:
        if mime_type and mime_type.lower() in self.mime_types:
            return True
        suffix = Path(filename).suffix.lower()
        return suffix in self.extensions

    @abstractmethod
    def parse(self, path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
        """원본을 수정하지 않고 NormalizedDocument를 생성한다."""


class ParserError(Exception):
    pass
