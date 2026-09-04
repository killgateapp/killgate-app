# VALIDATION_CONTRACT_PROTOCOL.md

Purpose: prevent hindsight, confirmation bias, and moving goalposts by creating the decision rules before evidence is collected.

## Core Rule
The user does **not** have to invent a “pre-commit kill” condition. Killgate generates a Validation Contract from the hypothesis and the system's governed defaults before research begins.

The contract is a system control, not founder-supplied market evidence.

## Creation Timing
Create and lock the contract immediately after the hypothesis is entered and **before**:
- search queries are run,
- public evidence is scored,
- interviews are conducted,
- pilot offers are made,
- or a recommendation is generated.

Record:
- contract version,
- hypothesis fingerprint,
- creation timestamp,
- lock timestamp,
- critical assumptions,
- evidence hierarchy,
- evidence exclusions,
- research thresholds,
- direct-validation thresholds,
- economic thresholds,
- GO / CONTINUE_VALIDATION / PIVOT / KILL rules.

## Default Locked Gates
### Research Qualification
- ≥3 directly relevant public sources
- ≥2 independent domains/source groups
- direct topical evidence of the customer problem
- direct topical evidence of current behavior/workarounds/alternatives
- budget, pricing, existing-spend, or credible spend-proxy evidence for RESEARCH_PASS
- active search for disconfirming evidence

A research pass means only “worth direct buyer validation.” It never authorizes build.

### Human Reality Check
- ≥8 unique qualified direct-buyer conversations before GO eligibility; duplicate buyer labels do not increase the count
- continue toward 12 by default and up to 20 when evidence is ambiguous, biased, or insufficiently diverse
- ≥30% strong pain backed by a recent real example
- ≥4 buyers positive on the actual tested pilot price unless ≥2 real paid pilots already exist
- ≥2 completed pilot payments or verifiable paid deposits, each with a received amount and payment evidence/reference
- objections, “not a priority” feedback, and contradictory evidence recorded and weighed

## Evidence Hierarchy
0. Synthetic — AI simulation/speculation; never validation
1. Market fact — verified pricing, regulation, market artifact
2. Observed — real public user behavior/language
3. Direct — authentic buyer conversation/interaction
4. Commitment — concrete costly action short of payment
5. Payment — completed payment or verifiable paid deposit

Higher levels may strengthen a decision but may not be invented by relabeling lower levels.

## Decision Semantics
### GO
All locked GO gates pass and Evaluator verifies provenance. Human may approve the GO, but may not approve a GO that the Boolean gates reject.

### CONTINUE_VALIDATION
Use when the opportunity still has credible signal but one or more gates remain genuinely unresolved. The next experiment must be specific and time-bounded. Do not lower the locked threshold.

### PIVOT
Use when the underlying problem is credible but the tested ICP, offer, workflow, channel, positioning, or price is contradicted. A material pivot creates a **new hypothesis and new locked contract** before new evidence is collected.

### KILL
Use when sufficient evidence shows the buyer does not have meaningful recurring pain, existing alternatives solve the job adequately, commitment/payment remains below threshold after sufficient qualified testing without a credible narrower hypothesis, or a fatal legal/platform/technical/trust/economic constraint exists.

## Important Distinction: Missing Evidence vs Negative Evidence
Failure to retrieve enough useful web evidence may block progression, but absence of web evidence is **not automatically proof that demand is absent**.

- `RESEARCH_FAIL — INSUFFICIENT EVIDENCE` means the research packet cannot qualify the idea.
- A KILL recommendation should rely on affirmative disconfirming evidence, sufficient failed direct validation, or a fatal constraint—not merely a bad search result set.

## Change Control
After the first evidence item is collected:
- default thresholds may not be weakened,
- definitions of evidence may not be relaxed,
- failed evidence may not be reclassified merely to reach GO.

The human may add a stricter business-specific constraint (for example, “must not require HIPAA compliance”), but it must be additive, timestamped, and recorded in DECISION_LOG.md. It may not weaken the defaults.

## Evaluator Checks
Before RESEARCH_PASS or GO, verify:
- the contract predates the evidence being scored,
- its hypothesis fingerprint matches the active hypothesis,
- thresholds were not weakened after evidence arrived,
- the decision maps to the locked rules,
- lower-level evidence was not promoted to satisfy a higher-level gate.

## Killgate v1.5 Mechanism + Feasibility Locks
Before evidence is scored, decompose the offer into material mechanisms. Infer whether each is CORE or SUPPORTING when the founder does not label it.

For each mechanism, the research evaluator must later choose exactly one action:
- KEEP — supported or sufficiently established for the role it plays.
- TEST — material and still unproven.
- REMOVE_DEFER — commodity, unnecessary, or bundled downstream infrastructure whose removal does not change who pays, for what job, at what price, or why they pay.
- CONTRADICTED — evidence attacks a material value-producing claim.

Do not force a new commercial hypothesis merely because a supporting mechanism is bundled by incumbents. A bundled differentiator can force RESEARCH_PIVOT; bundled downstream infrastructure usually becomes REMOVE_DEFER.

### Feasibility gate
If willingness-to-pay depends on a technically uncertain capability and failure of that capability would collapse the economic thesis, ordinary price interviews are locked. The research-stage verdict becomes `FEASIBILITY_REQUIRED`.

Before that capability test runs, lock:
- only inputs available at the claimed decision time,
- later ground truth,
- metrics including true captures and false positives,
- whether a correct flag would have changed an operational action,
- baseline human/status-quo performance and any cheap commodity sibling tool,
- explicit pass thresholds,
- explicit fail thresholds.

Unproven is not the same as contradicted. A failed capability test does not automatically mean KILL; it may require a mechanism or commercial pivot.
