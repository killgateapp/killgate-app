# OpenAI API Cost Benchmark Spec

Goal: estimate average dollar cost of one Killgate research run using production-like OpenAI API calls.

## Keep constant
- identical Killgate instruction/reference text;
- identical idea prompts;
- model and reasoning effort;
- web-search configuration/context level;
- max output / report structure;
- geographic assumptions where relevant.

## Record per run
- model;
- reasoning effort/mode;
- input tokens;
- cached input tokens;
- output tokens;
- reasoning tokens if reported;
- total tokens;
- number of web-search calls;
- elapsed time;
- verdict;
- confidence;
- whether sources/gates passed;
- estimated dollar cost.

## Benchmark design
Run at least 10 different ideas. For variance, run 3 repeats of at least 3 ideas. Report median, mean, p25, p75, and max. Do not estimate production cost from a single unusually long or short research packet.

## Cost equation
Model cost = uncached input tokens * input rate + cached input tokens * cached-input rate + output tokens * output rate.

Add web-search tool charges and search-content token charges according to the current OpenAI pricing page.

## Important
ChatGPT Project runs do not expose equivalent API billing, so use them to validate behavior only. The API benchmark is the source of truth for production cost.
