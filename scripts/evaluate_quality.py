"""Evaluate case-separated JSONL labels/predictions without network or inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.evaluation import LabelRecord, PredictionRecord, evaluate_quality, load_jsonl


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--split", choices=["DEVELOPMENT", "VALIDATION", "TEST"], default="TEST")
    parser.add_argument("--origin", choices=["SYNTHETIC", "ATTORNEY_LABELED"])
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--schema", choices=["labels", "predictions"], help="Print JSON Schema and exit")
    args = parser.parse_args(argv)
    if args.schema:
        result = (LabelRecord if args.schema == "labels" else PredictionRecord).model_json_schema()
    else:
        if args.labels is None or args.predictions is None:
            parser.error("--labels and --predictions are required unless --schema is used")
        try:
            result = evaluate_quality(
                load_jsonl(args.labels, LabelRecord), load_jsonl(args.predictions, PredictionRecord),
                split=args.split, origin=args.origin,
                baseline=load_jsonl(args.baseline, PredictionRecord) if args.baseline else None,
                bootstrap_samples=args.bootstrap_samples, seed=args.seed,
            )
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
    serialized = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
