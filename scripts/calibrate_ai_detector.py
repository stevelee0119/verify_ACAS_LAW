"""AI 작성 판별기 보정 인터페이스(v2 Phase 8).

작성 주체가 확인된 문서 묶음(라벨: AI / HUMAN)으로 규칙 기반 판별기의 점수 분포와 임계값별 오분류를 계산한다.
판정 임계값(ai_document_detector의 0.35·0.65)을 바꾸기 전에 이 결과로 근거를 남기기 위한 도구이며, 라벨 없는
문서로는 보정하지 않는다. 저장소에는 작성 주체가 확인된 문서 묶음이 없으므로 인터페이스만 제공한다.

입력(JSON Lines): {"path": "문서 경로", "label": "AI" | "HUMAN"}
출력: 문서별 점수·판정, 임계값별 오탐(HUMAN을 AI로)·미탐(AI를 놓침) 수, 권장 임계값(오탐 0 조건에서 최소 미탐)

    python scripts/calibrate_ai_detector.py --labels labeled.jsonl --out calibration.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]


def score_documents(labels_path: Path):
    from packages.document_engine import parse_document
    from packages.verification_engine.ai_document_detector import _rule_based_ai_detection

    rows = []
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        path = Path(item["path"])
        data = path.read_bytes()
        doc = parse_document(str(path), document_id=path.stem, filename=path.name, mime_type="",
                             sha256=hashlib.sha256(data).hexdigest())
        result = _rule_based_ai_detection(doc, [], False)
        rows.append({"path": str(path), "label": item["label"], "score": round(result.score, 3),
                     "verdict": result.verdict, "objective_traces": result.signals.get("objective_traces", 0)})
    return rows


def calibrate(rows):
    table = []
    for threshold in THRESHOLDS:
        false_ai = sum(1 for r in rows if r["label"] == "HUMAN" and r["score"] >= threshold and r["objective_traces"])
        missed = sum(1 for r in rows if r["label"] == "AI" and not (r["score"] >= threshold and r["objective_traces"]))
        table.append({"threshold": threshold, "human_flagged_as_ai": false_ai, "ai_missed": missed})
    safe = [t for t in table if t["human_flagged_as_ai"] == 0]
    recommended = min(safe, key=lambda t: (t["ai_missed"], t["threshold"])) if safe else None
    return {"documents": rows, "thresholds": table, "recommended": recommended,
            "note": "사람 작성 문서를 AI로 오판하지 않는(오탐 0) 조건에서 미탐이 가장 적은 임계값을 권장한다. "
                    "권장값은 이 라벨 묶음에 대한 것이며, 판정은 여전히 '참고용, 확정 불가'로 표시한다."}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = calibrate(score_documents(args.labels))
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(report["recommended"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
