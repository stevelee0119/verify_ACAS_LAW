# Verification Completeness Review

Base: `5a8dd7d974ccc68ae79dbd3cc09fac9aeb89117f` (0.9.11).
Change: 0.9.12, rule version `2026.09.27.5`.

## Implemented

- Summarize findings from every legal-claim engine; an empty citation table is not legal clearance.
- Preserve source objects and AI/argument fields through the database report export path.
- Keep pooled references flat on repeated export, including long inline excerpts. Record unresolved references explicitly. `RESOLVED` checks reference availability, not source authenticity or an independent signature.
- Distinguish the constitutional standard of review from the challenged provision.
- Deduplicate overlapping criminal-relief findings; resolve numbered relief references for provisional execution.
- Refer missing inference steps concerning fraud, damages proof, employee/company claims and private constitutional effects for human review. These are not AI-authorship or fabrication findings.
- Leave substantive parenthetical claims unverified when only numerical comparison was available.
- Detect machine-directed automatic approval, Korean warning suppression and audit-bypass flags; remove detected text despite reflow and include complete flagged blocks rather than truncated excerpts.
- Validate RAG evidence per item. Keep valid quote pairs, record rejected item reasons, distinguish attempted calls, accepted responses, partial review and valid empty advice. The provider fallback remains bounded to one additional call.
- Preserve supported punctuation in embedded Korean PDF fonts; restrict CID-only substitutions to CID output.
- Repair the existing startup test expectation for the 120-second migration bound and test timeout failure explicitly.

## Evaluation Boundaries

The supplied report's five visible-text snapshots were replayed with their original bounding boxes and block attributes. The original PDFs were no longer present at the supplied Downloads paths during implementation. This replay does not revalidate hidden PDF layers, signatures, OCR, live legal sources or model services.

- Case 2: direct and Korean indirect instructions were detected and removed. Rescanning the resulting body produced no remaining instruction findings in this fixture; this is not a guarantee against all prompt injection.
- Case 3: six distinct issues were represented: criminal relief, its provisional-execution cross-reference, fraud inference, third-party damages, damages proof and dismissal without examination. Four are explicitly human-review items. The constitutional-target false positive and duplicate criminal-relief issue were removed.
- Case 5: no added claim-rule warnings in the saved body. This does not make it a clean legal baseline; its precedent citations still require independent verification.

The new regression inputs omit test-case titles and expected answers. Existing input PDFs and reports were not edited or committed. Synthetic controls do not measure real-world AI-authorship or forgery accuracy.

The base main CI run `36291043587` failed three startup expectations because the implementation passed `timeout=120` and the tests expected only `check=True`. This change retains the timeout and updates the test contract, rather than weakening the startup bound.

## Remaining Work

- Run authenticated production analysis to verify current Drive revisions, provider executions and accepted quote pairs. Unit mocks and public health do not establish this integration.
- Expand claim-based retrieval across long documents. The existing 12,000-character model window is disclosed; truncated or partly rejected reviews remain incomplete.
- Validate incomplete reference-page extraction, including OCR and genuinely blank pages, without treating missing pages as read.
- Build an independently reviewed holdout corpus with verified clean citations, real human/AI provenance and genuine pre/post-tamper file pairs.
- Re-run old analyses to obtain corrected summaries. Re-export cannot reconstruct source objects that were already lost in a legacy standalone JSON.

## Release Gate

Push the work branch first. Only fast-forward main after CI for the exact work-branch commit succeeds and the fetched remote main is still its ancestor. A failed CI or diverged main must not be merged. Confirm the deployed commit through `/api/health` and the changed public static asset; report integration limitations separately.
