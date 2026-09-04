# Mechanism and Provenance Rules — v1.4

## Purpose
Prevent mechanism bleed, false pivots, and fake evidence independence.

## Infer mechanisms before scoring
Break the offer into the smallest commercially meaningful causal claims. Do not rely on the founder to label core/supporting features.

For each mechanism assign one ROLE:
- `CORE_VALUE`: directly carries differentiated buyer value / willingness-to-pay.
- `CORE_INPUT`: necessary input to a core-value mechanism but not independently valuable.
- `SUPPORTING`: useful UX or delivery mechanism that does not carry the thesis.
- `DOWNSTREAM_INFRASTRUCTURE`: capability needed to complete the workflow but which can reasonably be supplied by an incumbent/integration.
- `CONSTRAINT`: boundary, safety rule, compliance requirement, human-review rule, etc.

Assign one STATUS:
- `SUPPORTED`
- `PLAUSIBLE`
- `TEST`
- `COMMODITY`
- `BUNDLED`
- `REMOVE_DEFER`
- `CONTRADICTED`

## Whole-contract pivot rule
A mechanism being commodity/bundled does NOT automatically force RESEARCH_PIVOT.

Ask whether removing or integrating that mechanism materially changes:
1. the locked buyer;
2. problem/job;
3. differentiated value;
4. price/economic justification;
5. reason the buyer would pay.

If no, mark `REMOVE_DEFER` or treat it as downstream infrastructure and continue evaluating the remaining value-producing mechanisms.

A whole-contract RESEARCH_PIVOT is justified when evidence attacks or removes a mechanism that materially carries differentiation, economics, or willingness-to-pay, or otherwise requires a material change to buyer/problem/offer/price.

## Mechanism decomposition rule
If one mechanism hides multiple causal jobs, split it. Example: “predict supplement omissions” may contain (A) detect written estimate omissions and (B) predict physically hidden damage. Evidence for A cannot validate B; evidence against B cannot automatically erase A.

## Source diversity vs evidence independence
Track separately:
- `source_diversity`: distinct domains/entities/platforms;
- `evidence_independence`: observations produced by meaningfully unlinked people/data/incentives.

Three vendor websites can establish category feature/pricing facts but are not three independent demand observations. Ten articles quoting one study are one underlying observation. Large vendor datasets may be useful but must retain provenance, incentive, methodology, and selection-bias caveats.
