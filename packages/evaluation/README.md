# Offline Quality Evaluation

This evaluator scores external predictions against a versioned JSONL label
contract. It does not generate predictions or infer labels from engine results.
The bundled labels, reviewer names, timings, costs and predictions are synthetic.
They demonstrate metric arithmetic and failure cases, not real-world accuracy.

Run from the repository root using the existing environment:

```powershell
.venv\Scripts\python.exe scripts/evaluate_quality.py --labels tests/fixtures/analysis_completion/labels.jsonl --predictions tests/fixtures/analysis_completion/predictions.jsonl --baseline tests/fixtures/analysis_completion/baseline.jsonl --seed 7
.venv\Scripts\python.exe scripts/evaluate_quality.py --schema labels
.venv\Scripts\python.exe scripts/evaluate_quality.py --schema predictions
```

Label each item/error-type pair, retaining the exact source run, page, block and
half-open character offsets in `annotation.sources`. Use `case_family_id` for all
related proceedings, document revisions and derivatives. Assign families to one
of DEVELOPMENT, VALIDATION or TEST before tuning. Case IDs, family IDs, normalized
input duplicates and declared source hashes are checked across the entire dataset,
even when only TEST is evaluated. These checks do not detect undisclosed case
relationships or paraphrased leakage.

ATTORNEY_LABELED records require two distinct reviewer IDs, confirmed qualifications
and adjudication. This is a provenance contract, not authentication of reviewers.
Never label synthetic examples as attorney-reviewed real cases. Synthetic and
attorney-labeled cohorts cannot be pooled: use `--origin` to select one cohort.

Precision/recall count item/error-type matches. False VERIFIED rate uses predicted
VERIFIED as its denominator; the alternative non-VERIFIED-gold denominator is also
reported. Missing predictions are abstentions and contribute false negatives.
Coverage counts only VERIFIED and CONTRADICTED. Undefined ratios are null.

Input fingerprints, run/system versions, seed and bootstrap sample count make
reports reproducible. Percentile intervals resample whole case families. Rare
events and small samples can make these intervals degenerate. The separate Wilson
interval measures families containing any false VERIFIED, assuming independent
families. Zero observed errors is not a zero error probability.

Resource measurements are optional. Missing values are never zeros. Costs retain
their currency. Baseline comparisons pair identical item IDs; deltas are current
minus baseline, so negative time/cost deltas mean reductions. Different currencies
cannot be compared. Review-time comparisons are descriptive and do not establish
causal productivity gains without a suitable study design.
