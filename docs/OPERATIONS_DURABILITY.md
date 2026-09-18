# Durable Jobs and Central Budget Ledger

This implements the operations portion of plan F10 and the stability/remaining-status
items: immutable run inputs, atomic submission and claims, recoverable dispatch,
leases and heartbeats, bounded retries, cancellation, fenced publication, and shared
budget reservations. It does not implement archival replay of external sources.

## Main and Migration Integration

Import the model modules before `init_db()` or Alembic metadata inspection:

```python
from apps.api import job_control
from packages.llm_router import budget
from apps.api.routers import jobs
from apps.api.services import get_runner
```

All models use the existing `apps.api.db.Base`. The new tables are `durable_jobs`,
`job_attempts`, `budget_accounts`, and `budget_reservations`. The parent-owned
migration must create their indexes and unique constraints, including job
deduplication, one retry child per parent, and one attempt per run/fence. No columns
are added to shared models. Run migrations before starting production workers.

Register `jobs.router` with `/api`. Attach lifespan when constructing FastAPI:

```python
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(get_runner().start)
    try:
        yield
    finally:
        await asyncio.to_thread(get_runner().stop)

app = FastAPI(..., lifespan=lifespan)
```

`start()` is idempotent, immediately adopts legacy queued rows and recovers expired
leases, then starts periodic polling. `recover()` is also callable explicitly.
`stop(timeout=10)` stops polling and waits for local workers up to the timeout. A
process killed with unfinished work leaves leases for another poller to recover.
Keep at least one poller running. Live leases are never reclaimed just because a
second API instance starts.

The original `workers.celery_app` entrypoint and `verification.run` task still call
`services.execute_run`, which now takes the same database lease as local workers.
For a standalone Celery deployment without an API poller, use:

```text
celery -A apps.worker.celery_app worker -l info -Q verification,report
```

This entrypoint starts/stops recovery with Celery worker lifecycle signals. Broker
messages are delivery hints. A lost publish/ack or duplicate message cannot bypass
the database claim; undelivered queued jobs become dispatchable again after 30
seconds. Explicit Celery mode retains queued work on broker failure; auto mode may
fall back locally. Local worker capacity is per process, not cluster-wide.

## Verification Route Integration

`apps/api/routers/verification.py` is already integrated. It builds the complete
snapshot before the reuse key, calls `enqueue_run(session, unsaved_run, force=...)`,
commits the returned canonical run/job together, then submits that run ID. The
return value is `(run, reused)`. Do not pre-add/flush the new run outside this helper.
Its unique key resolves racing submissions; `force=True` creates a new run.
Reusable successful jobs retain that key to close the completion/enqueue race. Failed,
cancelled and partial jobs release it. Only completed runs qualify for result reuse.

Snapshots include context/issue dates, manually recorded issues, selected document
IDs, hashes, storage references, filenames, individual ownership flags, source
availability, engine versions, provider configurations, configured prices and budget
limits. API key *environment names* are recorded, never their values. Provider URLs
with embedded credentials, query strings or fragments are rejected.

Workers read these snapshots, verify original bytes and reject incompatible parser
or rule/prompt settings. They never rebuild inputs from changed project fields or
current document selection. Authentication secrets remain live configuration.
External source availability/content can change between attempts; retries repeat
the saved input contract rather than reproduce a prior external response byte for
byte. Legacy queued rows can be frozen at adoption; historical terminal runs without
a durable snapshot require a new verification rather than an inferred retry.

Saved inputs never override current organization restrictions. Execution clamps the
saved AI policy against the current project/organization policy, unions blocked
providers and preserves reveal blocks. It only restricts, never widens. Removed or
reassigned saved organizations, missing policies and invalid policy values fail
closed. Provider permission is checked again in the reservation-dispatch transaction;
a request prepared under ORIGINAL cannot be sent after a change to MASKED or
LOCAL_ONLY. Existing in-flight requests cannot be recalled. Legacy snapshots lacking
organization identity can validate the current project association but cannot
reconstruct a previously removed association.

Results record `effective_security` and `security_restricted` separately. A completion
under restrictions different from the saved inputs releases its deduplication key
and is excluded from completed-result reuse. This prevents a later policy relaxation
from reusing a result as though it had executed under the original broader policy.
Restrictions observed during an attempt remain in force for the rest of that attempt.

The verification route captures `submission.actor_id`, `organization_id` and
`authentication` from the server principal, after computing the semantic reuse key.
No token, credential ID or client-supplied actor is saved. Worker audit actor is
`system:worker`, with the original submission identity in its payload; retries keep
that identity and separately record the retry actor in their check record. Workers
do not require or manufacture an HTTP principal. ATTEMPT_STARTED records the
effective security policy separately from immutable input snapshots.

Progress, audit events, completed-document checkpoints, execution records, errors
and final publication require a valid owner/fence and unexpired lease. The fence is
checked while holding a database write lock in the transaction that writes results.
Cancellation removes ownership immediately. A request already dispatched to an
external provider may finish and incur a charge; its financial reservation can still
settle, but its stale worker cannot publish verification records.

Completed document checkpoints and execution/error history are retained per attempt.
Automatic transient-failure recovery repeats the same run with exponential backoff.
An explicit retry creates one idempotent child of a failed, cancelled or partial run
and copies its inputs. Prior results, errors and attempts remain available. A retry
of that same parent returns the same child; retry the failed child to create a later
generation. Retry descendants share the original run's budget account.

## Jobs API

| Method and Path | Contract |
| --- | --- |
| `GET /api/verification-runs/{id}/job` | Durable state, attempt count/limit, availability/heartbeat/lease timestamps, parent ID, error code, attempt history. |
| `POST /api/verification-runs/{id}/cancel` | HTTP 200 `RunOut`. Idempotent, preserves completed states and existing results. |
| `POST /api/verification-runs/{id}/retry` | HTTP 202 child `RunOut`. HTTP 409 for an ineligible run or missing historical durable snapshot. |

`resolve_job_project` and `project_id_for_run` resolve authorization through the
run's project. Inspection requires VIEWER; cancellation/retry require MEMBER. The
existing run GET/SSE APIs remain the source of pipeline progress. Durable job states
are `QUEUED`, `RUNNING`, `BACKOFF` and terminal run states; BACKOFF maps to QUEUED in
`RunOut`. Timestamp values are UTC, following existing naive DB timestamp storage.

Status deliberately exposes only partial-result **summaries** (document IDs, counts,
quarantine flags), numeric execution metadata, recognized provider/role codes and
fixed error codes. It does not return checkpoint text, filenames, evidence excerpts,
model reply text, arbitrary model names or raw exception strings. Full records stay
in the DB; this is enforced independently of exporter redaction.

Legacy finding review now uses the authenticated actor and the structured workflow
CAS helper for its first save. When a structured workflow already exists, the legacy
endpoint returns 409; clients should GET then PUT `/findings/{id}/workflow` with the
expected revision. Reveal audit events also use the authenticated actor.

## Budget Semantics

`BudgetLedger` stores integer nanodollars and exposes Decimal amounts. Amounts round
up at the storage boundary. Admission updates shared monthly and run accounts in one
transaction before a provider can be dispatched. SQLite uses `BEGIN IMMEDIATE`;
PostgreSQL uses row locks. Different routers/processes sharing the same DB therefore
share both spent and reserved balances. A rejected request does not consume budget;
a tightened nonzero cap remains stored even if that request is rejected.

With configured nonzero caps, admission enforces `spent + reserved + estimate <= cap`
for both the UTC reservation month and the original run. Zero explicitly means no
configured cap. Stored limits only tighten automatically; configuration drift to a
larger or zero limit does not silently reopen an existing account. Lower current
runtime limits also apply to older queued snapshots. Deliberate cap increases need
an operator-controlled ledger update, not a fresh router instance or retry.

Reservations cover the configured maximum input-token capacity plus the request's
bounded output tokens, at configured model prices (provider-price fallback remains
supported). UTF-8 byte length plus protocol overhead is a conservative input
admission check. Exact reported usage settles the reservation and releases excess.
Missing usage settles conservatively at the reserved estimate. The existing Gemini
adapter omits thought-token usage, so its cost stays labelled ESTIMATED at the full
reservation. Tiny reported amounts are not rounded to zero in router totals.

Unknown pricing blocks external calls unless `LV_LLM_UNKNOWN_CALL_USD` explicitly
supplies a conservative call ceiling. Local providers do not consume this external
model budget. Exceptions, timeouts and crashes after dispatch keep uncertain charges
reserved indefinitely, including across restarts. Never expire those holds on worker
lease expiry. Only undispatched reservations may be automatically released.
After reconciling provider usage, an operator can use the idempotent
`BudgetLedger.settle(reservation_id, Decimal(actual_usd))`; contradictory settlements
are rejected. Reservations remain attributed to the UTC month of admission.

This is a shared admission ledger against configured prices and bounds, **not a
provider invoice guarantee**. Maintain prices/bounds for each deployed model; calls
outside this router, vendor price changes, unknown fees or underdeclared bounds are
not controlled by it. If reported usage exceeds a reservation, the ledger records
the full amount and flags the overrun rather than hiding it or capping the record.
No claim is made about a monthly cap when the limit is zero or calls use other DBs.

## Configuration

These settings are read in the owned modules; no shared Settings/schema additions
are required. Use the same configuration and database across API/worker processes.

| Environment Variable | Default |
| --- | --- |
| `LV_JOB_LEASE_SECONDS` | `90`; heartbeat interval is one third of the lease |
| `LV_JOB_MAX_ATTEMPTS` | `3` |
| `LV_JOB_BACKOFF_SECONDS` | `5`; exponential, capped at 300 seconds |
| `LV_JOB_POLL_SECONDS` | `2` |
| `LV_JOB_CONCURRENCY` | `2` local threads per process |
| `LV_MONTHLY_BUDGET_USD` | Existing setting, `0` disables the cap |
| `LV_RUN_BUDGET_USD` | `0` disables the cap |
| `LV_LLM_MAX_INPUT_TOKENS` | `131072` |
| `LV_LLM_MAX_OUTPUT_TOKENS` | `4096`; oversized requests are rejected |
| `LV_LLM_UNKNOWN_CALL_USD` | Unset; unknown pricing blocks calls |

## Validation and References

Use a unique workspace temp directory on machines whose default pytest temp root
is inaccessible:

```text
.venv\Scripts\python.exe -m pytest -q -o addopts= tests/test_operations_completion.py tests/test_worker.py tests/test_release_gates.py tests/test_api.py tests/test_improvements.py --basetemp=artifacts/pytest-operations-UNIQUE
```

Coverage includes SQLite process/thread reservation races, hard-exit crashes, shared
retry budgets, atomic enqueue rollback, concurrent submit/claim, backoff, heartbeat,
startup recovery, cancellation, publication/audit fencing, mocked Celery delivery,
snapshot/secret handling, authorization, status redaction and legacy workflow CAS.
Live PostgreSQL/broker/provider testing requires their separate integration setup.

The transaction handling follows [SQLAlchemy's SQLite transaction guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).
Database ownership is necessary even with [Celery late acknowledgement and worker-loss redelivery](https://docs.celeryq.dev/en/stable/userguide/tasks.html).
The conservative Gemini handling follows [Google's thinking-token billing and output-limit documentation](https://ai.google.dev/gemini-api/docs/generate-content/thinking).
