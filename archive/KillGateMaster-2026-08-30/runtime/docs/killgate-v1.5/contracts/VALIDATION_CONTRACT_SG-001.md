# Validation Contract — SG-001

**Status:** LOCKED  
**Contract version:** 1.0  
**Skill version:** Killgate 1.4  
**Created/locked:** 2026-08-27T08:36:00Z (before evidence scoring)

**Hypothesis:** Independent collision shops with 3–20 technicians that process ≥30 insurance-paid repairs per month and experience recurring supplement-related production delays will pay $249/month for an add-on that, before teardown, analyzes the initial insurance estimate plus photos, VIN/vehicle data, labor ops, parts lists, historical repair patterns, and insurer-specific supplement patterns, then gives the estimator a prioritized review packet of likely omissions — because preventing one meaningful supplement delay per month covers $249.

**Fingerprint:** collision-indie-3to20-30ro-249-presupplement-review

**Price lock:** $249/month in hypothesis and at checkout.

## Mechanisms (inferred; user did not label)
Provisional labels to be confirmed after research. WTP sentence hangs on pre-teardown omission prediction, not on notifications or claim filing.

- M-predict: identify likely missed damage/ops before teardown
- M-insurer: use insurer-specific supplement patterns
- M-packet: prioritized estimator review list
- M-integrate: sit on existing estimating workflow
- M-human: estimator decides; no claim submit / no insurer negotiation

## Critical assumptions
1. Target shops have recurring supplement delays that cost ≥$249/month in cycle time, throughput, or rental/penalty pain.
2. A useful share of those supplements is predictable from pre-teardown artifacts (photos, VIN, estimate lines), not only from physical disassembly.
3. Estimators will review a packet before production and change behavior (add lines, sequence teardown, pre-alert insurer).
4. Incumbent estimating stacks do not already do this well enough.
5. Owner/GM can add $249 on top of CCC/Mitchell/shop management.
6. Integration is possible without becoming a claims-filing product.

## Locked gates
Default Killgate research + human/economic numeric gates. Unchanged.
