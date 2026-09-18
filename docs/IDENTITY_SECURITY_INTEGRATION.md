# Identity, authorization and vault integration

## Parent integration checklist

`apps/api/routers/projects.py` is already integrated: collection handlers carry
`@project_scoped`, lists are filtered before serialization, creation assigns
server-derived owner/organization IDs, both idempotency-return branches authorize
the existing project, organization AI policy is applied to create/update, and
HTTP audit events use `actor_id()`. An explicit `submitted_on: null` clears the date.

The following integration belongs to the parent because these files are outside
the auth implementation's write scope:

1. Import and include `apps.api.routers.identity.router` with prefix `/api` in
   `main.py`. Keep `app.middleware("http")(workspace_access)` registered exactly
   once. Import identity models before `init_db()` or metadata migration discovery.
2. Include the new identity models in Alembic metadata and create their tables.
   Import `apps.api.identity` in migration setup before reading `Base.metadata`.
   Do not enable multi-user mode against a database lacking these tables.
3. Add `PyJWT[crypto]>=2.10,<3` to dependencies for SSO. `boto3` is optional and is
   imported only for an explicitly selected AWS KMS provider.
4. Replace HTTP-boundary `payload.reviewer`, `"local-user"`, or default `"system"`
   actors in verification/reveal/report/download/viewer routes with `actor_id()`.
   Set `FindingRow.reviewed_by = actor_id()`. Existing review/reveal JSON requests
   are additionally normalized by the middleware, but handlers should use the
   helper directly. Workers must retain a trusted actor supplied by the server;
   do not invent a local-owner identity outside an authenticated request.
5. Keep organization `forced_ai_policy`, `blocked_providers`, and
   `block_sealed_reveal` enforced when constructing verification/LLM contexts and
   revealing/exporting sealed data. Create/update clamping alone does not enforce
   a policy changed after an existing project or queued run was created.
6. Apply query filtering to any global resource list/search/export added later.
   The middleware denies unrecognized routes and unintegrated project collection
   handlers. A new global collection needs an explicit policy, not an exemption.

## Tables

All four models share `apps.api.db.Base`; existing User/Organization/Project and
ProjectMember models are reused without schema changes.

| Model / table | Columns and constraints |
| --- | --- |
| IdentityAccount / identity_accounts | user_id String(40) PK, FK users.id; enabled Boolean NOT NULL; created_at DateTime NOT NULL |
| ApiToken / identity_api_tokens | id String(40) PK; user_id String(40) NOT NULL FK users.id, indexed; token_hash String(64) NOT NULL UNIQUE; label String(120) NOT NULL; created_at, expires_at DateTime NOT NULL; revoked_at DateTime nullable |
| ExternalIdentity / identity_external | id String(40) PK; user_id String(40) NOT NULL FK users.id, indexed; issuer String(500) NOT NULL; subject String(255) NOT NULL; UNIQUE(issuer, subject) |
| BrowserSession / identity_browser_sessions | id String(40) PK; user_id String(40) NOT NULL FK users.id, indexed; secret_hash String(64) NOT NULL UNIQUE; source_kind String(12) NOT NULL; source_id String(40) NOT NULL; created_at, expires_at DateTime NOT NULL; revoked_at DateTime nullable |

Defaults are Python defaults as declared in the models. Credentials are randomly
generated with 256 bits of entropy. Only their SHA-256 digests are stored.

## Request contracts

```python
from apps.api.identity import (
    current_principal, actor_id, visible_project_ids, filter_project_query,
    project_creation_defaults, apply_organization_policy, require_project,
)

principal = current_principal()  # also accepts an optional Request
actor = principal.user_id       # identical to actor_id()
ids = visible_project_ids(session)  # list[str]; None only for authenticated local owner
defaults = project_creation_defaults(session)  # owner_id, organization_id
changes = apply_organization_policy(session, changes, project=project)
require_project(session, project_id, "MEMBER")  # VIEWER, MEMBER, ADMIN
```

Calling a principal/actor helper without request context raises 401. The local
principal is always `local-owner`, including local mode authenticated with
`LV_ACCESS_TOKEN`. Helpers never infer identity from payloads, email claims,
role claims, organization claims, or client-supplied actor headers.

Organization ADMIN users administer only their own organization. Other users
need ownership or ProjectMember membership. Project owners/admin members manage
project access; organization VIEWER always caps project access at read-only.
Cross-organization grants cannot confer access. Projects without an organization
remain invisible in multi-user mode until an operator explicitly assigns them.

Project-related audit queries should apply both project and access constraints
before limits, aggregation or export:

```python
require_project(session, project_id)
statement = select(AuditEventRow).where(AuditEventRow.project_id == project_id)
statement = filter_project_query(statement, session, AuditEventRow.project_id)
rows = session.scalars(statement.order_by(AuditEventRow.sequence.desc()).limit(limit)).all()
```

`/api/audit/verify` remains local-only because it verifies the global hash chain.
Do not present a filtered subset as a complete hash-chain verification. Project
audit/manifest endpoints remain available after project authorization.
Process-global provider settings are read-only in multi-user mode.

## Browser and token APIs

| Endpoint | Contract |
| --- | --- |
| GET /api/identity/me | Authenticated user_id, organization_id, role, authentication; 401 requests login |
| POST /api/identity/session | Authorization: Bearer token-or-verified-JWT; empty body; returns identity and expires_at; sets acas_session cookie |
| DELETE /api/identity/session | Cookie and matching Origin; revokes the current browser session and clears its cookie |
| GET/POST /api/identity/users | Organization admin only; POST email, display_name, role; organization comes from the principal |
| PATCH /api/identity/users/{user_id} | Organization admin; role and/or enabled; disabling revokes tokens and sessions |
| GET/POST /api/identity/users/{user_id}/tokens | Self or organization admin; POST label, days (1..365); returns the secret once |
| DELETE /api/identity/tokens/{token_id} | Self or organization admin; immediate revocation, including derived browser sessions |
| POST /api/identity/users/{user_id}/oidc | Organization admin; explicit subject binding to the configured issuer; no auto-provisioning |
| DELETE /api/identity/oidc/{binding_id} | Organization admin; unbind SSO and invalidate derived sessions |
| GET /api/projects/{project_id}/members | Project admin |
| PUT/DELETE /api/projects/{project_id}/members/{user_id} | Project admin; PUT role; target must be a provisioned user of the same organization |

The browser cookie is HttpOnly, SameSite=Lax, Path=/api, Secure when using HTTPS,
and expires within eight hours or at the source credential's expiry, whichever
is sooner. API-token revocation, SSO unbinding, session revocation and account
disable are rechecked on every request. Cookie mutations require an exact
matching Origin; cross-site Fetch Metadata is rejected. Use same-origin fetch
with `credentials: "same-origin"`; private `<img>` PNGs and downloads then work
without exposing a token to a URL. Never put credentials in query strings or
localStorage. An invalid Authorization header cannot fall back to a valid cookie.

In multi-user mode only GET/HEAD `/` and `/static/...` are public. All API data,
including health/diagnostics, requires authentication. The static directory must
contain application assets only, never uploaded documents or generated artifacts.

In local mode the original boundary is retained: without `LV_ACCESS_TOKEN`, only
loopback peer AND loopback Host are allowed; with that variable set, the root
issues a native Basic challenge. Any username with the configured token as the
password works. The authenticated browser reuses Basic credentials and `/me`
returns `authentication: "local"`; it does not need a session exchange. A local
Bearer API request also remains supported. Cookie exchange is for multi-user mode.

## Configuration and bootstrap

| Variable | Meaning |
| --- | --- |
| LV_AUTH_MODE | `local` (backward-compatible default) or explicit `multi-user`; any other value fails closed |
| LV_ACCESS_TOKEN | Existing single-owner local boundary only; ignored by multi-user authentication |
| LV_OIDC_ISSUER | Exact trusted HTTPS issuer |
| LV_OIDC_AUDIENCE | API audience; required with the issuer and JWKS URL |
| LV_OIDC_JWKS_URL | Explicit trusted HTTPS JWKS endpoint; never taken from the token |
| LV_OIDC_ALGORITHMS | Comma-separated asymmetric allowlist; default RS256; HS* and none are rejected |
| LV_TRUSTED_PROXY_IPS | Explicit comma-separated immediate proxy peers allowed to assert X-Forwarded-Proto: https; default none |
| LV_PUBLIC_ORIGIN | Optional exact external origin used for CSRF validation behind a proxy |

Multi-user API access requires HTTPS except when both peer and Host are loopback.
For TLS termination, restrict server access to the proxy, configure its actual
peer IPs, overwrite forwarded headers there, and set LV_PUBLIC_ORIGIN to the
external HTTPS origin. Do not enable globally trusted forwarded headers in the
ASGI server: middleware cannot recover an original peer/scheme already rewritten
by an incorrectly configured server. Local remote Basic/token access also needs
HTTPS at deployment time, as in the original local boundary.

Apply migrations, then run the one-time offline bootstrap from the repository:

```text
.venv\Scripts\python.exe -m apps.api.identity --email admin@example.org --organization "Example"
```

This creates the first organization/admin and prints a one-day token once. It
refuses to run after an IdentityAccount exists. No bootstrap HTTP endpoint exists.
Store the returned token securely; use the admin API to provision users and issue
replacement credentials. Existing legacy projects are not silently adopted.

JWT validation requires a signature, issuer, audience, sub, iat and exp; validates
expiry and nbf; pins allowed algorithms; and looks up the exact (issuer, subject)
binding. Token email/role claims do not create or elevate accounts. JWKS lookup
uses a bounded timeout and refreshes for key rotation. This is bearer-JWT
verification, not an authorization-code login flow. See the official
[PyJWT verification documentation](https://pyjwt.readthedocs.io/en/stable/usage.html)
and [algorithm allowlist guidance](https://pyjwt.readthedocs.io/en/stable/api.html).

## Vault providers and rotation

The default has no network dependency. With no explicitly configured legacy
secret/keyring, a random local keyring is created at
`LV_DATA_DIR/secrets/vault-keys.json`. Protect that directory with owner-only OS
permissions/Windows ACLs and back it up separately from vault data. Explicit
missing/corrupt key files fail closed; no replacement key silently opens data.

| Variable | Meaning |
| --- | --- |
| LV_VAULT_KEY_PROVIDER | `file`, `env`, or explicit `aws-kms` |
| LV_VAULT_KEY_FILE | Existing private JSON file with active and keys; omit for generated local default |
| LV_VAULT_KEYS | JSON map of key ID to base64-encoded random 32-byte key |
| LV_VAULT_ACTIVE_KEY_ID | Key ID used for new encryption in the environment keyring |
| LV_PSEUDONYM_SECRET | Compatibility with explicitly configured legacy environment secrets; the public development placeholder is rejected for new encryption |
| LV_VAULT_LEGACY_SECRET | Explicit old raw secret when importing legacy AES/stream vaults into the selected provider |
| LV_VAULT_KMS_KEY_ID | Active KMS key ARN, not an alias |
| LV_VAULT_KMS_DECRYPT_KEY_IDS | Retained old key ARNs permitted for decryption |
| LV_VAULT_KMS_REGION | Optional explicit AWS region |

New vaults keep the AES-family prefix `ACAS2:` and use the unambiguous `K3:`
envelope marker. AES-256-GCM authenticates project ID, envelope version and key
metadata. Only key IDs and KMS-encrypted data keys are persisted alongside the
ciphertext. Legacy AES and authenticated stream vaults are read and migrated on
the next save when their old raw key is explicitly available.

For file keys, `FileKeyProvider.rotate()` retains old keys and selects a new key.
For environment keys, retain old entries and change LV_VAULT_ACTIVE_KEY_ID.
For KMS, retain old ARNs in LV_VAULT_KMS_DECRYPT_KEY_IDS. Re-save each vault with
the new active provider/key before retiring old keys. Crossing from a versioned
file/env provider to another provider requires decrypting with the old provider
and re-encrypting with the new one; changing configuration alone does not migrate
an already versioned envelope. Wrong, retired or unavailable keys stop processing
and preserve the existing vault. No plaintext key is stored in the database or
logged. KMS credentials are obtained only when the operator explicitly selects
that provider; the test suite uses an injected fake client.

AWS uses GenerateDataKey(AES_256), verifies the returned key ARN, and supplies
the same project-bound encryption context to Decrypt. See official
[KMS envelope encryption](https://docs.aws.amazon.com/kms/latest/developerguide/kms-cryptography.html),
[Decrypt](https://docs.aws.amazon.com/kms/latest/APIReference/API_Decrypt.html), and
[encryption-context rules](https://docs.aws.amazon.com/kms/latest/developerguide/encrypt_context.html).

## Focused validation

Use a fresh writable temporary directory for each test run on this host:

```text
.venv\Scripts\python.exe -m pytest tests/test_identity_security.py -q --basetemp=artifacts/pytest-identity-security-unique
```

The tests use isolated SQLite, generated RSA keys with mocked JWKS retrieval,
and an injected KMS client. They do not consume live credentials or contact AWS/SSO.
