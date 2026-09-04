# Validation Contract — COG-001

**Status:** LOCKED  
**Contract version:** 1.0  
**Skill version applied:** Killgate 1.3  
**Created/locked:** 2026-08-27T08:31:00Z (before evidence scoring)

**Hypothesis:** Residential remodeling contractors with 3–20 employees who lost at least $1,000 from undocumented or poorly documented change work in the previous 90 days will pay $129/month for an add-on that detects probable out-of-scope work from existing project communications, drafts an approval-ready change order (change + supporting comms + labor/materials + price), and collects homeowner signature and optional deposit before that work proceeds.

**Fingerprint:** remodel-3to20-129-changeorder-detect-approve

## Mechanisms
- M1 CORE: Detect probable out-of-scope requests/notes vs signed estimate/contract.
- M2 CORE: Assemble approval-ready CO with evidence pack and proposed price.
- M3 CORE: Homeowner approval/signature + optional deposit before work proceeds.
- M4 SUPPORTING: SMS/email alert to contractor when a potential scope change is detected. Not claimed as differentiation. Commoditization of M4 does not by itself force RESEARCH_PIVOT.

## Critical assumptions
1. Target contractors actually lose ≥$1,000 / 90 days on undocumented extras.
2. Leakage happens because detection/packaging/approval lags crew action, not only because owners refuse extras.
3. Existing PM tools do not already close this job well enough.
4. $129 is additive to current PM spend and authorized by owner/PM.
5. Detection from messy texts/photos is accurate enough to trust before work stops.
6. Homeowners will sign/pay mid-project on a software-generated CO.

## Locked gates
Default Killgate research + human/economic numeric gates. Unchanged.
Price in hypothesis = price at checkout = $129/month.
