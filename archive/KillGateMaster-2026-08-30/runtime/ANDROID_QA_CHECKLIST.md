# Killgate Android Internal-Track QA

Run this only after the final package ID, production HTTPS origin, signing setup, and internal-track build exist.

## Build prerequisite

- Generate/update with Bubblewrap v1.25.0 or newer.
- Confirm the generated Android project compiles and targets API 36.
- Keep Bubblewrap `enableNotifications` set to `true`; Bubblewrap v1.25.0 requires it when Play Billing is enabled.
- Before upload, inspect the generated Gradle file and confirm the Play Billing feature resolves `com.google.androidbrowserhelper:billing:1.2.0` or a newer PBL8+ compatible artifact. Do not upload a PBL7 build: the normal Play deadline for PBL7 new apps/updates is August 31, 2026.

## Install source

For billing and production Digital Asset Links validation, install the build **from Google Play's internal testing track** with a license-test account. A locally sideloaded build is useful for basic TWA/UI smoke tests, but it can be signed by the upload key rather than the Play App Signing key and therefore does not prove the production asset link.

## Device / emulator smoke test

After installing the internal-track build, `python scripts/android_internal_smoke.py --package-id <PACKAGE_ID>` captures minimized, app-PID-scoped crash/log evidence plus the resolved activity and package path. Use `--serial` when more than one adb target is connected. Screenshot/UI-tree capture can contain private account data and therefore requires a dedicated test account/device plus the explicit `--capture-private-ui` flag. The tool selects `adb` only from the configured Android SDK (or explicit `--adb` path), redacts common email/token patterns, and writes under the ignored `artifacts/` directory by default.

1. Confirm the device/emulator is visible with `adb devices`.
2. Resolve the launch activity with `adb shell cmd package resolve-activity --brief <PACKAGE_ID>`.
3. Launch Killgate and confirm it opens fullscreen as a TWA, not a Chrome Custom Tab with browser chrome.
4. Dump the UI tree and verify the landing page, new-idea form, idea pipeline, account link, and install-source behavior are present.
5. Capture screenshots of the landing page, account page, one venture page, and a validation decision page.
6. Check `adb logcat -b crash` and app-process logs for crashes, network errors, CSP failures, auth loops, or billing exceptions.

## Auth / account

- Create a test account and sign in.
- Kill/relaunch the app and confirm the authenticated session survives appropriately.
- Sign out and confirm private venture URLs redirect to login.
- Export account data and confirm the downloaded JSON contains only that account's records.
- Delete the test account and confirm the session is cleared and the account can no longer sign in.

## Validation integrity

- Create a new idea and confirm a locked system-generated Validation Contract is produced before evidence can justify GO.
- Run public research and confirm raw search snippets cannot PASS; each counted source must be present in the hosted web-search source ledger.
- Add two records for the same buyer and confirm unique-buyer counting does not inflate.
- Mark a payment without amount/reference and confirm it does not count as Level-5 evidence.
- Confirm manual/user action cannot force GO while deterministic gates fail.
- Confirm a valid paid-pilot contradiction does not get irrationally killed by weak interview scoring.

## Google Play billing

- Open Account inside the Play-installed TWA and confirm the Digital Goods API path is available.
- Confirm the account screen shows the localized subscription price returned by the Play Digital Goods API.
- Purchase the configured subscription with a license tester.
- Confirm backend entitlement becomes active and acknowledged.
- Close the app; use Play test controls / subscription lifecycle testing to trigger renewal, cancellation, grace period, account hold, revocation, and expiration where available.
- Confirm RTDN changes backend entitlement while the app is closed.
- Reopen/reinstall and confirm `listPurchases()` plus backend verification restores an active entitlement.
- Open subscription management from Account and confirm the link targets the exact package and subscription product in Google Play.
- Confirm the delete-account page warns that deleting app data does not cancel the Play subscription and provides a cancellation link.
- Confirm a canceled-but-not-expired subscription remains entitled only until the Play-reported expiry.
- Confirm on-hold, revoked, and expired states cannot run billing-gated research once `BILLING_ENFORCED=1`.
- Confirm the API safety ceiling is 30 successful runs per rolling 30 days and 8/hour for the test account, including across two backend workers if your deployment can exercise concurrency. This is not a purchased allowance. During internal beta, confirm the separate 9-run/14-day allowlist window.

## Digital Asset Links

- Confirm `https://<PRODUCTION_HOST>/.well-known/assetlinks.json` is publicly reachable without redirects that break verification.
- Confirm its package ID exactly matches the final app ID.
- With Play App Signing enabled, confirm the fingerprint is the **App signing key certificate** SHA-256 from Play Console.
- Verify the Play-installed build launches as a trusted fullscreen experience.

## Release stop conditions

Do not promote beyond internal testing if any of these occur:

- TWA opens with browser chrome because Digital Asset Links does not verify.
- Billing entitlement can be granted from client-supplied status without Play verification.
- RTDN requests can update entitlement without valid Pub/Sub OIDC authentication.
- Cross-account venture or entitlement data is visible.
- Account deletion does not remove owned data.
- Any path bypasses the deterministic Validation Contract / GO gate.
- Any real secret is present in the AAB, PWA JavaScript, source package, or logs.
