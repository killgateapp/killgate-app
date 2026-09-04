# Killgate changelog

## v1.2.0 — 2026-08-28 — decision-based monetization / durable wallet

- Replaced the retired generic credit / 3-pack / $14.99 refill catalog with: $19.99 Venture Pass (3 same-family passes), $7.99 same-idea Extra Evidence Run, $59.99/month Founder Pro (9/month), and active-Pro-only $14.99 3-run top-up.
- Removed unlimited/30-run subscription semantics. The rolling 30-day control is now a separate 30-run API safety ceiling, not a customer entitlement; private beta uses a 9-run/14-day allowlist window.
- Added family-scoped purchase context so a Venture Pass bought from an idea brief auto-binds and Extra Evidence Runs cannot migrate to unrelated ideas.
- Added durable Supabase wallet RPCs with atomic grant, bind, refill, and debit operations across Cloud Run workers.
- Founder Pro refills once per verified Google Play billing period and never bypasses the wallet.
- One-time Play consumables are consumed server-side only after the durable entitlement grant, allowing safe repurchase.
- Paid research debits now carry refund receipts; provider/state failures restore the undelivered entitlement exactly once instead of burning a purchased run.
- Updated pricing, Play catalog, release, Cloud Run, QA, readiness, and schema-verification documentation/tests.

## 2026-08-28c · v1.1.0

- Replaced the cartoon otter with a steel-gate mark and generated a full brand kit: app icons, maskable icon, favicons, OG image, hero atmosphere, empty arena, brief document, offline room, GO/KILL/PIVOT art, and pass-card art.
- Wired those images into chrome, home empty state, brief, auth, offline, account offers, and venture verdicts.
- Service worker cache bumped to killgate-v1.1.0.

## 2026-08-28b

- Created the four Play catalog IDs in code and docs: killgate_venture_pass, killgate_venture_bundle, killgate_credit, killgate_monthly.
- Enforced three live locks. Archive frees a slot. Pivot children stay on the parent slot.
- Evidence packet export at /v/{id}/packet.json. Approved GO displays as GO BUILD.
- Added PLAY_CONSOLE_CATALOG.md with the exact Console steps.

## 2026-08-28

- Replaced the $14.99/30-run subscription as the only SKU with Venture Pass, 3-pack, credit, and optional monthly refill.
- New ideas open an unpaid research brief. Live sources stay hidden until a credit is consumed.
- Pivot children inherit the parent pass family so a FAIL/PIVOT does not require a second checkout.
- Kept the 26 August engine/PWA slot, packet, and GO_BUILD rules in extras.

# Killgate Runtime Changelog

## v1.0.2 — Release economics + deployment hardening
- Deployed and verified the production distributed rate limiter and atomic rolling research-quota RPC in Supabase; Security Advisor remains clean.
- Added a 30-run rolling-30-day research allowance plus 8/hour burst protection and exposed the allowance in the account UI.
- Added OpenAI model/token usage instrumentation for real per-run cost measurement.
- Added Google Play localized subscription price display via Digital Goods `getDetails()`; no hard-coded checkout price.
- Added production readiness bounds for research quotas and maximum OpenAI output.
- Extended same-origin protection to login/signup mutating requests to reduce session-swapping CSRF risk.
- Added explicit prompt-injection handling for untrusted public-source titles/snippets.
- Added a non-root Docker image and Cloud Run production deployment path.
- Added release-candidate security review and pricing/unit-economics model.
- Made Bubblewrap v1.25.0+/PBL8+ verification a release gate ahead of the August 31, 2026 PBL7 deadline.

## v1.0.1 — Research/API and release hardening
- Migrated optional AI analysis to OpenAI Responses API strict Structured Outputs with `store=false`.
- Made server-known DIRECT source numbers/URLs authoritative rather than accepting model-written URLs.
- Made configured Google Play subscription SKU server-authoritative and fail-closed in entitlement consumption.
- Added production readiness and Supabase schema probes, privacy/support deployment configuration, and release-manifest validation.
- Upgraded service-worker cache generation and tightened operational error handling.

## v1.0.0 — Single-user account + Google Play architecture
- Added authenticated Google Play RTDN / Cloud Pub/Sub lifecycle processing with OIDC identity checks, package validation, message-id deduplication, and server-side re-verification.
- Added a server-only RTDN idempotency ledger that stores SHA-256 purchase-token hashes only.
- Added explicit `requests` runtime dependency required by `google.auth.transport.requests`.
- Added release-template renderer and internal-track Android QA checklist, including the Play App Signing vs upload-key distinction for Digital Asset Links.
- Added Supabase Auth and per-account RLS cloud persistence while retaining local dev mode.
- Added data export and verified account-deletion flow with a deployed Supabase Edge Function.
- Added server-side Google Play subscription verification, acknowledgement, token hashing, entitlement storage, and optional research gating.
- Added TWA Digital Goods / Payment Request checkout and entitlement restore flow.
- Added rate limits, structured logging, optional Sentry integration, and Play/privacy release checklists.
- Removed the inactive LangGraph skeleton and dependencies; deterministic validation remains authoritative.
- Expanded regression suite for account/billing paths.

# Runtime changelog

## v0.9.0 — Locked Validation Contract + evidence-backed GO

- Removed founder-defined default kill criteria from the runtime workflow.
- Generate and lock a system Validation Contract before research, fingerprinted to the active hypothesis.
- Read research thresholds from the locked contract so prompt/docs/code cannot silently drift apart.
- Added structured capture for qualified buyer conversations, pain examples, price reactions, objections, commitments, and payments.
- Deduplicate buyer labels so repeated interviews with the same buyer cannot inflate conversation gates.
- Require amount + payment evidence/reference before a record marked paid can clear the payment gate.
- Persist research evidence, direct-buyer evidence, Level-5 payment evidence, and accepted decisions into an audit trail instead of summary metrics only.
- Added deterministic GO / CONTINUE_VALIDATION / PIVOT / KILL scoring; the LLM may summarize evidence but cannot waive Boolean gates.
- Block manual GO unless research, conversation, pain, price, contradiction-review, and actual-payment gates pass.
- Treat insufficient public-web evidence as a progression blocker, not automatic proof for KILL.
- Clarified that public-source `DIRECT` relevance is not Evidence Level 3 direct-buyer evidence.
- Require a new locked contract when the hypothesis materially changes.

## v0.8.0 — Relevance-gated live research

- Replaced founder-wording heuristics with live, concept-level search queries.
- Added DIRECT / INDIRECT / IRRELEVANT classification before scoring.
- Excluded dictionary/reference pages, generic social profiles, Wikipedia, and isolated keyword matches from validation.
- Added hard PASS gates for source count, domain independence, problem evidence, alternatives/workarounds, budget evidence, and cited supporting claims.
- Added source-quality metrics and DIRECT-source links to the CLI and PWA result views.
- Added regression tests for the QueueCue false-PASS packet and for a properly sourced survivor packet.

## v0.6.0 — Installable PWA foundation

- Added a standards-based web app manifest with complete identity, icons, maskable artwork, narrow/wide screenshots, categories, and install metadata.
- Added a root-scoped service worker, cached application shell, and honest offline recovery page.
- Added useful OS integrations: app shortcuts, share target, `.txt` / `.md` file handlers, `web+killgate:` protocol handling, existing-window launch, Edge side-panel sizing, and Windows title-bar overlay styling.
- Added an in-app install affordance and online/offline status feedback.
- Reworked the mobile and desktop UI around a clearer validation intake and idea pipeline.
- Escaped user, state, and model-generated content before HTML rendering.
- Added CSP and baseline browser security headers.
- Added automated coverage for manifest assets, PWA endpoints, share/protocol intake, security headers, and injection-safe idea rendering.
- Deliberately excluded notes-app registration, OS widgets, and experimental tabbed mode because the runtime does not implement those product behaviors.
