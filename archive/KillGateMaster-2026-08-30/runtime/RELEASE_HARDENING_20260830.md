# Release correctness update — August 30, 2026

The eight issues in the supplied review are addressed in the active `runtime/` source.
The original source was copied to `../release-baseline-20260830-1839/` before edits;
real environment files, credentials, local customer data, and virtual environments
were excluded from that source copy. `extras/` was not changed. The pre-change suite
had 209 passing tests (the pasted review described an earlier 205-test snapshot).

This directory has no Git metadata. These are local file changes, not a commit,
remote push, production migration, deployment, or store release.

## Changed behavior

| Review issue | Implemented behavior |
| --- | --- |
| Stale subscription refill | Both signed-in verification and RTDN honor the ordered persistence result. Ignored purchases do not grant or acknowledge. The grant RPC rechecks token, product, active state and expiry while holding the entitlement lock, closing the accepted-then-replaced race. |
| Ambiguous research debit | A saved UUID claims each research attempt before quota/debit/provider work. Wallet and quota operations deduplicate the same ID. Cancellation tombstones prevent a delayed request from charging after cancellation. Failed reconciliation blocks fresh charges. |
| Attempt denial consumes quota | Attempt admission returns before saving a run, reserving quota, or debiting. |
| Final KILL hidden by research | Stored final decisions take precedence in the workspace, artwork, packet, and filename. The existing owner-stopped behavior remains distinct. |
| Concurrent live slots | Create/unarchive use per-user transaction locks. A database trigger also enforces admission for other writes. Existing over-limit accounts remain editable; no existing venture is deleted or archived by the migration. |
| Legacy direct evidence remains active | Version 1 linkage upgrade runs when state is loaded and persists with the next successful mutation. Source type, level, normalized buyer, exact quote and ordering must support a unique match. Ambiguous items are excluded from active evidence and listed for manual correction. Shared payment origins remain active until all supporting records are voided. |
| Only eight correction controls | The workspace retains its recent summary and links to `/v/{venture_id}/history`, with 20 records per page. Older records and post-decision corrections stay reachable. Ambiguous legacy items can be explicitly voided with a reason. |
| Home N+1 reads | Bulk ID/state/revision reads serve active ideas and a 20-item archive page. Slot status reuses the active states. The loader honors the server's row count rather than silently dropping rows at its page cap. |

Research refund handling also checks the original billing period: a refund from
an expired/replaced period becomes an ordinary wallet credit, never an increase
to the newer period's monthly allocation.

## Evidence and repeatability

`release-generated/verification-20260830.json` is the current machine-generated
record. It includes actual command results, exact pytest counts, dependency
versions, the catalog allocation, and source hashes. Regenerate instead of
copying a test count into release notes:

```powershell
.\.venv\Scripts\python.exe scripts/verify_release.py --output release-generated/verification-20260830.json --baseline ../release-baseline-20260830-1839 --postgres
```

For database tests, set `KILLGATE_TEST_DATABASE_URL` to a disposable **localhost**
PostgreSQL instance and make `pg@8.16.3` available to Node. The SQL checker refuses
non-loopback hosts, creates a unique test database, applies the source migrations,
runs real transactions on separate connections, and drops only that generated
database. No Supabase credentials are used. Local database verification used
PostgreSQL 18.4; the CI job also exercises the SQL on PostgreSQL 17. A configured
CI workflow is not evidence that CI has run.

The database checks cover debit replay, competing debits/cancellations, quota
replay and cancellation, stale/refreshed subscription ordering, cross-period
refunds, concurrent root creation/unarchive, pivot exemptions, direct-write slot
enforcement, abandoned-worker recovery, and function permissions. Application
tests additionally inject lost debit/quota/save responses and verify that a
late result write is fenced before refunding.

An in-app browser check also verified the final KILL presentation and the complete
history link, navigated from a 20-record first page to the oldest record, and
inspected the ambiguous-legacy warning and correction control. At a 390px phone
viewport, the page stayed within the viewport and the wide evidence table scrolled
inside its container. This used synthetic records in a separate temporary local
server, not customer data; details are in `release-generated/browser-qa-20260830.md`.

The pinned Starlette 1.6.0 TestClient emits one HTTPX deprecation warning. It remains
visible and is recorded in the artifact. Follow-up: migrate the test transport to
the officially supported replacement with a separately reviewed lockfile update;
do not suppress the warning or perform a broad dependency upgrade as part of this
financial-correctness patch.

## Production deployment boundary

1. Preserve a database backup and verify the actual deployed source/revision and
   migration history. The historical migration names share date prefixes and must
   not be blindly replayed or renamed on an existing project.
2. Pause new research and billing mutations and drain old workers. The new migration
   removes the callable **unkeyed debit** API; old workers must not handle paid runs
   after this transition. No automatic application-only rollback to the old debit
   implementation is safe.
3. Apply `supabase/migrations/20260830224035_release_correctness.sql` as one transaction.
   Do not rerun it as an ad hoc script: it renames existing function implementations
   and creates indexes/columns once. It does not change balances, remove evidence,
   or archive existing ventures by itself. Index creation can hold table locks;
   choose a maintenance window appropriate to the actual ledger size.
4. Deploy this runtime, run `scripts/check_supabase_schema.py` with server-only
   credentials, and run the existing configuration/readiness checks. The schema
   probe tests the exact new signatures with invalid-user inputs that cannot mutate
   data. Verify permission denial for both anonymous and authenticated customers.
5. On an authorized test account, verify restore/renewal/RTDN, duplicate request and
   provider-failure cases, then run a paid research request and confirm its report,
   wallet balance and quota. Confirm existing beta/test-admin allowlists and all
   rate/token protections remain as intended. Only then reopen traffic.

No production configuration or data was inspected or changed in this update. Passing
local tests, the disposable SQL checks, or `/readyz` does not establish a successful
live Google Play or research flow. No new APK/AAB was built or published.

The new entry points use explicit privilege revocation and fixed search paths;
see the [Supabase database-function security guidance](https://supabase.com/docs/guides/database/functions#security-definer-vs-invoker).

## Interrupted-run recovery

The saved state carries `research_run_id`, `research_run_status`, and
`research_run_paid`. A normal provider failure cancels the debit/quota and marks
the attempt `failed`, permitting a later attempt with a new ID. If cancellation
cannot be confirmed, it remains `reconciliation`; the next request attempts only
that reconciliation. A worker that disappears entirely can leave `pending`.
Pending requests never automatically start another paid run.

For an abandoned run, confirm the account, venture, run reference and worker status.
An operator can invoke the server-only `killgate_reconcile_research_run` RPC with
`p_user_id`, `p_venture_id`, and `p_research_run_id`. It locks the venture, checks
the exact operation, leaves a delivered result charged, otherwise cancels both
reservations and advances the saved revision in one transaction. A late worker
cannot overwrite that fence. A mismatch fails instead of cancelling another run.
No customer-facing endpoint exposes this operator RPC.

Keep credit-ledger run IDs and cancellation tombstones. Do not prune them using
the old 200-entry local-wallet truncation or delete keyed quota events merely
because their counting window expired. Active quota counts ignore released and
out-of-window rows; any future retention policy must retain equivalent durable
deduplication records. Local JSON mode is single-process development storage;
production concurrency guarantees require the Supabase RPCs and migration.
