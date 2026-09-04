# Killgate Google Play Release Checklist

## Values still needed from the owner / Play Console

- Final HTTPS origin, e.g. `https://...`.
- Final Android application/package ID.
- Bubblewrap/upload signing keystore used to sign the AAB you upload to Play.
- Play App Signing SHA-256 certificate fingerprint from Play Console (this is the production `assetlinks.json` fingerprint when Play App Signing is enabled).
- Google Play product IDs for Venture Pass, Extra Evidence Run, Founder Pro, and Founder Pro top-up.
- Google Play Console service account with Android Publisher API access.
- Current launch catalog: **$19.99 Venture Pass / $7.99 Extra Evidence Run / $59.99 monthly Founder Pro with 9 passes / $14.99 active-Pro 3-run top-up; no free live-research trial**. See `PRICING_AND_UNIT_ECONOMICS.md`.
- Final privacy/support email.
- Google Cloud Pub/Sub project + authenticated push service-account choice for RTDN.

## TWA packaging

Use **Bubblewrap v1.25.0 or newer** against the production PWA manifest. v1.25.0's Play Billing feature resolves `com.google.androidbrowserhelper:billing:1.2.0`, which uses Play Billing Library 8; this matters because Play Billing Library 7 reaches its normal new-app/update deadline on August 31, 2026. Enable Play Billing in `twa-manifest.json`:

```json
{
  "features": {"playBilling": {"enabled": true}},
  "alphaDependencies": {"enabled": true}
}
```

Keep `enableNotifications` set to `true` in the Bubblewrap manifest. Bubblewrap v1.25.0 requires notifications to be enabled when Play Billing is enabled; this does not authorize marketing notifications, which Killgate does not send.

Once origin/package/Play App Signing fingerprint are known, render the release files with `scripts/render_play_release.py`. Generate/update the Android project with Bubblewrap v1.25.0+, then inspect the generated Gradle dependency before building: it must use `com.google.androidbrowserhelper:billing:1.2.0` (or a newer billing artifact that is on Play Billing Library 8+), not the older 1.1.0/PBL7 path. Then build and publish the generated AAB to an internal testing track first. Follow `ANDROID_QA_CHECKLIST.md` for device/emulator and lifecycle verification.

The production origin must host a valid `/.well-known/assetlinks.json` binding the web origin to the exact Android package and the certificate that signs the app **installed on the device**. With Play App Signing, use the **App signing key certificate SHA-256** shown in Play Console, not the local upload-key fingerprint. You may add the upload-key fingerprint as an additional fingerprint only when you also want locally sideloaded builds to verify as a TWA. Killgate serves this path dynamically from `GOOGLE_PLAY_PACKAGE_NAME` + `PLAY_APP_SIGNING_SHA256`; the renderer output is a parity/check artifact. Confirm the **live** route returns the same binding before internal-track QA.

## Play Billing launch test

1. Create the four current Play products exactly as listed in `PLAY_CONSOLE_CATALOG.md`: `killgate_venture_pass`, `killgate_evidence_run`, `killgate_founder_pro`, `killgate_founder_topup`.
2. Apply all Supabase migrations through `20260828_killgate_founder_pro_wallet_rpc.sql`; run `python scripts/check_supabase_schema.py`.
3. Give the backend service account the required Play Developer API access and configure the four product IDs.
4. Keep `BILLING_ENFORCED=0` during initial wiring.
5. Install the internal-test build through Google Play using a license-test account.
6. Buy a Venture Pass from a specific idea brief. Verify: Play purchase → server verification → atomic family-bound three-pass grant → Play consumable consumption. Confirm the same one-time SKU can be repurchased.
7. Spend a pass and confirm the debit is durable after backend restart/new worker.
8. Buy an Extra Evidence Run and confirm it is bound to the same idea and unavailable to another idea.
9. Buy Founder Pro and confirm exactly 9 monthly passes are granted. Re-verify the same token/period and confirm it does not refill again.
10. Exercise a test renewal/RTDN period change and confirm the new verified period resets the monthly allocation to 9 once.
11. Confirm the $14.99 top-up is hidden/rejected when Pro is inactive and grants exactly 3 unbound passes when Pro is active.
12. Reinstall/open on another device and confirm `listPurchases()` plus backend verification restores the current subscription lifecycle without duplicate grants.
13. Configure authenticated RTDN push using `GOOGLE_PLAY_RTDN_SETUP.md` and confirm the Play Console test notification returns HTTP 204.
14. Exercise cancellation, expiration, grace-period, on-hold, revocation and restore flows; verify subscription status updates while already-granted wallet history remains auditable.
15. Confirm the UI displays localized Play-returned prices rather than hard-coded checkout values.
16. Confirm the 8/hour and 30/rolling-30-day **API safety ceilings** work across server instances; verify these ceilings do not themselves grant usage. During internal beta, also confirm the separate 9-run/14-day allowlist window.
17. Enable `BILLING_ENFORCED=1` only after all lifecycle tests pass.

### Current TWA account-binding limitation

As of this release pass, Android Browser Helper's Play Billing bridge accepts the SKU but does not expose Play Billing's `setObfuscatedAccountId` through Payment Request; upstream support is still an open request. Treat every purchase token as a bearer secret: HTTPS only, never log it, verify it server-side, hash it at rest, and keep Killgate's immutable first-owner rule. Reassess the upstream bridge before public release and consider a small native billing layer later if provider-level Killgate-account binding becomes a requirement.

## Play policy surfaces

- Public privacy-policy URL: `/privacy` on the production origin.
- Public account-deletion URL: `/delete-account` on the production origin.
- In-app account screen provides export, subscription-management/cancellation, restore, and deletion links.
- Account deletion clearly warns that deleting Killgate data does not cancel a Google Play subscription and links to Play subscription management first.
