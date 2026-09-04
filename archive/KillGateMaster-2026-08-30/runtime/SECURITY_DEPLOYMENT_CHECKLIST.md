# Killgate Production / Google Play Security Checklist

Killgate is intentionally a single-person account product, not a collaborative SaaS.

## Implemented in runtime/database

- [x] Supabase Auth session mode with HttpOnly, Secure (production), SameSite=Strict cookies.
- [x] Per-account venture isolation with Postgres RLS (`auth.uid() = user_id`).
- [x] Anonymous venture/entitlement table access revoked.
- [x] User JWT used for normal reads/writes; privileged Supabase key is server-only.
- [x] Account export route.
- [x] In-app and web account-deletion flow.
- [x] Authenticated account-deletion Edge Function deployed; owned rows cascade on user deletion.
- [x] Same-origin Origin check for mutating browser requests, including pre-session login/signup; RTDN/share-target exceptions are explicit.
- [x] Distributed server-side rate limits on idea creation, research, buyer evidence, and billing verification.
- [x] Atomic research quota: 8/hour and 30 per rolling 30 days by default.
- [x] Restrictive CSP, frame, content-type, referrer, and permissions headers.
- [x] Google Play purchase token verified on backend before entitlement.
- [x] Google Play product/state/expiry checked; new valid subscriptions acknowledged server-side.
- [x] Purchase token stored only as SHA-256 hash.
- [x] Authenticated Google Cloud Pub/Sub RTDN endpoint validates OIDC audience/service-account identity and Android package before processing.
- [x] RTDN lifecycle changes are re-verified against Google Play; message IDs are deduplicated server-side.
- [x] RTDN ledger is RLS-protected, unavailable to customer roles, and stores no raw purchase token.
- [x] Subscription entitlement table can be written only by backend/admin credentials.
- [x] Optional Sentry integration configured with default PII collection disabled.
- [x] Supabase security advisor clean after schema migrations, including distributed limiter and research quota.

## Required before production release

- [ ] Deploy the included non-root container behind HTTPS on the final Killgate domain (recommended v1 path: Cloud Run; see `CLOUD_RUN_DEPLOYMENT.md`).
- [ ] Set `AUTH_MODE=supabase`, `STATE_BACKEND=supabase`, `COOKIE_SECURE=1`.
- [ ] Store OpenAI/search/Supabase-secret/Google service-account credentials only in production secret storage.
- [ ] Configure backup/restore and test a restore.
- [ ] Set the final monitored privacy/support email in `/privacy`.
- [ ] Publish the privacy policy and `/delete-account` at stable public URLs and enter them in Play Console.
- [ ] Configure Google Play app package, subscription product/base plan, tester track, and service-account Developer API permissions.
- [ ] Test purchase, renewal, cancellation, grace period, on-hold, expiration, restore, and acknowledgement behavior using Play license testers.
- [ ] Wire Play Console + Google Cloud Pub/Sub to the implemented RTDN endpoint and pass the full lifecycle test matrix in `GOOGLE_PLAY_RTDN_SETUP.md`.
- [ ] Set `BILLING_ENFORCED=1` only after the internal-test billing flow verifies correctly end-to-end.
- [x] Production limiter is Supabase-backed and cross-worker safe; local mode retains in-process limits.
- [ ] Configure Sentry (or equivalent), alerting, health checks, and incident response.
- [ ] Run dependency/image vulnerability scan on the exact resolved production environment and final image.
- [x] Source-level release-candidate security review completed; see `SECURITY_REVIEW_RELEASE_CANDIDATE.md`.
- [ ] Complete Play Data Safety form from the final deployed behavior, not from assumptions.

GO-gate integrity remains independent of deployment security: auth, billing, hosting, or human approval must never bypass the locked Validation Contract.
