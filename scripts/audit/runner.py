"""합성 PDF 사건 묶음을 실제 검증 파이프라인에 넣어 결과·JSON·docx·요약 점수를 얻는다(v4 P0)."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from . import corpus as C


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_synthetic(workdir: Path | None = None) -> Dict[str, Any]:
    workdir = Path(workdir or tempfile.mkdtemp(prefix="lv-audit-"))
    os.environ.setdefault("LV_DATA_DIR", str(workdir / "data"))
    os.environ.setdefault("LV_DATABASE_URL", f"sqlite:///{workdir}/audit.db")
    os.environ.setdefault("LV_STORAGE_ROOT", str(workdir / "storage"))
    os.environ.setdefault("LV_PSEUDONYM_SECRET", "audit-secret")
    os.environ["LV_ALLOW_NETWORK"] = "0"

    from packages.pii_engine import PseudonymStore
    from packages.source_adapters import SourceRegistry
    from packages.source_adapters.local_mirror import LocalLegalMirror
    from packages.verification_engine import pipeline as module
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

    mirror = LocalLegalMirror(C.write_mirror(workdir / "mirror"))
    registry = SourceRegistry()
    registry.mirror = mirror
    registry.legal[0].mirror = mirror
    module.PseudonymStore = lambda project_id: PseudonymStore(project_id, root=workdir / "vault")

    documents = C.write_documents(workdir / "docs")
    inputs = [DocumentInput(f"doc{i}", str(path), name, "application/pdf", _sha(path))
              for i, (name, path) in enumerate(documents.items(), start=1)]
    pipeline = VerificationPipeline(registry=registry)
    result = pipeline.run("audit-run", ProjectContext("audit-project"), inputs)

    from packages.report_engine.docx_report import build_report_docx
    from packages.report_engine.exporters import to_payload
    payload = to_payload(result)
    docx_text = ""
    try:
        from io import BytesIO

        from docx import Document
        document = Document(BytesIO(build_report_docx(result)))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        docx_text = "\n".join(parts)
    except Exception as exc:  # 보고서 생성 실패도 감사 결과로 남긴다
        docx_text = f"<docx 생성 실패: {type(exc).__name__}: {exc}>"
    names = {d.document_id: d.filename for d in inputs}
    return {"result": result, "payload": payload, "docx_text": docx_text, "names": names, "workdir": workdir}
