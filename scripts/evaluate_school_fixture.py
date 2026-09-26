"""Offline reproduction, not proof of live legal/Drive/model connectivity."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # The working directory selects the revision under evaluation.
    sys.path.insert(0, str(Path.cwd()))
    with tempfile.TemporaryDirectory(prefix="school-eval-") as directory:
        os.environ.update(LV_ALLOW_NETWORK="0", LV_RAG_DRIVE_FOLDER_ID="",
                          LV_DATA_DIR=directory, LV_STORAGE_ROOT=directory + "/storage",
                          LV_DATABASE_URL="sqlite:///" + directory.replace("\\", "/") + "/test.db")
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            os.environ.pop(key, None)
        from packages.common.enums import ExternalAIPolicy
        from packages.common.storage import sha256_file
        from packages.report_engine import to_json
        from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

        started = time.monotonic()
        result = VerificationPipeline().run("school-evaluation", ProjectContext(
            "school-evaluation", case_date="2026-06-20", external_ai_policy=ExternalAIPolicy.LOCAL_ONLY),
            [DocumentInput("school-fixture", str(args.pdf.resolve()), args.pdf.name,
                           mime_type="application/pdf", sha256=sha256_file(args.pdf))])
        payload = json.loads(to_json(result))
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"state": str(result.state), "findings": len(result.all_findings),
                          "seconds": round(time.monotonic() - started, 2), "bytes": args.output.stat().st_size,
                          "errors": result.errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
