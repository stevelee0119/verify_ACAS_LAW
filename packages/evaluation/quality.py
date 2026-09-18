"""Reproducible offline metrics with explicit denominators and case-level guards."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
import random
import re
from statistics import mean, median
import unicodedata

from .schemas import LabelRecord, PredictionRecord

DECISIVE = {"VERIFIED", "CONTRADICTED"}


def load_jsonl(path: str | Path, model: type[LabelRecord] | type[PredictionRecord]) -> list:
    records = []
    with Path(path).open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                records.append(model.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path}: invalid record on line {number}: {exc}") from exc
    if not records:
        raise ValueError(f"{path}: empty dataset")
    return records


def validate_case_splits(labels: list[LabelRecord]) -> None:
    """Check all splits before filtering, including exact normalized duplicates.

    Family IDs must include related proceedings and document revisions. These
    guards cannot discover undisclosed relationships or semantic paraphrases.
    """
    if not labels:
        raise ValueError("Label dataset is empty")
    items: set[str] = set()
    seen: dict[tuple[str, str], str] = {}
    families = {}
    for label in labels:
        if label.item_id in items:
            raise ValueError(f"Duplicate item_id: {label.item_id}")
        items.add(label.item_id)
        if families.setdefault(label.case_id, label.case_family_id) != label.case_family_id:
            raise ValueError("A case must belong to exactly one case family")
        text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", label.input_text).casefold())
        identities = [("case", label.case_id), ("family", label.case_family_id),
                      ("normalized_input", sha256(text.encode()).hexdigest())]
        identities += [("source_hash", value) for value in label.source_hashes]
        for key in identities:
            previous = seen.setdefault(key, label.split)
            if previous != label.split:
                raise ValueError(f"Split leakage via {key[0]}: {previous} / {label.split}")


def _prediction_index(predictions: list[PredictionRecord], labels: list[LabelRecord]) -> dict:
    index = {}
    known = {label.item_id for label in labels}
    for prediction in predictions:
        if prediction.item_id in index:
            raise ValueError(f"Duplicate prediction: {prediction.item_id}")
        if prediction.item_id not in known:
            raise ValueError(f"Prediction has no label: {prediction.item_id}")
        index[prediction.item_id] = prediction
    return index


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _metrics(labels, predictions):
    tp = fp = fn = false_verified = verified = decided = gold_unverified = missing = 0
    errors = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for label in labels:
        prediction = predictions.get(label.item_id)
        status = prediction.status if prediction else "ABSTAIN"
        gold = set(label.error_types)
        found = set(prediction.error_types) if prediction else set()
        tp += len(gold & found)
        fp += len(found - gold)
        fn += len(gold - found)
        for error in gold | found:
            errors[error]["tp" if error in gold & found else "fp" if error in found else "fn"] += 1
        missing += prediction is None
        decided += status in DECISIVE
        verified += status == "VERIFIED"
        gold_unverified += label.gold_status != "VERIFIED"
        false_verified += status == "VERIFIED" and label.gold_status != "VERIFIED"
    total = len(labels)
    per_error = {key: {**values, "precision": _ratio(values["tp"], values["tp"] + values["fp"]),
                      "recall": _ratio(values["tp"], values["tp"] + values["fn"])}
                 for key, values in sorted(errors.items())}
    return {
        "items": total, "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
        "f1": _ratio(2 * tp, 2 * tp + fp + fn), "by_error_type": per_error,
        "verified_predictions": verified, "false_verified": false_verified,
        "false_verified_rate": _ratio(false_verified, verified),
        "gold_not_verified": gold_unverified,
        "false_verified_among_nonverified_gold": _ratio(false_verified, gold_unverified),
        "decisive_predictions": decided, "abstentions": total - decided,
        "coverage": _ratio(decided, total), "abstention_rate": _ratio(total - decided, total),
        "missing_predictions": missing, "prediction_completeness": _ratio(total - missing, total),
    }


def _percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (index - lower)


def _summary(values):
    return {"n": len(values), "mean": mean(values) if values else None,
            "p50": median(values) if values else None,
            "p95": _percentile(values, .95) if values else None,
            "total": sum(values) if values else None}


def _resources(labels, predictions):
    records = [predictions[label.item_id] for label in labels if label.item_id in predictions]
    result = {field: _summary([getattr(record, field) for record in records if getattr(record, field) is not None])
              for field in ("latency_ms", "review_seconds")}
    currencies = sorted({record.cost_currency for record in records if record.cost is not None})
    result["cost_by_currency"] = {currency: _summary([record.cost for record in records
                                                     if record.cost_currency == currency])
                                  for currency in currencies}
    return result


def _wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return {"lower": max(0.0, center - radius), "upper": min(1.0, center + radius), "level": .95}


def _uncertainty(labels, predictions, samples, seed):
    cases = defaultdict(list)
    for label in labels:
        cases[label.case_family_id].append(label)
    keys = sorted(cases)
    metrics = ("precision", "recall", "false_verified_rate", "coverage")
    draws = {metric: [] for metric in metrics}
    rng = random.Random(seed)
    if len(keys) >= 2:
        for _ in range(samples):
            selected = [label for key in rng.choices(keys, k=len(keys)) for label in cases[key]]
            measured = _metrics(selected, predictions)
            for metric in metrics:
                if measured[metric] is not None:
                    draws[metric].append(measured[metric])
    unsafe_cases = sum(any(predictions.get(label.item_id) and predictions[label.item_id].status == "VERIFIED"
                           and label.gold_status != "VERIFIED" for label in group) for group in cases.values())
    return {
        "unit": "case_family_id", "independent_case_families": len(keys),
        "bootstrap_samples": samples, "seed": seed,
        "percentile_bootstrap_95": {metric: ({"lower": _percentile(values, .025),
                                               "upper": _percentile(values, .975),
                                               "valid_resamples": len(values)} if values else None)
                                    for metric, values in draws.items()},
        "families_with_false_verified": unsafe_cases,
        "unsafe_case_family_rate": _ratio(unsafe_cases, len(keys)),
        "unsafe_case_family_wilson_95": _wilson(unsafe_cases, len(keys)),
        "limitations": ["Intervals assume independent, representative case families.",
                        "Percentile bootstrap may degenerate for rare/zero events; zero observed errors do not imply zero risk.",
                        "Wilson describes families with any false VERIFIED, not the item-level false VERIFIED rate."],
    }


def _paired_resources(labels, predictions, baseline, samples, seed):
    grouped = defaultdict(list)
    for label in labels:
        current, previous = predictions.get(label.item_id), baseline.get(label.item_id)
        if current is None or previous is None:
            continue
        for field in ("latency_ms", "review_seconds", "cost"):
            now, before = getattr(current, field), getattr(previous, field)
            if now is None or before is None:
                continue
            if field == "cost" and current.cost_currency != previous.cost_currency:
                raise ValueError("Paired cost comparison requires the same currency")
            key = f"cost:{current.cost_currency}" if field == "cost" else field
            grouped[key].append((label.case_family_id, before, now))
    output = {}
    for key, pairs in sorted(grouped.items()):
        cases = defaultdict(list)
        for case, before, now in pairs:
            cases[case].append(now - before)
        keys = sorted(cases)
        rng = random.Random(seed)
        draws = [mean(delta for case in rng.choices(keys, k=len(keys)) for delta in cases[case])
                 for _ in range(samples)] if len(keys) >= 2 else []
        mean_delta = mean(now - before for _, before, now in pairs)
        mean_baseline = mean(before for _, before, _ in pairs)
        output[key] = {"n_pairs": len(pairs), "case_families": len(keys),
                       "mean_baseline": mean_baseline, "mean_current": mean(now for _, _, now in pairs),
                       "mean_delta": mean_delta, "median_delta": median(now - before for _, before, now in pairs),
                       "relative_mean_delta": _ratio(mean_delta, mean_baseline),
                       "mean_delta_case_bootstrap_95": ({"lower": _percentile(draws, .025),
                                                          "upper": _percentile(draws, .975)} if draws else None)}
    return output


def _fingerprint(records):
    value = [record.model_dump(mode="json") for record in sorted(records, key=lambda record: record.item_id)]
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def evaluate_quality(
    labels: list[LabelRecord], predictions: list[PredictionRecord], *, split: str = "TEST",
    baseline: list[PredictionRecord] | None = None, origin: str | None = None,
    bootstrap_samples: int = 1000, seed: int = 0,
) -> dict:
    """Score supplied predictions, not synthetic truth or a hidden inference engine.

    Baseline deltas are current minus baseline (negative means less time/cost).
    Missing predictions count as abstentions and missed error labels. Unmeasured
    resource values remain missing. No real/synthetic metrics are silently pooled.
    """
    if split not in {"DEVELOPMENT", "VALIDATION", "TEST"}:
        raise ValueError("Unknown split")
    if origin not in {None, "SYNTHETIC", "ATTORNEY_LABELED"}:
        raise ValueError("Unknown origin")
    if not 100 <= bootstrap_samples <= 10000:
        raise ValueError("bootstrap_samples must be between 100 and 10000")
    validate_case_splits(labels)
    index = _prediction_index(predictions, labels)
    baseline_index = _prediction_index(baseline, labels) if baseline is not None else None
    selected = sorted((label for label in labels if label.split == split and (origin is None or label.origin == origin)),
                      key=lambda label: label.item_id)
    if not selected:
        raise ValueError("Selected evaluation cohort is empty")
    origins = {label.origin for label in selected}
    if len(origins) != 1:
        raise ValueError("Do not pool synthetic and attorney-labeled data; select an origin")
    synthetic = origins == {"SYNTHETIC"}
    measured = _metrics(selected, index)
    report = {
        "schema_version": 1, "split": split, "origin": selected[0].origin,
        "quality_claim": "SYNTHETIC_TOOLING_DEMONSTRATION_ONLY" if synthetic else "MEASURED_ON_DECLARED_ATTORNEY_LABELS",
        "real_world_quality_proof": False,
        "notice": ("Synthetic labels and predictions exercise tooling only; these scores are not real-world accuracy."
                   if synthetic else "Accuracy applies only to this labeled cohort; review representativeness and annotation provenance."),
        "case_count": len({label.case_id for label in selected}), "metrics": measured,
        "resources": _resources(selected, index), "uncertainty": _uncertainty(selected, index, bootstrap_samples, seed),
        "reproducibility": {"labels_sha256": _fingerprint(labels), "predictions_sha256": _fingerprint(predictions),
                            "bootstrap_samples": bootstrap_samples, "seed": seed,
                            "prediction_system_versions": sorted({p.system_version for p in predictions}),
                            "prediction_run_ids": sorted({p.run_id for p in predictions})},
        "definitions": {"precision": "TP / (TP + FP) over item/error-type labels",
                        "recall": "TP / (TP + FN), including missing/abstained predictions",
                        "false_verified_rate": "incorrect VERIFIED / all predicted VERIFIED",
                        "coverage": "(VERIFIED + CONTRADICTED) / all labeled items",
                        "abstention_rate": "all other statuses and missing predictions / all labeled items",
                        "null": "undefined denominator or metric not measured",
                        "split_guard_limit": "Explicit case/family IDs, normalized duplicates and declared source hashes; not semantic leak detection"},
    }
    if baseline_index is not None:
        previous = _metrics(selected, baseline_index)
        keys = ("precision", "recall", "false_verified_rate", "coverage", "abstention_rate")
        report["baseline"] = {"metrics": previous, "resources": _resources(selected, baseline_index),
                              "quality_delta": {key: measured[key] - previous[key]
                                                if measured[key] is not None and previous[key] is not None else None for key in keys},
                              "paired_resource_delta": _paired_resources(selected, index, baseline_index, bootstrap_samples, seed)}
        report["reproducibility"]["baseline_sha256"] = _fingerprint(baseline)
    return report
