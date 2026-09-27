"""실행 결과 JSON의 문서 본문(보이는 층)으로 결정론 엔진만 다시 돌려, 버전 간 결과를 비교한다.

네트워크·AI·공식 DB 조회를 하지 않는다. 숨은 층·메타데이터·OCR 층은 실행 JSON에 없으므로 재현하지 않는다.
비교 대상: 법령명 추출, 보이는 본문의 지시문 탐지(MEDIUM 이상), 법리 규칙.

사용:
  python scripts/replay_run_json.py RUN.json > now.json
  (다른 버전 작업 트리에서 같은 명령으로 before.json을 만든 뒤)
  python scripts/replay_run_json.py --diff before.json now.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def replay(run: dict) -> dict:
    from packages.adversarial_engine import AdversarialScanner
    from packages.common.schemas import BBox, Block, NormalizedDocument, Page
    from packages.legal_engine.citation_extractor import extract_citations
    from packages.legal_engine.legal_rules import review_legal_rules
    from packages.legal_engine.claim_review import review_claims
    from packages.verification_engine.sanitized_input import sanitized_reading_text

    out = {}
    for doc in run.get("documents", []):
        pages = [Page(p["page_number"], width=p.get("width", 0), height=p.get("height", 0), blocks=[
            Block(b["block_id"], b["text"], b.get("page") or p["page_number"],
                  bbox=BBox(*b["bbox"]) if b.get("bbox") else None,
                  source_layer=b.get("source_layer") or "visible_text",
                  block_type=b.get("block_type") or "paragraph", visible=b.get("visible", True),
                  attributes=b.get("attributes") or {})
            for b in p.get("blocks", [])]) for p in doc.get("pages", [])]
        nd = NormalizedDocument(doc["document_id"], doc.get("filename", ""), "application/pdf",
                                doc.get("sha256") or "0", pages=pages)
        scan = AdversarialScanner().scan(nd)
        legal = review_legal_rules(nd)
        legal += review_claims(nd, skip_sentences=[f.confidence_features.get("claim", "") for f in legal])
        clean, sanitization = sanitized_reading_text(nd, scan.findings)
        sanitized_doc = NormalizedDocument("sanitized", "sanitized.txt", "text/plain", "0",
                                          pages=[Page(1, blocks=[Block("clean", clean, 1)])])
        out[doc.get("filename") or doc["document_id"]] = {
            "scope": "SAVED_VISIBLE_TEXT_ONLY_NO_LIVE_SOURCES_OR_MODELS",
            "sha256": nd.sha256,
            "sanitization": sanitization,
            "remaining_instruction_findings": [str(f.type) for f in AdversarialScanner().scan(sanitized_doc).findings
                                               if not f.advisory_only],
            "laws": sorted({c.law_name for c in extract_citations(nd) if getattr(c, "law_name", None)}),
            "adversarial": sorted({f"{f.type.value}:{f.severity.value}" for f in scan.findings
                                   if not f.advisory_only and f.severity.value in ("MEDIUM", "HIGH", "CRITICAL")}),
            "rules": sorted({str(f.confidence_features.get("rule_id")) for f in legal}),
            "legal_findings": [{"rule_id": f.confidence_features.get("rule_id"),
                                "status": str(f.status), "page": f.page, "title": f.title} for f in legal],
        }
    return out


def diff(before: dict, after: dict) -> list:
    rows = []
    for name in sorted(set(before) | set(after)):
        for key in ("laws", "adversarial", "rules"):
            old, new = set(before.get(name, {}).get(key, [])), set(after.get(name, {}).get(key, []))
            if old != new:
                rows.append({"document": name, "item": key, "removed": sorted(old - new), "added": sorted(new - old)})
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--diff", action="store_true", help="두 replay 결과(before, after)를 비교")
    args = parser.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    result = diff(load(args.paths[0]), load(args.paths[1])) if args.diff else replay(load(args.paths[0]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
