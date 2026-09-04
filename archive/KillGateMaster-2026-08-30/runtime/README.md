# Killgate Runtime v1.2.0 — Single-User Play Store Architecture

The [August 30 release correctness update](RELEASE_HARDENING_20260830.md) covers
the eight reviewed defects, database deployment order, and interrupted-run recovery.
Use `python scripts/verify_release.py` for dated local evidence; add `--postgres`
with a disposable localhost PostgreSQL instance to exercise the actual SQL and races.
Historical handoff totals are not the current verification record.

Killgate is a **single-person product**: every customer gets one private validation workspace. There are no teams, seats, organizations, invitations, or shared ventures. A production backend may serve many customers, but Row Level Security isolates every account.

## What is implemented

- Plain-English idea intake.
- System-generated **locked Validation Contract** created before research.
- Live public research with DIRECT / INDIRECT / IRRELEVANT discovery classification and hosted source-content verification before PASS.
- Claim-to-source research gates and disconfirming-evidence search.
- Structured qualified-buyer evidence capture.
- Unique-buyer deduplication and payment-reference requirements.
- Deterministic GO / CONTINUE_VALIDATION / PIVOT / KILL gate; AI cannot override it.
- Evidence and decision audit trail.
- PWA install/share/file/protocol integration.
- **Supabase Auth** account mode with email/password sessions and refresh.
- **Supabase Postgres cloud persistence with RLS** (`auth.uid() = user_id`).
- Data export and in-app/web account-deletion path.
- Deployed authenticated `delete-killgate-account` Edge Function; deleting the Auth user cascades owned Killgate records.
- In-process abuse limits for local development and atomic server-only Supabase rate limiting in production, including login/signup protection, a 30-run rolling API safety ceiling, and an 8/hour default burst cap. Paid usage is controlled separately by the entitlement wallet; allowlisted beta testers receive nine free runs during a fourteen-day beta window.
- Structured logs plus optional Sentry SDK integration.
- OpenAI **Responses API + hosted web search + strict Structured Outputs** for production research. Raw search-provider snippets can only discover leads; a URL must appear in OpenAI's returned web-search source ledger before it can count toward PASS. The model returns source numbers and Killgate attaches only server-known URLs.
- **Google Play Billing TWA client flow** using Digital Goods + Payment Request APIs.
- **Server-side Google Play billing verification** for Venture Pass, Extra Evidence Run, Founder Pro, and Pro top-ups; consumables are granted durably before server-side Play consumption, while subscriptions use expiry/state checks, token hashing, acknowledgement, and authenticated RTDN lifecycle sync.
- **Durable Supabase research wallet** with atomic grants, family binding, current-entitlement-checked Pro refills, idempotent per-run debits, and cancellation receipts across Cloud Run workers.
- Saved research-run claims prevent duplicate provider work; ambiguous failures remain blocked until delivery or refund is confirmed. Database reconciliation can recover an abandoned worker without refunding a delivered result.
- Transactional admission enforces three live root locks, including concurrent creation and unarchive. Pivot children keep their existing slot behavior.
- Complete, paginated evidence corrections and archive history; legacy evidence is linked only when unambiguous and otherwise marked for review.
- `BILLING_ENFORCED=1` is mandatory for Play release readiness. Production paid research requires an actual wallet entitlement; a subscription is optional.
- Non-root Docker/Cloud Run production deployment path with runtime/release readiness checks.
- OpenAI model/token usage instrumentation for real post-launch unit-economics measurement.

## Product boundary

Single-user means **one human per account**, not “one installation with local-only files.” Production mode uses accounts so a customer's data can survive a phone replacement and remain private across devices.

The Android package must never contain OpenAI/search credentials, a Supabase secret/service-role key, or Google Play service-account credentials. Those stay on the server.

## Modes

### Local development

```env
AUTH_MODE=local
STATE_BACKEND=local
BILLING_ENFORCED=0
```

State is JSON on disk. This keeps development and automated tests simple.

### Production

```env
AUTH_MODE=supabase
STATE_BACKEND=supabase
WALLET_BACKEND=supabase
COOKIE_SECURE=1
BILLING_ENFORCED=1
```

Production additionally requires the Supabase URL/publishable key, a server-only Supabase secret key, Google Play package/SKU/service-account credentials, HTTPS hosting, and Play Console configuration.

Internal beta access is not a public free tier. It is enabled only for server-allowlisted Supabase user IDs, grants up to 9 free live research runs during one 14-day window, and is disabled before a Play release. The test-admin switch is a separate owner-only wallet bypass and is also release-blocked.

For a home smoke test with `killgateapp@gmail.com`, deploy with `AUTH_MODE=supabase`, sign up from `/signup`, confirm the Supabase email, then copy that Auth user UUID into `KILLGATE_BETA_USER_IDS` or `KILLGATE_TEST_ADMIN_USER_IDS` if the account should run a report without buying a Play entitlement. Do not store a password, refresh token, Supabase secret key, or OpenAI key in the repo or Android package. Live reports also require `OPENAI_REQUIRED=1` and a server-side `OPENAI_API_KEY` secret.

Public signup traffic needs production email delivery. Supabase's built-in Auth mailer is suitable only for tiny demos; configure custom SMTP, SPF/DKIM/DMARC, redirect URLs, and bot protection before launch, then tune the `KILLGATE_*_LIMIT_*` pre-auth caps to match the real mailer capacity.

Before deployment, run `python scripts/check_production_readiness.py --release` and `python scripts/check_supabase_schema.py` from the production backend environment. The first validates required runtime/release configuration without printing secret values; the second proves the server-only RTDN/rate-limit database objects are actually reachable and anonymous access cannot query those ledgers. `/healthz` exposes only basic service health; `/readyz` exposes only `ready`/`not_ready` and returns HTTP 503 when required runtime configuration is incomplete. Privacy and support contacts come from `PRIVACY_CONTACT_EMAIL` and `SUPPORT_EMAIL`, not hard-coded source.

The default research model is `gpt-5.6-luna` for a low-cost, high-volume workload. Override `MODEL_NAME` only with a model that supports the Responses API, hosted web search, and Structured Outputs. Killgate sends `store=false`, requires the hosted web-search tool, verifies its source ledger, and still applies its deterministic evidence evaluator after the model returns.

## Supabase

Version-controlled database setup lives under `supabase/migrations/`. The schema defines:

- `public.ventures`: one JSON `SystemState` per venture, composite key `(user_id, id)`.
- `public.subscription_entitlements`: server-written, user-readable entitlement state.
- `public.play_rtdn_events`: server-only RTDN message-id ledger for idempotency; stores only purchase-token hashes.
- `public.request_rate_events` plus `killgate_rate_limit_allow(...)`: server-only distributed rate-limit state/RPC for production workers.
- `public.pre_auth_rate_events` plus `killgate_pre_auth_rate_limit_allow(...)`: HMAC-keyed server-only login/signup abuse limits; raw email/IP identifiers are not stored.
- `killgate_research_quota_reserve_window(...)` / `killgate_research_quota_release(...)`: atomic cross-worker hourly + configurable-window research reservation and rollback.
- `public.killgate_wallets`, `public.killgate_venture_passes`, `public.killgate_credit_ledger`: durable paid-research entitlement state.
- `killgate_wallet_snapshot/grant/bind_pass/debit(...)`: server-only atomic wallet RPCs used by production.

All exposed tables have RLS enabled and anonymous access is revoked. The account/entitlement, RTDN, distributed-rate-limit, and research-quota migrations are applied to the connected production project and live-verified with a clean Supabase security advisor.

Account deletion code lives in `supabase/functions/delete-killgate-account/` and is deployed with JWT verification enabled.

## Google Play Billing

The web/TWA client never decides whether a purchase grants research.

1. The TWA requests one of Killgate's configured Play SKUs.
2. Checkout returns a purchase token.
3. The token plus product ID (and idea-family ID when required) is sent to `/billing/google-play/verify`.
4. The server verifies the purchase with the Google Play Developer API.
5. One-time consumables are atomically granted to Killgate's durable wallet and only then consumed through Play so the SKU can be repurchased.
6. Founder Pro is persisted as a server-verified subscription entitlement and acknowledged when required.
7. The 9 Founder Pro passes are refilled once per verified billing period, keyed to the subscription expiry; repeated verification of the same period cannot refill twice.
8. RTDN keeps subscription lifecycle/renewal state synchronized while the app is closed.
9. Research execution debits one wallet entitlement atomically unless the server has explicitly granted internal beta or test-admin access. Founder Pro does not bypass the wallet and there is no unlimited public access path.

The launch catalog is documented in `PLAY_CONSOLE_CATALOG.md`.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
uvicorn app.web:app --reload
```

Then open `http://127.0.0.1:8000`.

Local settings and the owner-approved API-key destination are `.env.local`. The file is loaded automatically, ignored by Git/Docker, and never replaces hosting-platform secrets in production.

## Tests

```bash
pip install --require-hashes -r requirements-dev.lock
pytest -q
```

The CLI remains a local developer/operator utility. Production customers use the web/TWA application.

## Production hosting

A non-root `Dockerfile` and `.dockerignore` are included. The recommended v1 deployment path is Cloud Run behind the final HTTPS origin; see `CLOUD_RUN_DEPLOYMENT.md`. Privileged OpenAI, Supabase, and Google Play credentials stay in backend secret storage and are never bundled into the PWA/TWA.

## Pricing

Default offer: **$19.99 Venture Pass**. Also $7.99 same-idea Extra Evidence Run, optional $59.99/month Founder Pro (9 passes), and active-Pro-only $14.99 3-run top-up. See `PRICING_AND_UNIT_ECONOMICS.md`.

## Android packaging

Killgate remains a PWA packaged as a **Trusted Web Activity**, avoiding an unnecessary native rewrite. The final Android App Bundle and live RTDN wiring still require values that cannot be safely invented in source: the production HTTPS origin, final Android package ID, upload signing key, Play App Signing certificate fingerprint, Play Console subscription/base plan, and Play service-account permissions. See `PLAY_STORE_RELEASE_CHECKLIST.md`. Once the owner values are known, `scripts/render_play_release.py` renders a current Bubblewrap-ready TWA manifest plus an `assetlinks.json` parity artifact without hand-editing placeholders; the production origin serves `/.well-known/assetlinks.json` dynamically from the final package/signing values; use Bubblewrap CLI 1.25.0+ and `ANDROID_QA_CHECKLIST.md` for internal-track QA.
