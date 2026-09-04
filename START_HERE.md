# Killgate ChatGPT Project Pack

Purpose: make a new ChatGPT Project behave as a close, auditable Killgate research harness and later reuse the same policy in an OpenAI API benchmark.

## ChatGPT setup

1. Create a new ChatGPT Project named `Killgate Research Benchmark`.
2. Set Memory to **Project-only**.
3. Open Project settings and paste the full contents of `PASTE_INTO_PROJECT_INSTRUCTIONS.md` into Project Instructions.
4. Upload the files in `references/` plus `benchmarks/TEST_IDEAS.md`.
5. Start each benchmark idea in a **new chat inside the same project** so prior run details do not contaminate the current idea more than necessary.
6. Use the same model/reasoning setting for every benchmark run.
7. Ask: `Run the complete Killgate process on this idea: ...`

## Important cost note

ChatGPT Project usage is not API billing. The Project is for behavior/quality testing. Exact production cost must be measured with the API using the same policy, model, web-search tool, and representative prompts.

## Suggested benchmark set

Run at least 10 ideas spanning:
- clearly weak consumer idea;
- plausible B2B SaaS;
- commodity-feature trap;
- core-vs-supporting mechanism trap;
- technically load-bearing feasibility trap;
- crowded market with real pain;
- regulatory/trust constraint;
- strong incumbent workflow;
- narrow high-value niche;
- apparently excellent idea that should still not receive GO without buyers/payments.

Record verdict, search behavior, response length, and later API usage/cost for each run.
