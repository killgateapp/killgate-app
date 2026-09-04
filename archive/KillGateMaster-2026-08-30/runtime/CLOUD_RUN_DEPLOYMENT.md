# Killgate Production Hosting — Cloud Run Release Path

Cloud Run is the recommended v1 host for the FastAPI/PWA origin because it gives Killgate one HTTPS backend/PWA origin, scales to zero/low traffic economically, and keeps all privileged credentials outside the Android/TWA package.

## Release topology

`Google Play TWA -> https://FINAL_KILLGATE_ORIGIN -> Cloud Run / FastAPI -> Supabase + OpenAI + Google Play Developer API`

Google Cloud Pub/Sub sends authenticated Play RTDN pushes to:

`https://FINAL_KILLGATE_ORIGIN/billing/google-play/rtdn`

## Container

The repository includes a non-root, digest-pinned `Dockerfile` with hashed Python dependencies. It defaults to `APP_ENV=production`, runs the runtime-readiness preflight before Uvicorn, serves `app.web:app` on `$PORT`, and health-checks `/readyz`.

Before deployment:

1. Run the full test suite.
2. Build the container.
3. To run the container in local development, explicitly override `APP_ENV=development`, provide the local-mode values, and verify `/healthz`.
4. Run a vulnerability scan against the resolved Python packages and final image.
5. Never bake `.env`, service-account JSON, OpenAI keys, Supabase secret keys, keystores, or signing material into the image.

## Production environment

Set non-secret configuration as Cloud Run environment variables and credentials through secret storage. At minimum production expects:

- `APP_ENV=production`
- `AUTH_MODE=supabase`
- `STATE_BACKEND=supabase`
- `WALLET_BACKEND=supabase`
- `COOKIE_SECURE=1`
- `PUBLIC_APP_ORIGIN=https://FINAL_KILLGATE_ORIGIN`
- `PRIVACY_CONTACT_EMAIL=...`
- `SUPPORT_EMAIL=...`
- `SUPABASE_URL=...`
- `SUPABASE_PUBLISHABLE_KEY=...`
- `MODEL_NAME=gpt-5.6-luna`
- `OPENAI_REQUIRED=1`
- `OPENAI_MAX_OUTPUT_TOKENS=2400`
- `RESEARCH_RUNS_PER_HOUR=8`
- `RESEARCH_SAFETY_CAP_30D=30` as an API safety ceiling, separate from paid credits
- `ENTITLEMENT_MAX_AGE_HOURS=24`
- `KILLGATE_BETA_ENABLED=0` for release; internal testing may explicitly enable it with a user-ID allowlist
- `KILLGATE_BETA_USER_IDS`, `KILLGATE_BETA_START_AT`, `KILLGATE_BETA_DURATION_DAYS=14`, and `KILLGATE_BETA_MAX_RUNS=9` when beta access is enabled
- `KILLGATE_TEST_ADMIN_ENABLED=0` for release; internal admin testing may explicitly enable it with a user-ID allowlist
- `KILLGATE_TEST_ADMIN_USER_IDS` must contain only the intended Supabase Auth user IDs when admin testing is enabled
- `GOOGLE_PLAY_PACKAGE_NAME=...`
- `PLAY_APP_SIGNING_SHA256=...` (Play Console **App signing key certificate** SHA-256)
- `GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID=killgate_founder_pro`
- `GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID=killgate_venture_pass`
- `GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID=killgate_evidence_run`
- `GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID=killgate_founder_topup`
- `GOOGLE_PLAY_RTDN_AUDIENCE=https://FINAL_KILLGATE_ORIGIN/billing/google-play/rtdn`
- `GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL=...`
- `BILLING_ENFORCED=0` until internal-track lifecycle QA is complete

Server-only secrets:

- `OPENAI_API_KEY`
- `SUPABASE_SECRET_KEY`
- Google Play Android Publisher service-account credential (`GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` or mounted file)
- `SENTRY_DSN` if used

Run `python scripts/check_production_readiness.py` in the deployed revision. It must report runtime-ready before traffic is moved to the revision. Run it with `--release` before promotion; release readiness additionally requires `APP_ENV=production`, `BILLING_ENFORCED=1`, both beta/admin testing switches disabled, and all Play/domain/contact values.

## Domain

Map the final custom domain to the production Cloud Run service and enforce HTTPS. `PUBLIC_APP_ORIGIN`, the TWA manifest, the PWA origin, Digital Asset Links location, OAuth/RTDN audience, privacy URL, deletion URL, and Play listing must all agree on that origin.

Killgate now serves Digital Asset Links dynamically at exactly:

`https://FINAL_KILLGATE_ORIGIN/.well-known/assetlinks.json`

The route is generated from `GOOGLE_PLAY_PACKAGE_NAME` and `PLAY_APP_SIGNING_SHA256`, and returns HTTP 503 until both values are valid. The `assetlinks.json` emitted by `scripts/render_play_release.py` is a parity/release-check artifact; the deployed route is the authoritative public copy. Verify the live URL after deployment and again after Play App Signing is enabled. Do **not** use the upload-key fingerprint for the Play-installed app binding.

## Promotion sequence

1. Deploy backend/PWA with `BILLING_ENFORCED=0`.
2. Verify `/healthz`, `/readyz`, Supabase schema probe, privacy/delete-account URLs, account auth, and live public research.
3. Render the final TWA files.
4. Build with Bubblewrap v1.25.0+ and verify the generated billing dependency is PBL8+.
5. Upload the AAB to Play internal testing.
6. Run `ANDROID_QA_CHECKLIST.md`, including purchase/restore/RTDN lifecycle.
7. Enable `BILLING_ENFORCED=1` in a new Cloud Run revision only after billing QA passes.
8. Re-run readiness and smoke tests, then promote the Play release beyond internal testing.
