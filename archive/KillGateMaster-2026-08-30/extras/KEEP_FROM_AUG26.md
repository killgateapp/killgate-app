# Differences kept from the 26 August bundle

The 27 August Python runtime is the Play/research product. The 26 August TypeScript PWA is a second generation that shipped product rules the Python app still does not implement as first-class UI.

Keep these. Do not throw them away because billing changed.

## Keep as product rules

From `extras/pwa-reference-2026-08-26` and `extras/engine-2026-08-26`:

- `GO_BUILD` vs `GO_SELL` — buyer evidence can permit a testable MVP without pretending you already have a sellable product.
- Three live locks. Drafts are cheap. A fourth lock is blocked until one idea is archived.
- Archive frees a slot and keeps the ledger. Unarchiving a locked idea needs a free slot.
- Pivot inside a lock does not consume a new slot (Python already creates a child venture; the family-bound Venture Pass now pays for that child).
- Evidence packet export as a dated attested snapshot.
- Fake payment refs (`cash` / `paid` / `yes`) do not count.
- AI cannot lower thresholds.

Those rules live in the portable engine tests. The Python runtime still uses GO / CONTINUE_VALIDATION / PIVOT / KILL and does not yet enforce the 3-lock cap. Merge that cap later; do not lose the engine.

## Keep as artifacts

- `extras/screenshots-2026-08-26` — home, GO BUILD, slots full, archive, desktop/phone.
- `extras/KILLGATE-HANDOFF-2026-08-26.md`
- `extras/engine-2026-08-26` — drop-in TypeScript gate.

## Do not keep from August 26

- “There is no account and no bill. The cap is the product.” That is replaced by the credit/pass catalog.
- Any implication that a local slot cap is the monetization model.

## Do not keep from August 24/25 pricing

- $14.99/month as the only SKU
- 30 research runs bundled into that subscription
- Research locked solely behind an active subscription
- Homepage CTA “Subscribe with Google Play”
