# Validation Contract Protocol

## Purpose

Prevent hindsight, confirmation bias, and moving goalposts by freezing the decision rules before evidence is collected.

## Creation timing

Create and lock the contract immediately after the hypothesis is normalized and before:

- web searches are scored;
- interviews are counted;
- pilot offers are evaluated;
- payments are counted;
- a verdict is generated.

Record at minimum:

- contract version;
- normalized hypothesis;
- hypothesis fingerprint if tooling supports it;
- critical assumptions;
- evidence that counts;
- evidence that does not count;
- research thresholds;
- direct-validation thresholds;
- economic thresholds;
- GO / CONTINUE_VALIDATION / PIVOT / KILL semantics.

## Default critical assumptions

1. A narrow, identifiable buyer experiences the stated problem in real life.
2. The problem is frequent, costly, risky, frustrating, embarrassing, or urgent enough to change behavior.
3. The buyer already uses a workaround, alternative, budget, or resource to address the job.
4. The proposed offer is meaningfully better than the current alternative on a dimension the buyer values.
5. A reachable buyer can authorize or influence a purchase.
6. The economics can support the proposed price and a realistic acquisition path.
7. Qualified buyers will accept a real paid pilot at the stated price, or a concrete pilot price will be established before direct testing.

## Default locked research rules

- minimum 3 directly relevant public sources;
- minimum 2 independent domains/source groups;
- directly relevant evidence of the customer problem;
- directly relevant evidence of current behavior/workarounds/alternatives;
- budget, pricing, existing-spend, or credible spend-proxy evidence for RESEARCH_PASS;
- active search for disconfirming evidence;
- at least 2 source-backed supporting claims for a PASS;
- at least 2 disconfirming/constraint findings for a PASS-quality packet;
- research pass means **worth direct buyer validation**, never permission to build.

## Default locked human/economic rules

- minimum 8 unique qualified direct buyers;
- target 8–12 by default;
- reassess the unchanged hypothesis by 20 qualified buyers;
- minimum 30% strong pain, backed by recent real examples;
- minimum 4 price-positive qualified buyers at a concrete tested price unless 2 verified paid pilots already exist;
- minimum 2 actual paid pilots or verifiable paid deposits;
- each counted payment requires amount > 0 and a meaningful receipt/invoice/payment reference;
- objections/no-priority reasons must be recorded for every qualified interaction;
- duplicates/follow-ups update a buyer but do not increase unique-buyer count.

## Change control

After the first evidence item is collected:

- do not lower thresholds;
- do not relax definitions;
- do not convert public evidence into direct evidence;
- do not convert verbal interest into payment;
- do not reuse a contract for a materially different hypothesis.

The user may add stricter constraints. Record them explicitly and keep them additive.
