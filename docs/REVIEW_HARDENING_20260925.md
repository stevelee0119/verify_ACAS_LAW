# Main review and verification hardening (2026-09-25)

## Compared revisions

- Previous review snapshot: `79dfb11ffd1e60d43c8a57413596747620fc48c4`.
- Antigravity main reviewed: `4a37f9485b05404bcb5595837059343adad819b3`.
- The intervening changes add calendar, cross-document entity, statute-range,
  precedent and calculation checks, sampling coverage, and evaluation safeguards.
- This review follows executable code and regression tests. It does not assign a
  new accuracy score without an independent labelled evaluation under the same
  source, model, OCR and network conditions.

## Improvements retained

| Previous issue | Improvement on incoming main | Additional correction |
| --- | --- | --- |
| Markdown/summary wording promoted AI authorship | Weak formatting signals no longer establish objective traces | Courtesy, disclaimers and Markdown tables are also weak signals |
| Metadata alone influenced authorship too strongly | Objective body traces are required | C2PA container presence is not an AI tool identity |
| Only the first 6,000 characters reached models | Head/middle/tail sampling and coverage added | Count source characters, cap whole-document verdicts, record failed model coverage as zero |
| Windows JSON integrity mismatch | Binary output preserves hashed bytes | Existing integrity regression retained |
| Missing deterministic checks | New date/entity/legal rules connected to pipeline | Correct normal-input false positives and unsupported certainty |
| Environment ambiguity | Environment checks and manifest fields added | One canonical preflight; summary and detail use the same environment |

## Defects corrected

1. Rule-only authorship scanning now respects excluded instruction blocks, as
   model scanning already intended to do. Explicit exclusions precede quote
   masking. Ordinary formatting cannot satisfy the objective-trace threshold.
2. Residue alone cannot establish full-document generation. Unanimous model
   opinions about a sample cannot establish the authorship of omitted text.
   Coverage separates requested characters from usable model review.
3. A Korean date's day suffix is not a Sunday annotation. March 29 is not
   February 29. A yearless February 29 is not assigned an invented year.
4. A statute and its implementing decree no longer share a substring-based
   article limit. Static limits are hints, never a substitute for official
   lookup, historical applicability or source-outage handling.
5. Static precedent and statute snippets no longer masquerade as grade-A
   official evidence or confirmed distortion. Only a quote attached to the
   relevant citation is considered. Static candidates remain advisory.
6. Corrected the date/topic of Supreme Court case `2020da247190` (Korean case
   identifier in code). The actual decision was issued on 2024-12-19 and
   removes fixedness from the ordinary-wage criteria. Official reference:
   https://www.scourt.go.kr/sjudge/1734594587787_164947.pdf
7. Matching sets of dates across documents are not inconsistent. Different
   values without a confirmed common person/event/period remain advisory.
   Unrelated arithmetic is not extracted as overtime hours.
8. Legal pleadings about answer-key theft are not themselves answer keys.
   Rejection requires a standalone filename indicator or explicit header.
9. The manifest no longer overwrites one environment record with another while
   keeping contradictory summary fields. Evaluation requires complete resources;
   failed runs keep diagnostic artifacts but do not publish success-labelled
   evaluation commits.

## Verification

- Incoming-main focused baseline: 82 passed, 2 failed. Both failures concerned
  stale expectations that weak style signals were objective authorship evidence.
- Added `tests/test_review_hardening.py` with normal-input, true-positive,
  unavailable-source, failed-model and scope/coverage regressions.
- Existing positive AI fixtures now contain genuine response-residue markers;
  negative fixtures explicitly cover courtesy/disclaimers/tables. Tests were not
  loosened to accept arbitrary AI classifications.
- Local test artifacts are outside the repository. Final full-suite and
  deployment evidence is recorded in the task completion message and GitHub CI.
- Offline fixtures and mocked model opinions are not live-source, model accuracy,
  cryptographic provenance or real-document forgery validation.

## Remaining work

- Validate provider/source credentials, OCR, latency and cancellation with a
  dedicated authorized live evaluation. Key presence is not connectivity proof.
- Build independent human/AI/mixed-authorship and authentic/tampered document
  holdouts; report precision, recall, false-positive rate and abstention by type.
- Implement and evaluate trusted signature/C2PA verification before presenting
  authenticity as cryptographically established. Metadata alone cannot do this.
- Bind cross-document entities to parties, events and effective dates before
  upgrading heuristic differences to confirmed contradictions.
- Keep deployment on Render. This change adds no infrastructure, service,
  dependency, database migration, or new recurring paid-model execution.
