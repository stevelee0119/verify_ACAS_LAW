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
- Check each file's current metadata, parents, download permission and revision.
  Read changed files only. Verify revision after download and MD5 when available.
- Cache extracted chunks and file SHA-256 under `LV_STORAGE_ROOT/reference-cache`.
  Removed files are deleted from this cache after a successful complete listing.
  Revoked, moved, changed-but-unreadable files are excluded even when cached.
- A run records UTC check time, eligible revisions/hashes, omissions, retrieved page
  excerpts and model executions. This is a best-effort snapshot, not an atomic Drive
  transaction; concurrent changes after each access check cannot be locked out.
- Retain the existing Render persistent disk. Ephemeral disks lose the cache and
  make the next run re-index. The cache is rebuildable, not the original document
  repository. Past run evidence remains historical evidence, never fresh input.

## Retrieval and Evidence Boundaries

SQLite FTS5/BM25 with Korean character bigrams performs lexical retrieval locally.
Each folder cache has a 512 MiB SQLite size cap and each search a 5-second query budget.
This is retrieval-augmented generation, **not semantic embedding search**. Duplicate
excerpts do not fill all six retrieval slots. Current implementation searches the
first 12,000 document characters plus requested issues and discloses truncation.

Up to six retrieved excerpts are sent through the existing LLM router, with the
same LOCAL_ONLY/MASKED/ORIGINAL policy, organization restrictions, output quarantine,
budget ledger and model audit. Titles and excerpts are masked under MASKED policy.
QUICK or unavailable models yield RETRIEVED_ONLY. Quarantined documents are not sent.
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
