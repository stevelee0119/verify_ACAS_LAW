"""Public synthetic TXT/PDF diagnostic; no private or retired corpus access.

Run from /tmp with --source-root to compare a clean public implementation snapshot.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from packages.claim_engine.evidence_consistency import check_exhibits
    from packages.document_engine.registry import parse_document
    from scripts.audit.corpus import build_pdf

    cases = [
        ("갑 제4호증의 1", "냉각도", "배치도", "별지 11쪽", "이동 경로를 설명한다."),
        ("을 제5호증", "운행표", "설비목록", "제 13페이지", "점검 순서를 표시한다."),
        ("병 제6호증의 2", "조명대장", "전력계통도", "첨부 17행", "교체 시점을 기록한다."),
    ]
    result = {}
    with tempfile.TemporaryDirectory(prefix="tk73-public-") as directory:
        for extension in ("txt", "pdf"):
            counts = {"false_positives": 0, "genuine_duplicates": 0}
            for different in (False, True):
                for index, (label, title, other, location, prose) in enumerate(cases):
                    target = other if different else title
                    lines = [f"{label}: {title}, {location}", "원본 표시 구역.", f"{label} {target}: {prose}"]
                    path = Path(directory) / f"public_{different}_{index}.{extension}"
                    if extension == "pdf":
                        build_pdf({"name": path.name, "header": "공개 합성 경계 점검", "footer": "가상 입력",
                                   "body": [("lines", lines[:2]), ("p", lines[2])]}, path)
                    else:
                        path.write_text("\n".join(lines), encoding="utf-8")
                    doc = parse_document(str(path), document_id="public", filename=path.name,
                                         mime_type="application/pdf" if extension == "pdf" else "text/plain",
                                         sha256="0" * 64)
                    if doc.parse_warnings:
                        raise RuntimeError(doc.parse_warnings)
                    found = [f for f in check_exhibits(doc)
                             if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
                    counts["genuine_duplicates" if different else "false_positives"] += len(found)
            result[extension] = counts
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
