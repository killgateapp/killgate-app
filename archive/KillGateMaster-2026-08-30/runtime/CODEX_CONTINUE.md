# Killgate — Codex continuation handoff

> Historical August 24 handoff. Use [the August 30 release update](RELEASE_HARDENING_20260830.md)
> and the generated verification artifact for current behavior and test results.
> Earlier totals and deployment instructions below describe their original snapshot.

Date: 2026-08-24
Snapshot: hardening branch transferred from ChatGPT
Verification at transfer: **146/146 pytest tests pass**

## Mission
Finish Killgate v1 as a production-quality Android/Google Play release. Do not rush it. The release standard is: no known correctness bugs in supported v1 behavior; updates after launch should primarily improve presentation/features rather than repair avoidable core defects.

## Product invariants — DO NOT weaken these
- Killgate v1 is a single-user/private-workspace Android product distributed through Google Play.
- Validation Contract is system-generated and locked; founders do not supply their own kill criteria.
- Public research is relevance-gated and cannot masquerade as buyer evidence.
- Buyer interviews are structured and unique-buyer deduplicated.
- Level-5 payment evidence requires amount + reference.
- GO / CONTINUE_VALIDATION / PIVOT / KILL is owned by deterministic gate logic. AI/manual input cannot force GO.
- Audit trail is retained.
- Paid-pilot contradiction rule remains authoritative.
- Billing product configured on the server is authoritative; client product IDs cannot select a different subscription.

## Current hardening work in this snapshot
The snapshot includes fixes/tests for:
- optimistic venture revision/concurrency protection
- research reservation/release behavior and stale-write conflict handling
- research/live-search malformed response handling and conservative fallbacks
- stricter auth/session failure behavior and cookie cleanup
- private/dynamic response cache controls
- Google Play token ownership/history and ordered entitlement persistence logic
- RTDN idempotency and malformed-storage-response fail-closed behavior
- Supabase runtime-contract release probe updates
- longer new venture identifiers
- request body/origin hardening
- local preview APK builder + structural APK tests

## Important incomplete item
Evidence correction/soft-void support has begun at the model/gate layer. The goal is:
- never erase evidence history;
- allow a mistaken evidence entry to be voided with timestamp + required correction reason;
- retain original values in audit history;
- exclude voided evidence from deterministic gate math;
- provide a safe authenticated UI/API correction action with regression tests.

Inspect the current implementation before extending it. Do not assume the UI/API portion is complete merely because the test suite passes.

## Live Supabase context known at handoff
Project used previously: `qpvigwpkykljnifrgyxi`.
Previously live: auth/account tables/RLS, ventures, subscription entitlements, account deletion Edge Function, RTDN ledger, distributed rate limit, research quota.
The NEW hardening migrations in `supabase/migrations/20260824_*` were NOT all confirmed applied/probed live at this handoff. Treat them as pending until you verify the actual project schema.

Never print or commit Supabase service-role/secret keys.

## OpenAI
- Responses API with strict Structured Outputs.
- Current source default model: inspect source; previously configured around GPT-5.6 Luna.
- `store=False` and conservative fallback behavior are intentional.
- Production key must be supplied via secret storage/environment only.
- An OpenAI Platform setup flow for a key named `Killgate Production` was opened from ChatGPT, but deployment/completion was NOT confirmed.

Never print or commit the OpenAI key.

## Android / Google Play
The final Play build is intended to be a Trusted Web Activity (TWA), not the local preview shell APK.
- Use modern Bubblewrap/toolchain and verify generated Android/Gradle dependencies against current Play requirements.
- Build the actual AAB locally.
- Install/run on emulator AND at least one real Android device via adb.
- Exercise back navigation, keyboard/form behavior, rotation/orientation expectations, process recreation, offline/server-failure states, auth, account deletion, research, billing restore/purchase lifecycle, RTDN lifecycle, and screenshots/store-listing appearance.
- Run `scripts/android_internal_smoke.py` where applicable.
- Do not enable production billing enforcement until internal-track lifecycle QA is complete.

Owner-controlled production values are still expected to include final HTTPS origin/domain, package ID, upload keystore/alias, Play App Signing SHA-256, Play subscription product/base-plan ID, Google Publisher service-account access, privacy/support email, RTDN Pub/Sub wiring, and production secrets.

Never commit keystores, signing passwords, Google service-account JSON, `.env`, OpenAI keys, or Supabase secrets.

## First actions for Codex
1. Treat this snapshot as the authoritative continuation source.
2. Create a normal Git history locally if needed; do not overwrite remote `main` until verification.
3. Inspect `git status`, repo structure, README, release/security docs, migrations, and test suite.
4. Create/activate a Python environment and install requirements.
5. Reproduce `pytest -q` and confirm 146 tests (or explain any environment-dependent difference).
6. Run compile/syntax/static checks and dependency/security scans available locally.
7. Finish evidence soft-void/correction end-to-end with regression tests.
8. Perform a second correctness review of deterministic gate math and all mutation/concurrency boundaries.
9. Apply/probe pending Supabase migrations only after reviewing them and confirming the target project.
10. Set up Android SDK/Java/Bubblewrap/Gradle as needed, build the real Android package, and perform emulator/device QA.
11. Fix validated defects, and add a regression test for every defect where practical.
12. Keep a running `CODEX_PROGRESS.md` with findings, fixes, exact commands, test counts, and remaining release blockers so the user can supervise from their phone.

## Release discipline
Do not declare "Play-ready" merely because unit tests pass. Play-ready means: production config resolved, backend deployed/probed, Supabase schema verified, Android AAB built with current requirements, Digital Asset Links correct for Play signing cert, install/device QA passed, billing/RTDN lifecycle tested on internal track, privacy/deletion/Data Safety/store listing reconciled, and no known Critical/High security/correctness defect remains.
