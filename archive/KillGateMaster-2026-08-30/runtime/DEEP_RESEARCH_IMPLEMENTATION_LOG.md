# Deep Research implementation log

## Phase 0 — baseline/audit

- Active source is `runtime/`; `extras/` remains reference material.
- Existing research, wallet, validation-contract, gate, rate-limit, state-store,
  and readiness services are the extension points. No legacy `extras/` imports
  were changed.
- The existing engine has live search, source classification, structured
  Responses API output, source-backed gates, mechanism scoring, feasibility
  gating, wallet debit/refund reconciliation, and persisted venture state.
- Documentation/code drift remains: the scorecard describes stronger observed
  evidence than the executable minimums. Phase 11 must reconcile that before a
  Deep Research PASS is promoted.
- The active handoff directory has no local `.venv`, so the historical test
  total was not silently presented as a fresh run. Production Secret Manager
  update is blocked by invalid local `gcloud` credentials; no production change
  was made.

## Phase 1 — bounded research domain (local)

- Added `app/models/deep_research.py` with run status, source, claim, plan,
  budget, cost-ledger, and run-envelope contracts.
- Added `app/services/deep_research.py` with deterministic input/evidence
  fingerprints, legal lifecycle transitions, and side-effect-free run
  initialization.
- Added `tests/test_deep_research.py` for lifecycle, fingerprint, budget, and
  validation behavior.
- No network calls, model calls, wallet debits, migrations, deployment
  changes, or production secret changes occur in this phase.

## Phase 2 — durable run persistence (local implementation)

- Added the additive migration
  `supabase/migrations/20260901042323_deep_research_runs.sql`.
- Added a server-only `deep_research_runs` table with validation and hypothesis
  fingerprints, venture-family lineage, evidence fingerprint, lifecycle status,
  optimistic revision, checkpoint, cost ledger, result, report, and failure
  fields.
- Enabled RLS, revoked table access from `public`, `anon`, and `authenticated`,
  and granted access only to `service_role`. The two RPCs are similarly
  server-only: `killgate_deep_research_run_create` is idempotent by run ID and
  `killgate_deep_research_run_checkpoint` uses revision fencing.
- Added server-key-only create, checkpoint, and authenticated resume loading in
  `app/services/deep_research.py`. The loader filters by both run ID and user
  ID, reconstructs the typed run envelope, and fails closed on malformed rows.
- Added a bounded `execute_research_run` orchestration seam. It advances only
  through the fixed planner/retrieval/extraction/synthesis/evaluation stages,
  checkpoints before and after each handler, resumes from the persisted status,
  and exposes idempotent reserve/refund/commit hooks for the existing wallet
  layer without importing or replacing wallet policy.
- Extended `scripts/check_supabase_schema.py` and its tests to probe the new
  table/RPC boundary without mutating data.
- The implementation deliberately does not expose the table through the
  customer Data API or put a provider key in the browser. This aligns with
  Supabase's current public-schema exposure change, which requires explicit
  Data API exposure for new tables ([changelog](https://supabase.com/changelog)).

## Phase 3 — bounded retrieval/security/cache (local implementation)

- Added `app/services/retrieval.py` with an injectable, provider-neutral HTTP
  retrieval boundary. It canonicalizes URLs, rejects credentials, non-HTTP(S)
  schemes, non-standard ports, localhost/private/link-local/multicast/reserved
  destinations, and revalidates every redirect target.
- Retrieval is bounded by timeout, redirect count, response bytes, and extracted
  text size. Only HTML, plain text, and JSON responses are accepted; scripts and
  styles are excluded from extracted text.
- Added a process-local TTL cache and a `RetrievedSource.provenance()` adapter
  that records a content SHA-256 and access timestamp for the durable evidence
  model. No provider credentials or arbitrary tool execution are involved.
- Added tests for SSRF protections, redirect validation, content limits,
  extraction, caching, and provenance.

## Phase 4 — deterministic planner contract (local implementation)

- Added `app/services/research_planner.py` with application-owned claim
  decomposition and a six-query bounded research plan covering problem voice,
  workarounds, alternatives/pricing, spend, negative evidence, and community
  voice.
- The planner verifies that the supplied hypothesis still matches the locked
  run fingerprint before producing a plan, so it cannot silently change the
  commercial contract. It emits load-bearing claim metadata, evidence
  categories, contradiction targets, and technical questions for later model
  enrichment.
- This is intentionally deterministic scaffolding; no OpenAI request is made
  and no model output can change budgets or validation gates.

## Phase 5 — competitor and pricing normalization (local implementation)

- Added typed `CompetitorProfile`, `CompetitorType`, and
  `PricingObservation` records in `app/models/market_research.py`.
- Added deterministic competitor identity normalization and observed-price
  parsing in `app/services/market_research.py`. Currency remains explicit;
  annual prices are normalized to monthly amounts only within the same
  currency, and contact-sales/unobserved prices remain unknown.
- Added tests for direct/substitute identity records, source deduplication,
  monthly/annual/one-time pricing, and no-inference behavior.

## Phase 6 — customer-voice deduplication (local implementation)

- Added typed `VoiceObservation` records with source, community, author,
  theme, sentiment, and content-fingerprint fields.
- Added quote normalization/deduplication and independence grouping by
  community/domain plus author key. Repeated text is collapsed without
  erasing the first source's provenance; counts are not treated as independent
  voices unless their groups differ.
- Added focused tests for repeated observations, content fingerprints, and
  independence counts.

## Phase 6/7 foundation — evidence normalization (local implementation)

- Customer-voice records now carry deterministic normalized-content hashes and
  independence groups, which are prerequisites for contradiction and
  corroboration scoring.
- Competitor and pricing records remain separate from customer voice so a
  vendor claim, pricing page, and observed buyer statement cannot be counted as
  interchangeable evidence.
- Added `EvidenceLink` and deterministic evidence-matrix helpers. Claim
  coverage, challenging evidence, and corroboration now count distinct source
  families rather than repeated URLs; unknown claim links are ignored and
  unresolved claims remain explicit gaps.
- Added contradiction summaries that surface claims with both supporting and
  challenging sources for explicit falsification review, preserving whether
  the claim is load-bearing.
- Added `GapFillController` and claim-specific gap-fill query generation. The
  controller reserves searches through the existing cost ledger and stops on
  complete coverage, soft/hard cost limits, search ceilings, elapsed-time
  limits, or repeated rounds with no new sources.
- Extended `readiness_report()` with opt-in Deep Research budget validation:
  enabled deployments must configure bounded model/search ceilings and a hard
  cost limit above the soft limit; development enablement is surfaced as a
  warning rather than silently treated as production-ready.
- Added typed `DeepResearchReport` assembly and rerun-delta helpers. Reports
  preserve known claims, unresolved gaps, contradictions, source IDs, and the
  stopping reason; an unsupported model `RESEARCH_PASS` is downgraded to
  `INSUFFICIENT_EVIDENCE` at report assembly time. Reruns explicitly distinguish
  changed evidence/contract/hypothesis from a changed answer alone.
- Added the feature-flagged `deep_research_pipeline.py` bridge and connected it
  to `/v/{venture_id}/run`. With `DEEP_RESEARCH_ENABLED=1`, the existing
  synchronous research provider now runs inside the durable plan/retrieve/
  extract/synthesize/evaluate/completed envelope; with the flag off, the
  legacy route is unchanged. Wallet debit/refund and validation decisions stay
  in their existing layers.
- Added the non-secret `DEEP_RESEARCH_*` budget entries to `.env.example` so
  deployments can opt in explicitly and readiness can validate the same names.
- Added route-level coverage proving the feature flag selects the durable bridge
  and preserves the legacy provider result/redirect behavior.
- Added a dedicated authenticated `/v/{venture_id}/deep-research.json` export
  and included the durable report in the existing attested packet without
  weakening ownership checks or exposing server credentials.
- Pivot creation now carries the parent Deep Research run ID into the new
  venture-family member, allowing later rerun reports to identify their prior
  snapshot without rewriting the parent evidence.
- Terminal checkpoint writes are now rejected by the migration RPC, making a
  completed/failed/cancelled run immutable against delayed worker retries.
- The legacy provider bridge records its observable search/model calls and
  token telemetry in the durable cost ledger before report assembly.
- Added the append-only `deep_research_snapshots` export surface. Completed
  checkpoint writes copy the run's locked fingerprints, lineage, plan,
  evidence, result, cost, and report once; the authenticated report endpoint
  prefers this snapshot while retaining a rollout-safe venture-state fallback.
- Extended the non-mutating Supabase schema probe and anonymous-access checks
  to cover the snapshot table.
- Added application-owned model routing for Deep Research stages: Luna is the
  default for planning, extraction, contradiction work, and critique; Terra is
  the default final-synthesis model; Sol is explicitly opt-in. Deep mode now
  sets an explicit Responses `max_tool_calls` ceiling and readiness validates
  the route/ceiling without exposing credentials.
- Split the legacy provider seam into explicit discovery and synthesis
  functions. The feature-flagged pipeline now checkpoints discovery-derived
  sources during extraction before invoking the locked synthesis/evaluator
  path; legacy provider overrides remain compatible for rollout tests.
- Deep mode routes final provider synthesis to Terra by default, records Luna
  as the deterministic planner route, and passes an explicit bounded
  `max_tool_calls` value to Responses; Sol remains disabled unless explicitly
  enabled by an administrator.
- Added provider-neutral `SearchProvider`, `SourceRetriever`, and
  `EvidenceExtractor` seams with adapters for the existing live search,
  SSRF-safe HTTP retrieval, and normalized provenance-linked text extraction.
- Added `scripts/benchmark_deep_research.py`, a provider-free contract
  benchmark that measures fixture latency, ledger spend, verdict output, and
  citation-integrity invariants without making network calls or reading keys.
  The current fixture run reports two cases, zero provider calls, zero spend,
  and intact citation links.
- Reconciled the stronger scorecard thresholds with the Deep path: the locked
  contract now records 30 observed-user items, 15 independent voices, and 3
  communities as targets, and a model PASS is downgraded when those targets
  are not met. The legacy low-cost pre-gate remains unchanged.

## Remaining risk / next phase

- The migration has not been applied to or verified against the production
  Supabase project in this handoff. The local checkout has no linked Supabase
  project/configured database, so the schema probe remains a fixture-tested
  release check until production credentials are available.
- The durable run store, planner envelope, checkpoint executor, report export,
  and venture-family lineage are now wired to the web request path behind the
  existing quota, wallet, validation, and audit boundaries. The bridge still
  delegates provider work to the existing research engine; provider-backed
  stage splitting, a separately materialized final-snapshot export, and live
  production verification remain before this can be called a complete Deep
  Research launch. Terminal rows are revision-fenced and rejected for later
  mutation, and reruns compare against an authenticated parent snapshot.
- Production Secret Manager/Cloud Run configuration remains unchanged because
  local `gcloud` authentication returned `invalid_grant`; restore provider
  authentication before adding a new secret version or deploying.
- The first Platform key creation was acknowledged without a returned local
  handoff payload; a same-name encrypted handoff retry was written to the
  ignored local env file. Review and revoke the unused first key in OpenAI
  Platform after access is available.

## Phase 7/8 continuation — qualified evidence and durable worker ownership (local)

- Discovery records are now distinct from evidence records. The pipeline stores
  classified discovery metadata as `discovery_sources`, reserves each direct
  page fetch against the run ledger before retrieval, and promotes only safely
  retrieved/extracted content into `QUALIFIED` sources. Failed/inaccessible
  retrieval never becomes supporting or negative evidence.
- Deep Research PASS is now downgraded when no source completed qualification
  or when no material conclusion links to a qualified source. Provider-returned
  URLs are no longer inserted into the evidence graph merely because a model
  named them.
- Added source lifecycle and publisher-commercial-interest contracts, including
  conservative user-generated and governmental/regulatory classification. The
  source lifecycle remains provenance-first: discovery, retrieved, extracted,
  verified/qualified, or inaccessible.
- Added additive migration
  `supabase/migrations/20260901074500_deep_research_worker_ownership.sql`.
  It adds service-role-only run claim/release RPCs, bounded worker leases and
  attempt counts, and a partial one-active-run-per-venture constraint. It has
  not been applied anywhere.
- Added server-side worker lease helpers, owner-safe
  `/v/{venture_id}/deep-research-status.json`, persisted locked run inputs for
  future worker recovery, and readiness requirements for explicit inline versus
  Cloud Tasks worker mode. No Cloud Tasks resource, Cloud Run revision, secret,
  provider call, or production configuration was changed.
- Expanded the provider-free benchmark to five deterministic cases (narrow
  problem, technical uncertainty, incumbent bundle contradiction, unknown
  pricing, and customer-voice shortfall), reporting qualified-source depth in
  addition to citation integrity and cost.

### Verification

- Focused lifecycle/provider/pipeline/schema tests: `26 passed`.
- Report/benchmark/release-focused tests: `37 passed, 1 warning`.
- Provider-free benchmark: five cases, 10 qualified fixture sources, zero
  provider calls, zero estimated cost, and intact citation integrity.

### Remaining risk / next phase

- The durable worker lease schema and RPCs need production application and
  catalog/privilege verification once Supabase credentials are restored.
- Cloud Tasks dispatch and authenticated worker execution require production
  Google authentication and a server-side state-loading path; local code now
  preserves the locked inputs and exposes status but does not enqueue external
  work.
- The staged extractor/synthesizer still needs the deferred live-provider
  acceptance path. No API key was read or used during this local continuation.

### Final local verification for this continuation

- Full suite completed in two timeout-safe groups: `160 passed` and
  `129 passed` (`289 passed` total), each with only the pre-existing FastAPI
  TestClient/httpx deprecation warning.
- Changed Deep Research files pass Ruff; `compileall` and `pip check` pass.
- Repository-wide Ruff currently reports 174 pre-existing style/modernization
  findings outside this scoped change. They were not mechanically rewritten
  because that would be unrelated cleanup rather than Deep Research work.

## Local completion pass — durable exports, worker contract, and application polish

- Deep Research runs and immutable snapshots now carry structured competitor
  profiles and observed pricing records through checkpoint persistence and the
  report export. The report exposes competitor IDs and observed pricing without
  inventing missing values.
- Added provider-free worker dispatch contracts in
  `app/services/deep_research_worker.py`. Inline execution validates only a
  minimal run/user job. Cloud Tasks mode validates non-secret queue/URL/audience
  inputs and produces an intent only; it does not create an external task.
- Applied safe Ruff mechanical fixes across `app`, `tests`, and `scripts`, then
  corrected the remaining lint findings without changing the application’s
  validation, billing, or security policy. Repository-wide Ruff is now clean.

### Verification

- Full suite in two groups: `162 passed` plus `130 passed` (`292 passed` total),
  each with only the known third-party TestClient/httpx deprecation warning.
- `ruff check app tests scripts`, `compileall`, and `pip check` all pass.
- No provider request, API key access, secret operation, production migration,
  external task submission, or deployment occurred.
