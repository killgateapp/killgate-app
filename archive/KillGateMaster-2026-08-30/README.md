# Killgate current merged release — v1.2.0 — 28 August 2026

This is the newest consolidated Killgate working set produced from the August 26 archive, the August 27 v1.5 merged source, and the August 28 monetization branch.

## Authoritative runtime

`runtime/` is the current Python PWA/backend. It retains the **v1.5 validation/feasibility-gate engine** while the application/runtime release is **v1.2.0**.

### Current monetization

- **Free Killgate Brief:** locked hypothesis/contract + exact research work order; no live evidence, sources, score, or verdict.
- **Venture Pass — $19.99:** one idea family, up to **3 live research passes**.
- **Extra Evidence Run — $7.99:** **1** additional pass bound to the same idea family.
- **Founder Pro — $59.99/month:** **10** live research passes per verified billing period; unused monthly passes expire.
- **Founder Pro 3-Run Top-Up — $14.99:** **3** additional unbound passes; active Founder Pro required.
- **No unlimited research and no 30-run monthly entitlement.**

Google Play catalog IDs documented for production:
- `killgate_venture_pass`
- `killgate_evidence_run`
- `killgate_founder_pro`
- `killgate_founder_topup`

### Billing/entitlement protections now baked in

- Production wallet state is durable and atomic through Supabase RPCs, not Cloud Run local disk.
- Venture Pass / Evidence Run family binding is enforced server-side.
- Founder Pro refills once per verified billing period.
- Founder Pro top-ups require a current Pro entitlement.
- One-time Play products are consumed **only after** the Killgate ledger durably grants the entitlement.
- A paid research debit carries a unique receipt. If provider execution or state persistence fails before the result is delivered, Killgate restores that entitlement **exactly once**.
- Paid entitlements are separate from the hidden anti-abuse ceiling (`RESEARCH_ABUSE_CAP_30D`, default 60).

See:
- `runtime/PRICING_AND_UNIT_ECONOMICS.md`
- `runtime/PLAY_CONSOLE_CATALOG.md`
- `runtime/RELEASE_NOTES_V1.2.0.md`

## Preserved references

`extras/` contains older August 26 engine/PWA/screenshots and handoff material retained for provenance and product rules. They are **reference material**, not the authoritative runtime.

## Verification status

The merged functional/runtime suite passed:

**181 passed, 1 deselected**

The deselected test is the Android preview APK modern-signature build test because this build sandbox does not contain Android SDK `d8`/`apksigner`. No new APK is claimed from this package. The source/build scripts remain included for execution in an Android SDK environment.

## Run tests

```bash
cd runtime
python -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock
pytest -q
```
