# Killgate Release-Candidate Security Review — August 24, 2026

## Result

No confirmed Critical or High source-level vulnerability was found in the release-candidate review. The live Supabase Security Advisor reports zero findings after the distributed rate-limit and research-quota migrations.

This is a release-candidate security review, not a claim that the final Play-installed AAB has been penetration-tested. The Android wrapper does not exist until the owner supplies the final origin/package/signing values and Bubblewrap builds it.

## Boundaries checked

### Account and tenant isolation

- `ventures` and `subscription_entitlements` remain user-owned under Supabase RLS.
- Anonymous access is revoked.
- Live `request_rate_events` and `play_rtdn_events` are server-only.
- Live `killgate_rate_limit_allow` and `killgate_research_quota_allow` RPC execution is denied to `anon` and `authenticated`; `service_role` is allowed.
- Venture reads/writes include both owner ID filters and user-scoped Supabase JWTs, providing application filtering plus RLS defense in depth.

### Browser/session security

- Access/refresh cookies are HttpOnly, Secure in Supabase production mode, and SameSite=Strict.
- Unsafe same-origin requests reject a mismatched `Origin`, including login/signup before a user session exists. Authenticated Pub/Sub RTDN and the OS/PWA share target are the intentional exceptions.
- CSP denies framing and restricts scripts/styles/connects to self; X-Frame-Options, nosniff, and strict-origin referrer policy are set.
- User-supplied hypotheses, evidence text, account email, source URLs, and messages are HTML-escaped at render boundaries reviewed.

### Google Play billing

- Browser purchase status cannot grant entitlement directly.
- The server-configured Killgate subscription product ID is authoritative; a client-supplied alternate SKU is rejected.
- Purchase tokens are verified against Google Play `purchases.subscriptionsv2.get` before entitlement is persisted.
- Active unacknowledged subscriptions are acknowledged server-side.
- Stored entitlement consumption checks product ID, active state, and expiry again.
- Raw purchase tokens are not persisted; hashes are used for entitlement/RTDN correlation.
- RTDN requires a Google-signed Pub/Sub OIDC token, expected audience/service-account identity, matching Android package, idempotent message ID, and a fresh Play verification before entitlement state changes.

### AI/research trust boundary

- OpenAI uses the Responses API with strict JSON-schema output and `store=false`.
- The model cannot provide authoritative URLs. It may cite only server-numbered DIRECT sources; Killgate attaches the known URL.
- Source titles/snippets are explicitly treated as untrusted data and instructions embedded in source content are ignored.
- The deterministic evaluator can downgrade an LLM PASS; the LLM cannot override the locked validation contract or force GO.
- Production research has both an hourly cap and an atomic rolling-30-day API safety ceiling enforced in Supabase; private beta uses a separate 9-run/14-day allowlist window.

### Secrets and code primitives

A local scan of the release-candidate source found no matches for production-style OpenAI project keys, Supabase secret keys, Google API keys, or private-key PEM blocks. No application use of `eval`, `exec`, `os.system`, `shell=True`, disabled TLS verification, unsafe pickle loading, or unsafe YAML loading was found in the reviewed source.

## Remaining verification gates

1. **Dependency CVE audit:** `pip-audit`/Bandit/Semgrep were not available in the current sandbox and package-registry DNS was unavailable in the previous attempt. Run a dependency audit in CI or the release machine after installing the production dependency set. Do not mark this complete until the exact resolved environment is scanned.
2. **Final AAB scan:** build the real Bubblewrap project with the production identity, then inspect the AAB/APK for secrets, unexpected permissions, PBL version, exported components, and signing identity.
3. **Internal-track dynamic QA:** purchase, restore, cancel, grace, hold, revoke, expire, RTDN, account deletion, cross-account isolation, Digital Asset Links, and crash/logcat verification require a Play-installed internal-test build.
4. **Production monitoring:** Sentry remains optional but recommended; configure alerts without logging credentials, purchase tokens, or full buyer-research payloads.

## Release stop conditions

Do not promote to production if a dependency audit reports an unresolved exploitable High/Critical issue, PBL7 is present in the generated bundle, Digital Asset Links do not verify the Play signing certificate, a cross-account read/write is possible, purchase state can be forged client-side, RTDN accepts unauthenticated pushes, or any production secret is found in web assets/AAB/logs.
