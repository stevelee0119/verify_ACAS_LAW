"""Offline, case-separated evaluation of externally supplied predictions."""
from .schemas import LabelRecord, PredictionRecord
from .quality import evaluate_quality, load_jsonl, validate_case_splits

__all__ = ["LabelRecord", "PredictionRecord", "evaluate_quality", "load_jsonl", "validate_case_splits"]
