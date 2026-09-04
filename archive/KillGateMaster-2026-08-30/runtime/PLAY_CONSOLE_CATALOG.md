# Google Play catalog to create for Killgate

Create these four products exactly as written for the current launch monetization.

| Play product ID | Type | US base price | Server grant |
|---|---|---:|---|
| `killgate_venture_pass` | One-time **consumable** | $19.99 | 1 Venture Pass = 3 research passes; auto-binds when purchased from an idea brief |
| `killgate_evidence_run` | One-time **consumable** | $7.99 | 1 research pass bound to the current idea family |
| `killgate_founder_pro` | Auto-renewing subscription, monthly base plan, **no free trial** | $59.99/month | 9 unbound research passes per verified billing period; unused expire |
| `killgate_founder_topup` | One-time **consumable** | $14.99 | 3 unbound research passes; server rejects purchase grant unless Founder Pro is active |

## Environment

```text
GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID=killgate_venture_pass
GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID=killgate_evidence_run
GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID=killgate_founder_pro
GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID=killgate_founder_topup
```

`GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID` remains accepted only as a temporary compatibility alias for `GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID`; new deployments should use the Founder Pro name.

## Console steps

1. Play Console → Killgate → Monetize → Products → In-app products / one-time products.
2. Create and activate `killgate_venture_pass`, `killgate_evidence_run`, and `killgate_founder_topup` as repurchasable/consumable products at the US base prices above.
3. Monetize → Subscriptions → create `killgate_founder_pro`.
4. Add one monthly auto-renewing base plan at $59.99 US. Do not add a free trial for launch.
5. Activate all four for the internal testing track before production.
6. Configure the four server environment variables above plus the final package name, Play service account, RTDN settings, and app-signing fingerprint.
7. Keep `BILLING_ENFORCED=0` only while wiring internal testing. Production release requires `BILLING_ENFORCED=1`.
8. Run all Supabase migrations through `20260828_killgate_founder_pro_wallet_rpc.sql`, including the research-quota-window migration, before enabling paid research.

## Checkout behavior

- Idea brief: Venture Pass → Extra Evidence Run → Founder Pro; top-up appears only when Pro is already active.
- Account page: Venture Pass → Founder Pro; top-up appears only for active Pro. Extra Evidence Run is omitted because it must be attached to a specific idea.
- One-time consumables are verified on the server, granted atomically, then consumed through the Play Developer API so they can be repurchased.
- Subscription renewal/refill is keyed to the verified billing-period expiry and handled through verification/RTDN.
