# Killgate Pricing & Unit Economics — 28 August 2026

## Commercial principle

Killgate sells **decisions, not unlimited AI access**. The default purchase is tied to one idea family. Founder Pro exists only for repeat users and remains metered.

## Launch catalog

| SKU | US base price | Entitlement | Intended customer |
|---|---:|---|---|
| **Venture Pass** | **$19.99 one-time** | Up to 3 live research passes on one idea family | Default / most founders |
| **Extra Evidence Run** | **$7.99 one-time** | 1 additional live pass, permanently bound to the same idea family | Founder continuing an existing validation |
| **Founder Pro** | **$59.99/month** | 9 unbound live research passes per billing month; unused monthly passes expire | Serial founders, consultants, high-frequency users |
| **Founder Pro 3-Run Top-Up** | **$14.99 one-time** | 3 additional unbound passes; purchasable only while Founder Pro is active | Pro users who exceed 9 in a month |

There is **no unlimited plan, no 30-run subscription, and no public free live-research trial**. A private, allowlisted beta can receive free access for the defined 14-day test window.

### Google Play product IDs

- `killgate_venture_pass` → `GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID`
- `killgate_evidence_run` → `GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID`
- `killgate_founder_pro` → `GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID`
- `killgate_founder_topup` → `GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID`

The PWA must display Google Play's localized checkout price. The dollar values above are US base-price planning values, not hard-coded checkout amounts.

## What the customer gets before paying

`/v/{id}/brief` remains free and is generated from the locked Validation Contract only. It shows:

- the frozen hypothesis;
- critical assumptions;
- query-family labels;
- the gates that can still fail;
- what public research can and cannot establish;
- the exact work order the paid pass will run.

It does **not** reveal live sources, quotes, scores, findings, or a verdict.

## Venture Pass rules

1. One Venture Pass creates one three-pass entitlement.
2. When bought from an idea brief, the pass is bound to that idea family immediately.
3. A legitimate pivot child inherits the parent `pass_family_id` and can use remaining passes.
4. The same unchanged hypothesis cannot be rerun merely to shop for model/search variance.
5. A new unrelated business concept requires a new Venture Pass or an available Founder Pro pass.
6. Purchased Venture Pass entitlements expire after 12 months if unused.

## Extra Evidence Run rules

The $7.99 Extra Evidence Run is not a generic wallet credit. It is a one-pass family-bound entitlement and therefore cannot be moved to another idea. This preserves the intended promise: **same project, one more check**.

## Founder Pro rules

- $59.99/month.
- 9 unbound research passes per actual Google Play billing period.
- The period is keyed to the server-verified subscription expiry; repeated verification of the same period does not refill it twice.
- Unused subscription passes expire when that billing period ends.
- Renewal/refill is driven by Play verification/RTDN and stored in the durable wallet.
- Founder Pro does not bypass the wallet and never means unlimited access.
- A $14.99 top-up grants 3 unbound passes only if a current Founder Pro entitlement is verified.
- No automatic overage billing: the user explicitly buys a top-up.

## Private beta

Private beta testers do not pay for research. The server allowlists their Supabase Auth user IDs and grants up to 9 free live research runs during one 14-day beta window. Beta access is not a public signup benefit, does not create wallet credits, and is disabled before a Play release.

## Production durability and abuse controls

Production uses `WALLET_BACKEND=supabase` (or inherits `STATE_BACKEND=supabase`). Grants, pass binding, subscription refills, and research debits execute through atomic server-only Supabase RPCs with per-user advisory locks.

Consumable Play purchases are consumed only **after** Killgate's durable ledger accepts the grant. That makes the SKU repurchasable without risking duplicate entitlement grants.

`RESEARCH_SAFETY_CAP_30D` is a separate fraud/capacity safety ceiling. Default: **30 successful research runs per rolling 30 days**, plus the existing **8/hour** burst ceiling. It does not grant research and is not marketed as a plan allowance. Internal beta access is separately allowlisted for **9 free runs during one 14-day window**.

## Planning unit economics

Planning reserves:

- Google Play: 15% reserve.
- AI + search: $0.20 per live pass reserve.
- Refund reserve: 8% of one-time SKU gross; 5% of subscription gross.
- Support/development reserve: 15% of post-Play receipts.

| SKU | Gross | Play 15% | AI reserve | Refund reserve | Support reserve | Contribution before fixed infra/tax |
|---|---:|---:|---:|---:|---:|---:|
| Extra Evidence Run (1) | $7.99 | $1.20 | $0.20 | $0.64 | $1.02 | **$4.93** |
| Venture Pass (3) | $19.99 | $3.00 | $0.60 | $1.60 | $2.55 | **$12.24** |
| Founder Pro (9 used) | $59.99 | $9.00 | $1.80 | $3.00 | $7.65 | **$38.54** |
| Founder Pro Top-Up (3) | $14.99 | $2.25 | $0.60 | $1.20 | $1.91 | **$9.03** |

These are planning reserves, not forecasts. Replace them with measured p50/p95 research cost, refunds, conversion, repeat-purchase rate, and support burden after launch.

## Repricing strategy

Launch Venture Pass at $19.99. Do not lower it to compete on report volume. Once Killgate has enough real purchases to measure conversion, test $24.99 and $29.99 for new customers. Keep the decision framework, not raw run count, as the core value proposition.

Founder Pro should remain a minority path. If ordinary founders start choosing it simply because the Venture Pass economics are unattractive, revisit the packaging rather than increasing included monthly runs.
