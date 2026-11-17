# Accepted deployment limitations

These are known, accepted limits of the current implementation. None of them is hidden by weakening a security control or an
approval gate. Each must be resolved or consciously accepted before a production deployment.

| # | Limitation | Why it matters | Required before production |
|---|---|---|---|
| 1 | **Application-level SSRF protection only.** The egress policy (server-controlled per-tenant allow-list, address checks, DNS pinning, no redirects) runs inside the application. | A compromised application process, a library bug or a resolver difference could still reach unintended networks. | Network-level egress restrictions (firewall, proxy or gateway allow-list) that independently limit what the API and worker hosts may reach. The operator must authorize every connector origin in `EGRESS_ALLOWLIST` **before** a tenant is onboarded; tenant administrators cannot change it. See [connector-egress.md](../security/connector-egress.md). |
| 2 | **Per-process throttling and limits** (login throttle, request-size and concurrency limits). | With several instances the allowance multiplies and counters reset on restart. | Distributed rate limiting or gateway-level enforcement ([rate-limiting-limitations.md](../security/rate-limiting-limitations.md)). |
| 3 | **Two execution paths** (built-in Apex rules, profile-driven Meridian). | Two implementations must be kept consistent by tests. | The planned, regression-tested unification ([apex-meridian-execution-paths.md](../architecture/apex-meridian-execution-paths.md)). |
| 4 | **About 75% of extracted incidents need human review** with the approved 1.5B model. | High operational workload for supervisors. | Unresolved. The review gate is intentionally not relaxed; reducing the load needs better evidence generation and a fresh, approved evaluation. |
| 5 | **Cross-browser and screen-reader validation is incomplete.** Automated axe checks and a keyboard-only walk-through ran in Microsoft Edge only. | Passing axe is not WCAG conformance; automated tools find only a subset of issues. | A manual screen-reader audit (for example NVDA/JAWS/VoiceOver) and a full accessibility review. Chromium and Firefox are **future compatibility targets**; no additional browser was downloaded. |
| 6 | **Comprehensive multi-tenant AI-quality benchmarking is scheduled for Phase 8.** The 95% citation target is NOT MET; Meridian has smoke evidence only. | No AI-quality claim is made beyond the measured Phase 3/4 results on the synthetic dataset. | Phase 8. |
| 7 | **Test credentials** exist only for isolated test stacks (see [test-credentials.md](../security/test-credentials.md)). | They are public by construction. | Production refuses them (see guards); keep real secrets out of source and artifacts (secret scan). |
| 8 | CI has not run; nothing is pushed or published. | Results are local-machine evidence. | Authorized push and CI run (publication is a separate gate). |
