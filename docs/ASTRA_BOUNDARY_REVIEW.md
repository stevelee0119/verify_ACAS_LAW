# Astra follow-up: evidence boundaries

Baseline: `a6d92db67a2c2dbb319f70359871a4093e623caf` (main, 0.9.3).

## Improvements already on main

- The v6 audit removed static copies of selected case holdings and statute texts.
  Citation content must instead pass through the official-source comparison path.
- Unsupported pleading conflicts were converted to advisory review findings.
- Version 0.9.1 added table continuation, compound formulas, party-role binding,
  injection regressions, and a scorer that separates reference signals from defects.
- Version 0.9.2 improved report layout. These changes are preserved.

## Reproduced defects and changes

Seven independent synthetic acceptance probes failed on the baseline. These are
counterexamples, not a representative accuracy benchmark or blind evaluation.

| Boundary | Baseline defect | Change |
| --- | --- | --- |
| Currency units | Header units were removed without scaling the values | Convert bare numbers to won using header/row units; explicit cell units are not scaled twice |
| Signed money | Negative deductions became positive through `abs` | Preserve the parsed sign and apply the formula operator separately |
| Unknown components | Present but unreadable optional interest became zero | Distinguish absent components from unreadable/blank components; reject partial numeric parses |
| Party identity | Sharing a case and the role "plaintiff" proved identity | Require the fact store's unambiguous name evidence as well; compare identified people separately |
| Statute identity | Different laws with the same article number matched | Compare normalized law name, level, article, and any specified paragraph/item |
| Evaluation coverage | An empty control document could pass | Require positive extraction evidence and document-scoped core-engine execution evidence |
| Precision | Correct OCR abstention could produce precision above 100% | Separate abstention from defect recall and use the same defect-claim population in precision's numerator and denominator |

Rules are versioned as `2026.09.26.5`. The scorer is `eval_v4-scorer-3`; v2 and v3
numbers are not directly comparable. Existing reports are not overwritten.
No hosting service, external dependency, or production database schema was added.

## Validation and remaining limits

`tests/test_astra_boundaries.py` contains the seven reproductions plus positive and
negative controls for unit conversion, signed values, unknown cells, statutory
identity, execution coverage, OCR abstention, and multiple parties. Existing
scorer and engine tests retain their positive controls. A previous expectation
that role alone proves identity was intentionally changed to advisory status.

Identity promotion currently reuses the conservative masked-name parser in the
fact store. Unrecognized real names, ambiguous names, plural roles, and facts
without a confirmed shared case cannot support a definitive cross-document
contradiction. This is evidence of inconsistent document statements, not proof
of the underlying real-world fact.

Offline fixtures and CI do not prove live legal-source connectivity, LLM accuracy,
AI authorship, or document authenticity. Production-source checks and a separately
held blind evaluation are still required. No blind answer key or stored blind
evaluation output was used to develop these changes.

Release gate: push the work branch, require successful CI for its exact commit,
then fast-forward main only if the current remote main is an ancestor. Verify the
same commit and database health at the Render health endpoint after deployment.
