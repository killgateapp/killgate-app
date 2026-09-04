# Validation Contract — CG-001

**Status:** LOCKED  
**Contract version:** 1.0  
**Created/locked:** 2026-08-27T08:30:00Z (before evidence scoring)  
**Hypothesis:** Residential remodeling contractors with 3–20 employees who have lost at least $1,000 from undocumented or poorly documented change work during the previous 90 days will pay $129/month for software that detects probable out-of-scope work from existing project communications and turns it into an approval-ready change order before the work is performed.

**Fingerprint:** remodel-3to20-129-changeorder-detect-approve

## Provisional
- US residential remodel (kitchen, bath, addition, whole-house). Not commercial GC.
- Integrates with existing PM (Buildertrend, CoConstruct, JobNimbus, JobTread, or similar) plus texts/email/notes.
- Buyer is owner or PM who can put a card on file.

## Mechanisms
- M1 CORE: Compare new customer requests/job notes to signed estimate/contract and flag probable out-of-scope work.
- M2 CORE: Assemble a proposed change order (change, supporting comms, labor/materials, price).
- M3 CORE: Homeowner approval/signature and optional deposit before additional work proceeds.
- M4 SUPPORTING: Ordinary SMS/email alerts to the contractor when a potential scope change is detected. Not claimed as differentiation. Commoditization of M4 does not pivot the offer.

## Critical assumptions
1. Target contractors lose ≥$1,000 / 90 days to undocumented change work.
2. Requests arrive in channels the product can see (text, email, job notes, photos, conversations).
3. Current workaround (verbal yes, text thread, native CO module used after the fact) leaves money on the table.
4. Detection + approval-ready CO is better on a dimension they value than the PM system they already pay for.
5. $129/mo sits on top of existing PM spend.
6. Crews will wait for approval instead of just doing the work.
7. Qualified buyers will pay a real $129 pilot.

## Locked gates
Default Killgate research and human/economic numeric gates. Unchanged. Research pass ≠ build permission. GO requires 8 qualified buyers, ≥30% strong pain with recent examples, 4 price-positive unless 2 paid, 2 verified paid pilots.
