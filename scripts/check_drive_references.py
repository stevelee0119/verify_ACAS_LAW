"""Run on the Render worker with its real environment, not fixture mirrors.

  python -m scripts.check_drive_references               # full sync summary and connection log (JSON)
  python -m scripts.check_drive_references --duplicates  # identical copies you can delete from Drive
"""
import json
import sys

from packages.common.config import get_settings
from packages.rag_engine.library import ReferenceLibrary


def duplicate_lines(summary):
    lines = []
    for group in summary.get("duplicates", []):
        keep = group["keep"]
        lines.append(f"[보존] {keep['folder_path']}/{keep['name']}".replace("[보존] /", "[보존] "))
        for copy in group["delete_candidates"]:
            lines.append(f"  [삭제 후보] {copy['folder_path']}/{copy['name']} ({copy['size']:,} bytes) {copy['url']}"
                         .replace("[삭제 후보] /", "[삭제 후보] "))
    total = sum(g["reclaimable_bytes"] for g in summary.get("duplicates", []))
    lines.append(f"중복 묶음 {len(summary.get('duplicates', []))}개, 삭제 시 {total / 1048576:.1f}MiB 절약")
    for group in summary.get("similar_names", []):
        lines.append("[이름만 같음·내용 다름, 확인 필요] " + " | ".join(
            f"{f['folder_path']}/{f['name']}".lstrip("/") for f in group["files"]))
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    library = ReferenceLibrary(get_settings())
    result = library.sync()
    if "--duplicates" in argv:
        print("\n".join(duplicate_lines(result)))
    else:
        # No reference contents, tokens, private paths or API keys in the diagnostic output.
        print(json.dumps({k: v for k, v in result.items() if k != "sources"}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
