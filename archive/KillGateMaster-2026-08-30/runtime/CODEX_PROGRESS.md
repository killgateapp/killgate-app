# Killgate release progress

Updated: 2026-08-24 (America/New_York)

## Target dates

- Tester-ready target: Wednesday, 2026-08-26.
- Public Play target requested: Wednesday, 2026-09-09.
- Store review, developer-account verification, and production identity timing are controlled by Google and cannot be guaranteed by source changes alone.

## Source and recovery baseline

- Authoritative source: `C:\Users\patri\OneDrive\Desktop\Killgate`.
- Preserved transferred baseline: Git commit `f0f5b12` on `main`.
- Local secrets, service accounts, signing keys, Android binaries, QA artifacts, and `.env.local` are ignored/excluded.
- `.env.local` exists with safe development defaults and a blank `OPENAI_API_KEY`; real hosting secrets must remain in the production secret store.

## Completed source/release work

- Corrected evidence-correction handling so original evidence and decisions remain auditable while voided support no longer counts toward gates; a prior GO is withdrawn when corrected evidence no longer satisfies the locked contract.
- Enforced unique-buyer/payment evidence invariants and preserved deterministic GO gating.
- Changed research so raw search snippets are discovery metadata only and can never PASS. Production requires OpenAI hosted web search, and only URLs in its returned source ledger can count.
- Fixed Play purchase ordering to verify, durably persist entitlement, then acknowledge.
- Added bounded entitlement freshness (`ENTITLEMENT_MAX_AGE_HOURS=24`) so missed RTDN cannot leave stale paid access until the old monthly expiry.
- Made production billing fail closed and made `APP_ENV=production` plus `BILLING_ENFORCED=1` mandatory for release readiness.
- Added HMAC-keyed distributed login/signup limits without storing raw email/IP identifiers.
- Offloaded blocking Supabase session resolution from the ASGI event loop and changed request-size enforcement to stop while streaming rather than after unbounded buffering.
- Added account subscription management/cancellation and restore surfaces; deletion warns that deleting app data does not cancel a Play subscription.
- Added the server-only Supabase pre-auth limiter migration and extended the live schema/anonymous-denial probe.
- Updated Bubblewrap manifest compatibility (`enableNotifications=true`) and proved Bubblewrap v1.25.0 generates compile/target SDK 36 with `com.google.androidbrowserhelper:billing:1.2.0` (PBL 8.3.0 path).
- Pinned the container base by digest, runtime/dev dependencies by version plus SHA-256 hashes, and GitHub Actions by commit SHA.
- Hardened Android tools to resolve beneath explicit JDK/SDK roots, strictly validate adb package/components, minimize/redact app-PID logs, and require opt-in for private screenshot/UI capture.
- Completed Codex Security scan `7cf55aab-bcad-490f-819a-31cc3d50dbe9`: complete coverage, zero open reportable findings after remediation.

## Verification ledger

- `pytest -q`: **159 passed** (one third-party Starlette TestClient deprecation warning only).
- Ruff functional/bugbear checks: clean.
- Bandit medium/high scan: clean.
- `pip-audit` runtime and CI hashed locks: no known vulnerabilities.
- Python 3.12 dry-run resolution for both hashed locks: successful.
- Python compileall, browser JavaScript syntax, `pip check`, and `git diff --check`: clean.
- Installed OpenAI SDK exposes every Responses parameter Killgate uses, including hosted web search, required tool choice, source inclusion, Structured Outputs, and reasoning controls.
- Docker build not executed locally because Docker is not installed; the pinned production build remains a required CI gate.

## Installable Android preview

- Artifact: `artifacts/Killgate-current-UI-PREVIEW.apk`.
- SHA-256: `08A416AE3B7E855382E480A133DFC4701F6E7B775207B0C14EBC3B3134B3CBEC`.
- Package: `com.killgate.preview`; min SDK 24; target SDK 36.
- Signature: APK Signature Scheme v2 and v3 verified.
- Installed and launched successfully on Android 16/API 36 emulator.
- Landing and Validation Contract flows rendered correctly with safe system-bar insets; crash buffer remained empty.
- This APK is deliberately labeled an offline UI preview. Backend, AI, authentication, billing, and production Digital Asset Links require the final Play TWA/AAB and are not represented as connected in this APK.

## External release inputs still required

These values are intentionally not invented or committed:

- Production HTTPS origin/domain and deployed Cloud Run service.
- Final Android package ID. It becomes difficult/permanent to change after first Play upload.
- Play Console developer/app access and required Data safety/account-deletion declarations.
- Upload keystore, alias/passwords, and Play App Signing SHA-256 fingerprint.
- Play subscription product ID, single monthly base plan, localized price, and license-test accounts.
- Google Play Developer API service account and authenticated RTDN Pub/Sub audience/service account.
- Production Supabase project, applied migrations/Edge Function, and live schema/security-advisor verification.
- OpenAI project API key in production secret storage; creation is parked until the owner is on the desktop approval/account screen.
- Monitored privacy and support email addresses.
- Optional production Sentry configuration.

## Promotion stop conditions

- Do not upload the first AAB until the final package ID is explicitly confirmed.
- Do not enable public paid release until the Play-installed internal-track TWA proves Digital Asset Links, Digital Goods purchase/restore, persistence-before-acknowledgement, RTDN lifecycle transitions, cancellation links, and account deletion behavior.
- Do not claim Play release readiness until `python scripts/check_production_readiness.py --release` and `python scripts/check_supabase_schema.py` both exit successfully in the production environment.
