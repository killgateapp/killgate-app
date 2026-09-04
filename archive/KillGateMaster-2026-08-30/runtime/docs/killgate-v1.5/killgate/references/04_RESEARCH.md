# Research Protocol and Gate

After lock, run live research. Do not return a query plan instead of results when tools work.

Investigate buyer, job, unprompted problem language, frequency/cost, workarounds, alternatives and prices, complaints about alternatives, spend evidence, triggers, disconfirming evidence, reachability, constraints.

If the user does not label mechanisms, infer them from the offer and classify core vs supporting before scoring.

## Research outcomes
- RESEARCH_PASS: packet clears the deterministic gate. May include REMOVE_DEFER implementation constraints. Means worth direct buyer validation. Not GO. Cap confidence.
- RESEARCH_FAIL: packet lacks required evidence. Not automatically KILL.
- RESEARCH_PIVOT: some signal exists, but the locked commercial hypothesis (buyer, job they pay for, offer shape that carries WTP, or price) is contradicted or incomplete.
- FEASIBILITY_REQUIRED: pain and alternatives are real enough that the idea is not empty, but WTP hangs on a technically uncertain capability whose failure collapses the thesis. Public evidence does not establish that available inputs contain enough signal. Next step is a locked capability test, not $price interviews.

Do not RESEARCH_PIVOT solely because a supporting or downstream-bundled mechanism is commodity.
Do not RESEARCH_PASS when the recommended cheapest test is “see if the model can do the hard thing.” That contradiction means FEASIBILITY_REQUIRED.

Load-bearing capability test (lock before running):
- inputs limited to what would have been available at the claimed decision time
- comparison against later ground truth (teardown, lab result, realized outcome)
- metrics: true captures of the costly events, false positives, whether a correct flag would have changed an operational action
- baseline: human status quo and any cheap commodity tool that covers the non-differentiated sibling job
- pass/fail thresholds written down first

A failed feasibility test is not automatically KILL. It can PIVOT the mechanism (sell the commodity sibling at commodity price, or stop). A passed test unlocks ordinary RESEARCH_PASS / human WTP gates on the same commercial hypothesis if the WTP sentence is unchanged.

Deterministic PASS minimums:
- contract locked first
- ≥3 independently useful DIRECT sources
- DIRECT evidence in ≥2 source groups
- pain; workarounds/alternatives; budget/spend or proxy
- disconfirming search done
- ≥2 source-backed supporting claims
- ≥2 disconfirming or constraint findings
- no known fatal unresolved constraint
