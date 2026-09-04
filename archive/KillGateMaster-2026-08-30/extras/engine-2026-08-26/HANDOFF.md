# Killgate handoff — 26 August 2026

Private validation workspace. Most ideas should not be built. This gate makes that decision expensive to fake.

## What this product is

Killgate is not an idea mill. You write a draft, lock a buyer / price / offer, attest public sources, record unique buyers, and a deterministic evaluator returns:

- `GO_BUILD` — buyer evidence permits a testable MVP
- `GO_SELL` — MVP trials, successful outcomes, and purchase or pilot commitments
- `CONTINUE` — missing evidence
- `PIVOT` — sample contradicts the locked profile
- `KILL` — completed low-pain sample, or a fatal constraint with owner confirmation
- `OWNER_STOPPED` — you stopped; never recorded as an evidence-backed kill

Thresholds are system-owned. AI cannot lower them.

## What shipped on 26 August

The 25 August engine was complete and unwired. It is now the UI.

1. **TypeScript port of the adaptive evaluator**, matching the Python contract (29 original tests still pass, plus slot and packet tests).
2. **Three live locks.** A draft is cheap. Confirming a buyer, price, and offer takes a slot. A fourth lock is blocked until you archive one.
3. **Archive** keeps the ledger and frees a slot. Unarchiving a locked idea needs an open slot.
4. **Evidence packet export.** Dated JSON: locked profile, fingerprint, gate, sources, buyers, trials. A GO is a contract against that file.

There is no account and no bill. The cap is the product.

## Layout

```
src/lib/killgate/
  types.ts          gates, thresholds, records
  evaluator.ts      deterministic recommendation
  profile.ts        lock + fingerprint (SHA-256)
  slots.ts          MAX_LIVE_LOCKS = 3
  packet.ts         evidence packet
  store.ts          localStorage workspace
  *.test.ts         36 tests

src/routes/
  index.tsx         live / drafts / archive
  v.$ventureId.tsx  contract, research, buyers, build, risk, log
```

## How to run the PWA zip

```
npm install
npm run dev
```

Open the printed local URL. `npm test` runs the gate, slot, and packet tests.

## Slot rules

| Action | Uses a live slot? |
|---|---|
| Start a draft | no |
| Lock buyer / price / offer | yes, unless that workspace is already live |
| Pivot the locked profile | no — same slot |
| Archive | frees the slot, ledger stays |
| Unarchive a locked idea | yes, needs a free slot |
| Unarchive a draft | no |
| Load GO BUILD sample | yes |

## Packet

Export writes `killgate-{gate}-{name}-{date}.json`. It is an attested snapshot of owner-entered evidence. Killgate does not independently verify interviews, payments, or URLs.
