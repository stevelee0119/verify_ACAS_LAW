# Drive Reference RAG

Google Drive is the source of truth. No corpus documents are committed to Git,
downloaded into the Docker image, or sent to a separate vector database service.
The NotebookLM notebook is not scraped. Use the original Drive folder instead.

## Render Setup

Set these on the API service **and every separate worker**:

| Variable | Value |
| --- | --- |
| `LV_RAG_DRIVE_FOLDER_ID` | `1fbGA2Ifw9282Nu0ieVWPegAt_GJkdAtM` |
| `LV_DRIVE_API_KEY` | Secret API key from a project with Drive API enabled; restrict the key to Drive API |
| `LV_RAG_SYNC_SECONDS` | `120` (bounded to 600) |
| `LV_RAG_MAX_FILES` | `1000` (bounded to 5000) |
| `LV_RAG_DOWNLOAD_MB` | `128` per run (bounded to 512) |

The API-key option only reads publicly accessible files. A Gemini key is not
automatically a working Drive key: its project must enable Drive API and its key
restrictions must permit it. Never put keys into chat, source code, URLs or Git.

For a private library, use a dedicated service account, share only this folder
with that account as Viewer, and store its JSON in a Render Secret File. Set
`LV_DRIVE_SERVICE_ACCOUNT_FILE=/etc/secrets/drive-reader.json` instead of the API
key. Only the `drive.readonly` scope is requested; no domain-wide delegation.
Service-account mode takes precedence when both are configured.

This is an **administrator-configured common reference library for all projects
on this deployment**, not a personal Drive connection. Do not point it at private
case files or a folder whose readers differ between projects. User uploads never
enter this shared index. The current supplied folder has public-reader permission;
the program does not create or broaden any sharing permission.

Existing Render services may not automatically apply new Blueprint variables.
Register them in Environment and redeploy. Leave the folder variable empty to
disable RAG. Missing credentials with a configured folder produce an explicit
UNAVAILABLE result; they do not silently disable checks.

## Freshness and Cache

- Every new analysis has a new refresh request identity. A completed old analysis
  is never returned before Drive can be checked. Refresh runs in the durable worker,
  not while an API request holds the project transaction.
- Recursively list all accessible children with pagination (depth 12, 200 folders).
  Incomplete or failed listings make the entire cached corpus ineligible.
- The listing read at the start of each run already carries every file's parents, trash
  state, download permission and revision. An unchanged cached file is reused on that
  basis without a second per-file request (so large libraries do not stall on request
  latency). A new or changed file is re-read just before download, and its revision is
  verified again after download, with MD5 when available.
- Access decisions have distinct codes: `REFERENCE_TRASHED`, `REFERENCE_DOWNLOAD_BLOCKED`,
  `REFERENCE_MOVED`. A move is inferred only when a fresh response names parents and the
  folder whose listing returned the file is not among them. Drive may omit `parents` for
  API-key (anonymous) reads of link-shared files; an omitted field is not a move. The
  fields behind each rejection (parent IDs and flags only) are logged in
  `diagnostics.access_checks` (first 10). The cache revision no longer includes parents.
- With an API key only link-shared ("anyone with the link") folders are listed. A subfolder
  with narrower sharing is invisible to the listing and therefore absent from `folder_paths`.
- Identical copies (same MD5 and size) are listed as delete candidates and only one
  kept copy is downloaded and indexed. If the kept copy is unusable, a copy is used.
  Copy markers such as "…의 사본", " (1)" and "Copy of" are ignored when reading a
  file's format, so copies keep their PDF/HWP/TXT format.
- Instruction-like text in a reference: pages carrying a HIGH/CRITICAL machine-instruction
  finding are excluded and the rest of the file is indexed (`REFERENCE_INSTRUCTION_PAGES_EXCLUDED`,
  `excluded_pages`) when the file has at least 10 pages and the flagged pages are at most 2%
  of them (minimum 1, maximum 3). Otherwise, or when the signal cannot be tied to a page
  (metadata, hidden layer, encoding), the whole file is quarantined (`REFERENCE_QUARANTINED`).
  Either way `scan_findings` (type, severity, page, path, intents, 60-character excerpt, first
  5) is logged in the inventory entry. Cached whole-file quarantines from earlier versions,
  which carried no evidence, are re-read once.
- Cache extracted chunks and file SHA-256 under `LV_STORAGE_ROOT/reference-cache`.
  Removed files are deleted from this cache after a successful complete listing.
  Revoked, moved, changed-but-unreadable files are excluded even when cached.
- A run records UTC check time, eligible revisions/hashes, omissions, retrieved page
  excerpts and model executions. This is a best-effort snapshot, not an atomic Drive
  transaction; concurrent changes after each access check cannot be locked out.
- Retain the existing Render persistent disk. Ephemeral disks lose the cache and
  make the next run re-index. The cache is rebuildable, not the original document
  repository. Past run evidence remains historical evidence, never fresh input.

## Pre-open Selection: Only Candidate Files Are Opened

During an analysis the library lists the whole folder tree first (metadata only: folder
path, file name, description, size, revision). It then opens (downloads and extracts)
only candidate files (`packages/rag_engine/relevance.py`, `metadata_gate`):

1. **Name/path match** (`NAME_PATH_MATCH`): terms of each file's folder path, name and
   description are weighted by rarity among the library's own names (digits, copy markers
   and short Latin words removed). A file is a candidate when the checked document's text
   covers at least 0.25 of that weight with at least 2 shared terms.
2. **Drive full-text search** (`DRIVE_FULLTEXT_MATCH`): for each document the two most
   salient repeated content words (particles and pleading boilerplate removed) are sent
   as `fullText contains` queries restricted to the listed folders (40 folders per query).
   Drive searches its own index, so files with uninformative names are still found
   without being downloaded. If the search fails (HTTP error, network), the failure is
   logged and selection falls back to names and paths.
3. At most 24 candidates are opened per run (`CANDIDATE_LIMIT` for the rest, highest
   score first). Non-candidates that are not cached are marked `NOT_SELECTED_METADATA`
   and never downloaded. Already cached, unchanged files are reused at no cost.
4. The relevance gate below then decides, from the opened text, whether any excerpt is
   used. If nothing is selected, Drive material is not used.

Why this design instead of "open every file whose name looks related": names in a real
library are often generic (for example "결과보고서", "업무편람"), so a name-only rule either
opens too much or misses files. Drive's server-side full-text search checks contents
without downloads, while the name/path gate keeps the rule transparent. An unexpected
defect in the selection step is recorded as `metadata_gate.error` with
`fallback: ALL_FILES_BY_PRIORITY` so Drive review is not stopped. A sync without a query
(`scripts.check_drive_references`) still indexes every file to warm the cache.

Opening order is per document: each document's candidates are ranked by their own name
score, and a file's `rank` is its best position for any document. Every document's first
candidate is opened before any document's second, so a short sync budget is not spent on
one document. `diagnostics.deferred` counts only selected candidates left for a later run.

Full-text search refusals: Drive may refuse `fullText contains` (HTTP 403), notably for
API-key access. A refused multi-folder query is retried once folder by folder; if that is
also refused the run records `DRIVE_FULLTEXT_FORBIDDEN`, sets `fulltext_available: false`
and stops further full-text calls (names and paths still select files). The Drive error
reason code (for example `insufficientFilePermissions`) is logged per call as `reason`;
messages, URLs and keys are not logged. A service account with the folder shared to it is
the credential mode in which full-text search is expected to work (unverified here).

`diagnostics.metadata_gate` records thresholds, full-text searches (terms, file count or
error), selected and not-selected counts and time; each `inventory` entry carries its
`gate` (score, matched terms, full-text hit, reason, selected).

## Relevance Gate: Drive Is Used Only When Relevant

Before any excerpt reaches a model, the library decides whether any Drive file is
relevant to the checked document (`packages/rag_engine/relevance.py`):

1. Key terms of the document are weighted by their frequency in the document times their
   rarity (IDF) in the indexed Drive chunks; terms in more than half of the chunks of a
   corpus with 20+ chunks are treated as boilerplate.
2. Text coverage of a chunk = share of that weighted key-term mass the chunk contains.
3. Folder/file-name coverage = share of the file's folder-path and name terms (weighted by
   rarity among the library's own names, copy markers removed) that the document uses.
4. File score = best chunk coverage + 0.5 x name coverage. A file is selected only when
   its text coverage is at least 0.14, it shares at least 4 key terms (fewer for a very
   short query), and its file score is at least 0.25. A name alone never selects a file.
5. Up to three excerpts per selected file, six in total, are used. If no file passes,
   the document's RAG status is `NOT_RELEVANT` and **Drive material is not used**; this is
   an outcome, not an unfinished check, and not proof that no authority exists.

The thresholds were set on a synthetic calibration set (17 synthetic references in
topic folders; 11 tuning and 11 separately worded check queries, 6 related and 5
unrelated each). Both sets gave 6/6 related documents using the expected file and 5/5
unrelated documents not using Drive; zero-error settings spanned text floors 0.12-0.16
and file scores 0.25-0.28. This is a small synthetic calibration, not a measurement on
the real library. Every selection log records the thresholds and each candidate's text
coverage, name coverage and score, so real run JSON can be used to re-calibrate.

## Connection Log in the Run JSON

`run_manifest.reference_library` in the downloaded result JSON contains:

- `health` (always present, also when Drive is off, with `enabled`, `disabled_reason`, `credentials_configured`): listing success, credential mode (`api_key`, `service_account`, `none`),
  API call and error counts, files seen/indexed/reused, duplicate groups, sync time and,
  per document, the RAG status, whether Drive was used, files selected and sources used.
- `diagnostics`: start/finish time, budget, stage timings (inventory, files), folder paths,
  file types, downloads (count/bytes), extractions (count/ms), skipped duplicates,
  deferred files, issue counts and the Drive API call log (operation, HTTP status,
  milliseconds, bytes, file ID; at most 300 calls). URLs, keys and tokens are not logged.
- `duplicates` / `similar_names`: identical copies with the kept file and delete
  candidates (Drive links), and same-named files whose content differs.

Each document's `engine_data.rag.selection` holds the relevance decision, reason,
thresholds, shared key terms and the top candidate files with their scores.
`python -m scripts.check_drive_references --duplicates` prints the delete-candidate list.

## Retrieval and Evidence Boundaries

SQLite FTS5/BM25 with Korean character bigrams performs lexical retrieval locally.
Each folder cache has a 512 MiB SQLite size cap and each search a 5-second query budget.
This is retrieval-augmented generation, **not semantic embedding search**. Duplicate
excerpts do not fill all six retrieval slots. Current implementation searches the
first 12,000 document characters plus requested issues and discloses truncation.

Up to six retrieved excerpts are sent through the existing LLM router, with the
same LOCAL_ONLY/MASKED/ORIGINAL policy, organization restrictions, output quarantine,
budget ledger and model audit. Titles and excerpts are masked under MASKED policy.
QUICK or unavailable models yield RETRIEVED_ONLY; no relevant file yields NOT_RELEVANT. A quarantined document is searched and reviewed with its detected instruction blocks and strings removed (`engine_data.rag.input`); if nothing remains it is SKIPPED.
Both the model's claim quote and reference quote must occur exactly in the provided
text; fabricated source IDs/quotes or invalid output schemas are rejected.

Quote matching does not prove entailment, legal validity, currency of a law, AI
authorship or forgery. All accepted opinions remain advisory; no RAG opinion changes
deterministic findings/scores or overrides official legal-source verification.
No hit does not prove absence or fabrication.

PDF text layers, TXT/MD/CSV, DOCX, HWP/HWPX and XLSX are supported. Native Docs export
as text, Slides as PDF and Sheets as XLSX. Shortcuts and unsupported formats are
reported, not traversed outside the configured folder. PDF extraction is text-only:
scanned/blank pages and partial reading are disclosed. Upload searchable versions
of scanned books, or split oversized references in Drive; do not embed them in code.

Each extraction is isolated in a subprocess (30 seconds, 1,500 PDF pages, 3 million
characters; 256 MiB virtual-memory limit on Linux). This is a resource/time boundary,
**not an OS security sandbox**. The
child receives no API credentials. Existing archive checks and adversarial scanning
run before indexing. Per-file download is capped at 96 MiB. Parsed timeout/failure
outcomes are cached for that revision so bad files cannot repeatedly starve later
ones. Replace the file in Drive to retry, or clear the rebuildable reference cache
during maintenance. Sync stops within its bounded budget plus one network timeout;
first runs over a large library can be partial while the cache warms.

Cache text is local disk data and is not covered by uploaded-original envelope
encryption. Use only the intended common library, Render disk access controls, and
appropriate retention. Saved excerpts in historical reports follow report sharing
and PII masking rules.

## Verification

Run `python -m scripts.check_drive_references` in the Render worker environment.
Exit 0 means every accessible listed reference was indexed without a reported
limitation. Exit 2 means disabled, unavailable, partial or omitted content; inspect
the stable issue codes. This command makes real Drive calls, but no LLM calls.

Then run an authenticated document analysis and inspect
`run_manifest.reference_library`, `documents[].engine_data.rag`, model executions,
the result screen and PDF/DOCX reports. The health capability only describes
configuration and explicitly sets `connectivity_verified=false`.

Unit tests use mocked Drive responses and real extraction subprocesses. They prove
refresh/failure boundaries, not live Google authentication or production coverage.

Official references: [Drive search and public-folder API keys](https://developers.google.com/workspace/drive/api/guides/search-files),
[downloads and exports](https://developers.google.com/workspace/drive/api/guides/manage-downloads),
[read-only scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
