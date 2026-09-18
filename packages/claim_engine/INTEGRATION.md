# Claim Analysis and Calculation Contracts

All added Claim/Entity/Event fields have backwards-compatible defaults. Pass the
project and source run explicitly when extracting a run snapshot:

```python
extract_claims(doc, citations=None, *, project_id=None, source_run_id=None) -> list[Claim]
extract_events(doc, *, project_id=None, source_run_id=None) -> list[Event]
extract_entities(doc, *, project_id=None) -> list[Entity]
resolve_entities(entities, *, project_id=None) -> list[Entity]
claim_contradictions(claims, *, project_id) -> list[Finding]
match_evidence_references(claims, items, *, project_id) -> list[EvidenceMatch]
search_claim_candidates(query, claims, *, project_id, limit=10, minimum_score=0.2) -> list[ClaimCandidate]
```

These functions are exported from `packages.claim_engine`. `speaker_text` and
`target_text` retain extracted surface labels; `speaker_id`/`target_id` are explicit
IDs, not inferred name identities. `transaction_id` and `event_identity` are
separate. Payments without individual identity are not compared. Quoted,
reported, conditional, alternative, negated and ambiguous assertions are excluded
from factual contradiction comparison. Findings remain advisory UNVERIFIED
assertion conflicts or identity/context candidates, not legal proof.

Entity resolution merges only explicit IDs or `explicit_aliases` in the same
known project, rejects conflicting identifier groups and does not mutate inputs.
Legacy `aliases`, equal names, substrings and lexical search scores do not merge
entities. Canonical IDs are deterministic from the project, type and explicit
identifier anchor (or explicit alias group). Adding/changing that anchor can
change a canonical ID; persist reviewed identities in the parent application.

Evidence references have exact branch-sensitive keys such as `갑:12:2`. `page`
is the citing page; `page_start`/`page_end` are cited pages. `span` uses half-open
offsets into the citing block. Run/document/hash locations are retained.
`EvidenceItem(project_id, reference_key, document_id, source_run_id,
document_sha256, available_pages)` supplies the included evidence catalog.
Matching locates references only and keeps relationship UNASSESSED. Human
support/refutation decisions belong in the parent's separate assessment records.

## Segmented Interest

```python
calculate_segmented_interest(
    *, principal: Decimal, start_date: date, end_date: date,
    rate_periods: list[RatePeriod], payments: list[AllocatedPayment],
    assumptions: InterestAssumptions,
) -> SegmentedInterestResult
```

`RatePeriod(start_date, end_date, annual_rate_percent, source)` is always a
half-open date interval. `AllocatedPayment(payment_id, paid_on, amount, principal,
interest, source)` requires amount = principal + interest. No legal allocation
priority, costs, interest capitalization or statutory rate is supplied.

`InterestAssumptions` requires day_count_convention, include_start, include_end,
rounding, rounding_quantum, rounding_stage, payment_timing, allocation_policy,
principal_source, period_source, convention_source, confirmed_by and a true
user_confirmed. Values are ACT/365F, ACT/360 or ACT/ACT; ROUND_HALF_UP,
ROUND_HALF_EVEN, ROUND_DOWN or ROUND_UP; SEGMENT or FINAL; START_OF_DAY or
END_OF_DAY; and EXPLICIT allocation. Decimal inputs must be finite, nonnegative,
at most 28 significant/integer digits and at most 12 fractional digits.

ACT/ACT splits at calendar-year boundaries. Endpoint flags choose actual accrual
days. Payments are applied at the chosen start/end of their date, clamped to the
calculation's accrual boundaries; the original payment date remains in `payments`.
SEGMENT rounding occurs at each rate/payment/year interval. FINAL allocation
checks use unrounded accrued interest; the final rounding adjustment gets its own
ROUNDING audit row when nonzero. Paid interest cannot exceed interest accrued.

Result `.to_dict()` emits decimal strings and ISO dates. Schedule kinds are
ACCRUAL, PAYMENT and ROUNDING. Each row retains its source, principal balances,
interest balance, rate/day denominator or payment allocations. Sum posted interest
minus paid interest to reconcile the final balance. `arithmetic_only` is true.

`POST /api/calculations/interest/segmented` accepts the same nested fields. All
request schemas live in `apps/api/routers/calculations.py`; invalid inputs return
422. Send decimal strings, not JSON floating-point numbers. The legacy simple
endpoint is retained.

Load `apps/web/static/calculation-workbench.js` after the existing app/workflow
helpers and call `calculationWorkbench.init()`. It idempotently appends inside
`[data-panel='calculations']`. It resets confirmation after changes, discards stale
responses, clears the worksheet when the visible panel changes project, and
exports the complete calculation result as JSON. No app.js or index.html changes
are included in this module.

Immediately after assigning `state.project`, call
`calculationWorkbench.onProjectChange()` (alias: `.sync()`), or dispatch
`document.dispatchEvent(new CustomEvent("acas-project-changed"))`. Events on
`window` are also supported. No event detail is required: the current
`state.project?.id` is authoritative. The hook returns true when it cleared a
different project's worksheet, false otherwise, and is safe before init.
Switching projects, including closing a project, clears all fields, confirmations
and results even while the panel stays visible, aborts pending fetches and
invalidates late successes/errors. The new worksheet is immediately usable;
an old request's cleanup cannot change a new request's busy state. Repeated
same-project events preserve current inputs.

Offline quality evaluation and JSONL annotation contracts are documented in
`packages/evaluation/README.md`. Synthetic examples demonstrate tooling only.
