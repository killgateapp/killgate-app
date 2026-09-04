# Final Decision Gate

Use deterministic logic. Narrative confidence cannot override Boolean gate failure.

## Gate metrics

Calculate from **unique qualified buyers** using the latest qualified interaction per buyer for pain/price language. A verified payment from any valid follow-up for that buyer remains durable economic evidence.

- `conversations` = unique qualified buyers
- `strong_pain_count` = unique buyers whose latest record is strong pain
- `strong_pain_ratio` = strong_pain_count / conversations
- `price_positive_count` = unique buyers with a valid concrete price-positive reaction
- `paid_pilot_count` = unique buyers with at least one verified paid record
- `contradictions_reviewed` = every qualified interaction has objection/no-priority text

## Default thresholds

- minimum conversations: 8
- target: 8–12
- reassessment ceiling: 20
- minimum strong-pain ratio: 30%
- minimum concrete price-positive buyers: 4, unless at least 2 verified paid pilots already exist
- minimum verified paid pilots/deposits: 2

## GO

Return `GO` only if **all** are true:

1. locked contract matches current hypothesis;
2. research gate passed;
3. conversations >= 8;
4. strong_pain_ratio >= 0.30;
5. price_positive_count >= 4 OR paid_pilot_count >= 2;
6. paid_pilot_count >= 2;
7. contradictions_reviewed is true.

## CONTINUE_VALIDATION

Prefer when:

- contract mismatch, research not passed, or fewer than 8 qualified buyers means the final gate is not yet ripe; or
- strong demand signal exists but one required gate remains genuinely unresolved and a specific next experiment can resolve it without weakening thresholds.

## PIVOT

Return `PIVOT` when any of these patterns applies:

- strong-pain ratio is below threshold **but verified payments already meet the payment gate**: the economic signal is real, but the ICP/problem framing is inconsistent;
- at least 20 qualified buyers have been tested and fewer than 2 verified payments exist: do not keep testing the unchanged hypothesis indefinitely;
- pain clears but price-positive/payment response is weak: likely offer/price/positioning/ICP misalignment;
- evidence says the underlying problem is credible but the tested buyer, offer, workflow, channel, positioning, or price is contradicted.

A material pivot requires a new hypothesis and new locked Validation Contract.

## KILL

Return `KILL` when the final gate is mature enough and affirmative evidence shows:

- strong-pain ratio remains below 30% without compensating paid evidence; or
- target buyers do not meaningfully prioritize the problem;
- adequate alternatives solve the job well enough that the offer lacks a defensible improvement;
- commitment/payment remains below the locked bar after sufficient qualified testing and no credible narrower hypothesis survives;
- a fatal legal, platform, trust, technical, or economic constraint makes the opportunity commercially unattractive.

Do not KILL solely because web search failed to retrieve enough evidence.

## Human authority

A human may reject or defer a GO. A human may impose stricter constraints. A human may not declare GO when the locked Boolean gates reject GO without explicitly creating a new future hypothesis/contract and collecting new evidence under it.
