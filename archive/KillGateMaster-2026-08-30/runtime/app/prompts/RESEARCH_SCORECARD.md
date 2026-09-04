# RESEARCH_SCORECARD.md

This gate determines whether a hypothesis deserves human validation time. It does not authorize build or GO.

## Required Gates
- [ ] Active Validation Contract was locked before the evidence being scored
- [ ] Contract fingerprint matches the active hypothesis
- [ ] Every retrieved result is classified DIRECT / INDIRECT / IRRELEVANT before scoring
- [ ] ≥3 independent DIRECT sources across ≥2 domains clear the automated relevance pre-gate
- [ ] DIRECT evidence covers both the customer problem and current behavior/workarounds/alternatives
- [ ] Dictionary/reference pages, generic social profiles, Wikipedia, and isolated keyword matches contribute zero points
- [ ] ≥30 relevant observed-user evidence items after deduplication
- [ ] Evidence represents ≥15 independent observed voices/accounts when identity/context permits
- [ ] Evidence spans ≥3 independent communities/domains OR a documented reason the buyer is concentrated in fewer places
- [ ] ≥3 recurring pain/workflow themes are identified
- [ ] ≥2 distinct current workarounds or alternatives are documented
- [ ] ≥3 relevant alternatives/pricing observations are documented when competitors exist
- [ ] Existing-spend or budget-proxy evidence is present
- [ ] Negative/disconfirming evidence was actively sought and recorded
- [ ] No fatal legal/platform/technical constraint is unresolved
- [ ] Every material conclusion links to Evidence IDs
- [ ] Every material supporting claim explains which DIRECT source supports it and how

## Research Strength Indicators
Observed voices supporting primary pain:
Independent source groups:
Current workaround examples:
Existing-spend/budget proxy examples:
Competitor price range:
Strongest repeated complaint:
Strongest disconfirming finding:
Unresolved uncertainty:

## Result
- Missing/insufficient web evidence blocks RESEARCH_PASS but does not, by itself, prove KILL.
- RESEARCH_PASS | RESEARCH_FAIL | RESEARCH_PIVOT
- Confidence (0–1):
- Evidence IDs:
- Human questions that remain genuinely unanswered:

## v1.5 mechanism / feasibility checks
Before accepting RESEARCH_PASS:
- mechanism scoreboard present,
- CORE vs SUPPORTING classified,
- commodity downstream mechanisms do not create inherited pivots,
- no unresolved load-bearing CORE capability remains at TEST.

If a load-bearing CORE capability remains technically unproven and a complete capability test can be pre-registered, verdict = `FEASIBILITY_REQUIRED`, not RESEARCH_PASS.

Allowed research verdicts:
- RESEARCH_PASS
- RESEARCH_FAIL
- RESEARCH_PIVOT
- FEASIBILITY_REQUIRED
