# Google Play RTDN Setup — Killgate

Killgate's runtime now contains an authenticated push endpoint at:

`POST https://<PRODUCTION_HOST>/billing/google-play/rtdn`

The endpoint does **not** trust the notification as entitlement truth. It validates the Pub/Sub OIDC identity, checks the Android package name, deduplicates by Pub/Sub `messageId`, hashes the purchase token, resolves the already-associated Killgate account, then calls Google Play `purchases.subscriptionsv2.get` and persists the fresh server-authoritative state.

## Required owner / Google Cloud values

- Production HTTPS host.
- Final Android package ID.
- Google Cloud project used for the Pub/Sub topic/subscription.
- A user-managed service account for authenticated Pub/Sub push.
- The final Pub/Sub push audience (normally the exact RTDN endpoint URL).

Set these server-side environment variables:

```env
GOOGLE_PLAY_RTDN_AUDIENCE=https://<PRODUCTION_HOST>/billing/google-play/rtdn
GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL=<PUSH_AUTH_SERVICE_ACCOUNT>@<GCP_PROJECT>.iam.gserviceaccount.com
```

## Google Play / Pub/Sub configuration

1. Create a Pub/Sub topic for Killgate RTDN.
2. Grant `google-play-developer-notifications@system.gserviceaccount.com` the **Pub/Sub Publisher** role on that topic.
3. Create a **push** subscription targeting the Killgate RTDN HTTPS endpoint.
4. Enable authenticated push and select the user-managed push-auth service account.
5. Set the OIDC audience to exactly the value used in `GOOGLE_PLAY_RTDN_AUDIENCE`.
6. Grant the Pub/Sub service agent permission to mint OIDC tokens for the selected push-auth account as required by Google Cloud.
7. Keep **payload unwrapping disabled**. Killgate uses the standard Pub/Sub wrapper because Google recommends deduplicating RTDNs by `messageId`.
8. In Play Console, configure the RTDN topic and select **subscriptions and all voided purchases** for v1. One-time products are not part of Killgate v1 billing.
9. Send the Play Console test notification. A successful authenticated delivery should receive HTTP `204`.

## Lifecycle behavior

For subscription RTDNs and voided subscription purchases, Killgate re-queries Google Play before changing entitlement. This covers renewal, cancellation, grace period, account hold, pause/recovery, revocation, expiration, and later lifecycle event types without treating the notification body itself as proof.

A new `SUBSCRIPTION_PURCHASED` notification can race the browser's first backend verification. If the RTDN token has not been associated with a signed-in Killgate account yet, the endpoint returns HTTP `503` so Pub/Sub retries instead of permanently discarding the event.

Processed Pub/Sub message IDs are stored in `public.play_rtdn_events`. The table has RLS enabled, no customer access, and stores only a SHA-256 token hash — never the raw purchase token.

## Test matrix before `BILLING_ENFORCED=1`

- Play Console test notification reaches the endpoint and is deduplicated on redelivery.
- New subscription becomes active and acknowledged.
- Renewal updates expiry.
- Voluntary cancellation remains entitled only through the Play-reported expiry.
- Grace period remains active if Play reports `SUBSCRIPTION_STATE_IN_GRACE_PERIOD` and expiry is still future.
- Account hold removes entitlement.
- Revocation removes entitlement immediately after Play re-verification.
- Expiration removes entitlement.
- Reinstall / second device restores by `listPurchases()` and backend verification.
- An intentionally duplicated Pub/Sub message does not call Google Play twice after the first successful processing.
