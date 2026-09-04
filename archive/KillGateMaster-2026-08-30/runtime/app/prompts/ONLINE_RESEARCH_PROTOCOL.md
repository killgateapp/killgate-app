# ONLINE_RESEARCH_PROTOCOL.md

Purpose: replace broad human discovery work with auditable public-market research while preserving the distinction between observed evidence and direct/economic validation.

## Core Rule
Online research may qualify or kill a hypothesis before human outreach. It may not, by itself, satisfy a GO decision.

## Source Relevance Pre-Gate
Classify every retrieved result before it can enter the Evidence Ledger or influence a score:
- **DIRECT:** contains evidence about the named buyer, problem, current behavior, workaround/alternative, pricing, existing spend, or willingness to pay.
- **INDIRECT:** provides adjacent context but does not substantiate a material hypothesis claim.
- **IRRELEVANT:** matches only isolated words or provides generic reference material unrelated to customer demand.

**Important:** `DIRECT` in this protocol is only a public-source relevance label. It does **not** mean Evidence Level 3 direct-buyer evidence. A directly relevant Reddit thread, review, or competitor-pricing page can qualify public research, but it can never substitute for a real buyer conversation or payment.

Dictionary definitions, thesaurus pages, generic social profiles, Wikipedia pages, and isolated keyword matches are always IRRELEVANT for demand validation and receive zero points.

The automated packet must contain at least three independent DIRECT sources across at least two domains, DIRECT evidence of the customer problem, and DIRECT evidence of current behavior/workarounds/alternatives. Otherwise return `RESEARCH_FAIL — INSUFFICIENT RELEVANT EVIDENCE`. Every material supporting conclusion must state exactly which DIRECT source supports it and how.

## Research Questions
For every hypothesis, the Validation Agent must answer:
1. Who is the narrowest plausible buyer and where do they congregate publicly?
2. What job are they trying to accomplish?
3. What exact problem language recurs without prompting?
4. How frequent, costly, risky, embarrassing, or time-consuming is the problem?
5. What workarounds are already being used?
6. What products/services compete for the same job, and what do they cost?
7. What do buyers repeatedly dislike about those alternatives?
8. What evidence suggests an existing budget or willingness to spend?
9. What trigger events make the problem urgent?
10. What would make the hypothesis false or commercially unattractive?
11. Which acquisition channels contain the buyer at reasonable concentration?
12. What legal, platform, technical, or trust constraints could make the product impractical?

## Source Priority
Prefer first-party or user-generated material over summaries about users.

High-value observed sources:
- Public forum/community threads
- Product reviews and app-store reviews
- Competitor support forums and issue trackers
- GitHub issues/discussions when relevant
- Public social posts/comments with clear context
- Public Q&A/community discussions
- Public job posts or workflow documentation showing the task exists
- Competitor pricing/product pages for factual market claims

Supporting sources:
- Industry reports
- Search trend/demand evidence
- News or trade publications
- Product directories

Never count synthetic personas, AI role-play, generated survey answers, or agent speculation as market validation.

## Required Pipeline
### 1. Hypothesis packet
Write a one-sentence buyer/problem hypothesis and 3–7 falsifiable subclaims.

### 2. Query plan
Create searches for:
- pain language
- workaround language
- competitor complaints
- switching/cancellation language
- pricing/budget language
- "not a problem" / negative evidence
- failed or abandoned solutions

### 3. Raw collection
Every useful item becomes an EVIDENCE_LEDGER entry with URL/source identifier, date accessed, exact quote or factual artifact, context, and evidence level.

### 4. Normalize and deduplicate
Before counting evidence:
- Canonicalize URLs.
- Cluster near-identical text.
- Treat reposts/syndicated material as one source.
- Treat multiple comments from the same account in the same discussion as one independent voice for prevalence counts.
- Record source platform/domain so one community cannot masquerade as broad market coverage.

### 5. Code themes
Tag each item with one or more of:
- pain
- frequency
- consequence
- workaround
- spend/budget proxy
- competitor complaint
- desired outcome
- switching trigger
- distribution channel
- negative/disconfirming
- regulatory/technical constraint

### 6. Competitor and pricing pass
Record at least three relevant alternatives when they exist, including pricing, target buyer, core promise, and repeated complaints. "No competitor" is not automatically positive evidence.

### 7. Adversarial/disconfirming pass
The Validation Agent must actively search for reasons the idea is weak. At least 20% of the final research evidence set should be negative, contradictory, neutral, or constraint-related when such evidence exists.

### 8. Research Qualification Gate
Complete RESEARCH_SCORECARD.md. Only a PASS may create a Human Reality Check task.

### 9. Human Reality Check packet
Convert research into a short, targeted script. Do not ask the human to rediscover facts already observed. Ask only questions that require a real person's direct answer, behavior, authority, or willingness to pay.

### 10. Economic gate
At least two actual pilot payments are required for GO. Public statements such as "I'd pay for this" never equal payment.

## Counting Rules
- A theme count is a count of independent observed voices, not documents.
- One person repeating the same complaint ten times = one voice for prevalence.
- Ten articles quoting the same study = one underlying evidence source.
- Competitor marketing claims do not count as customer pain evidence.
- Anonymous claims may be used, but reliability should be lower when identity/context cannot be assessed.
- Evidence gathered from a seller's own testimonials must be labeled commercially interested.

## Output
The Validation Agent produces:
1. Research Scorecard
2. Evidence-backed problem brief
3. Contradiction brief
4. Competitor/pricing table
5. Human Reality Check packet
6. Recommendation: RESEARCH_PASS | RESEARCH_FAIL | RESEARCH_PIVOT

A RESEARCH_PASS means "worth asking real buyers," not GO.

## Killgate v1.5 mechanism review
Split stacked claims rather than letting one supported sibling inherit credibility for another. Example structure: detect A + predict B + reduce delay + cause payment are separate claims.

For every material mechanism output:
- mechanism,
- role: CORE or SUPPORTING,
- action: KEEP / TEST / REMOVE_DEFER / CONTRADICTED,
- whether it is load-bearing,
- whether changing/removing it changes the commercial hypothesis,
- strongest source or provenance limitation.

Different URLs are source diversity, not automatically independent evidence. Vendor/help-center domains may establish that a feature exists, but commercially interested sources remain one evidence family for demand/WTP/ROI unless methods and incentives are genuinely independent.

### Additional research outcome: FEASIBILITY_REQUIRED
Return `FEASIBILITY_REQUIRED` when pain, alternatives, and spend signal are real enough to continue, but the differentiated economic thesis depends on an unproven load-bearing technical capability. Do not send the founder into ordinary willingness-to-pay interviews first.

A `RESEARCH_PASS` is invalid when the cheapest honest next test is still “can the system actually do the hard thing?”
