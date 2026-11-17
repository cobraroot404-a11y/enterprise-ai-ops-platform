# Connector outbound-destination security (SSRF)

Tenant administrators may create connectors (`POST /api/v1/connectors`), so the platform makes server-side HTTP
requests to addresses a tenant influences. This is the only tenant-reachable outbound path (the Ollama client uses a
fixed server-side setting). The destination policy lives in `backend/app/connectors/egress.py`, is configured only by
the **server** environment, and is enforced on **every request**, not only when a connector is saved.

## Controls (all in `egress.py` unless noted)
| Requirement | Control |
|---|---|
| Admins cannot override restrictions | The allow-list comes from `EGRESS_ALLOWLIST` (server env). No tenant-writable field can add, widen or bypass it; connector `config` is validated and never consulted for destinations |
| Explicit allow-lists | `{"<tenant slug or *>": ["https://origin", ...]}`: origins (`scheme://host:port`, default ports made explicit) scoped **per tenant**, so one tenant cannot target another tenant's approved system. The default policy denies everything |
| Schemes, credentials, ports | Only `http`/`https`; userinfo, fragments, query strings, whitespace, control characters, backslashes, zone ids and non-ASCII hosts are rejected; a port that is not on the allow-list is a different origin and is denied |
| Unsafe destinations | After resolving, **every** address must be globally routable: loopback, private, link-local, multicast, reserved, unspecified, CGNAT and cloud-metadata addresses (`169.254.169.254`, `169.254.170.2`, `100.100.100.200`, `fd00:ec2::254`, ...) are refused. IPv6 is validated the same way; IPv4-mapped IPv6 (`::ffff:127.0.0.1`) is unwrapped first. An allow-listed origin that resolves to an unsafe address is still refused |
| Alternative IP forms | Hosts that look numeric must be canonical dotted-quad or a bracketed IPv6 literal: `2130706433`, `0x7f000001`, `0177.0.0.1`, `127.1`, fullwidth digits and similar are rejected. (Side effect: a DNS name made only of `0-9a-f` and dots, such as `deadbeef.cafe`, is also refused) |
| DNS rebinding / TOCTOU | The name is resolved **once per request**, all answers are validated (a mixed public+private answer is refused), and the connection is made to the **validated IP** (the `Host` header and TLS SNI/verification keep the real name). A later DNS answer cannot influence that connection; the next request re-validates from scratch |
| Connection-time enforcement | `HttpConnector.request` calls `authorize()` before any bytes are sent: for initial calls, **retries** (the worker rebuilds the client on every attempt), background submissions and enrichment lookups. A denied request sends nothing (no credential leaves the process) and is classified permanent, so it is dead-lettered instead of retried |
| Redirects | Never followed; a 3xx response is a permanent error, so no redirect destination (and no `X-API-Key`) is ever used |
| Credentials | The API key is attached only to the validated, pinned origin |
| Timeouts / size | connect timeout at most 3 s, total/read timeout from the caller, response bodies capped at 1 MiB (streamed) |
| Save-time check | `check_config` refuses a connector whose origin is not allowed for the tenant (HTTP 422 `connector_destination_not_allowed`). This is only an early, friendly rejection, not the protection |
| Worker role | The per-tenant scope needs the tenant slug; the worker has no table access, so migration 0006 adds a single-purpose `connector_tenant_slug(uuid)` definer function |

## Development-only mock exception
`EGRESS_DEV_MOCKS` (same JSON shape) authorizes the local mock services (`http://127.0.0.1:8101` to `8105`, per tenant
slug, see `.env.example`). Such an origin may resolve to **loopback only**; it can never unlock a private network, another
port, another loopback address, a name that resolves to a private address, or another tenant's slug. The production
allow-list never honors it, and the policy **refuses to start** (`ValueError`) if `EAOP_ENV=production` and
`EGRESS_DEV_MOCKS` is set. The test-suite registers only its own mock servers through the same mechanism.

## Evidence
`backend/tests/test_connector_egress.py` (79 tests): 20 unsafe or alternative URL forms; 20 unsafe address literals even when
allow-listed; names resolving to metadata, loopback or private addresses (IPv4 and IPv6); unauthorized public domains, ports,
schemes and cross-tenant destinations; dev-mock narrowness and production refusal; DNS rebinding with a single-resolution and
pinned-address proof; nothing sent when denied; redirects refused; response-size and timeout bounds; API rejection of 13
unauthorized `base_url`s for three connector kinds and a 403 for non-admins; the **worker** refusing another tenant's origin and
a metadata address introduced **between retries**; enrichment lookups; and positive tests that approved mock connectors still
work end to end.

## Limitations
- This is application-level enforcement. A real deployment should also apply network egress controls (firewall, proxy or
  gateway) as defence in depth; operators must maintain the allow-list.
- Resolution uses the operating system resolver; the policy trusts it to return the addresses it will connect to.
- A tenant admin still chooses the connector path and non-destination configuration, within the validated schema.
- Allow-listed production origins are added by an operator; there is deliberately no UI for it.

## Operator authorization and network-level enforcement
- **Each approved connector origin must be explicitly authorized by the platform operator in `EGRESS_ALLOWLIST` before a tenant is
  onboarded.** Onboarding a tenant whose connector origins are not authorized fails at the connector step (HTTP 422). Tenant
  administrators cannot add, widen or bypass the allow-list through any API or connector configuration (regression-tested).
- **Application-level protection is not a substitute for network-level egress restrictions in production.** Deploy the API and worker
  hosts behind a firewall, proxy or gateway that independently permits only the authorized destinations. No paid cloud
  infrastructure is provisioned or required by this repository.
- Accepted limitations are tracked in [../deployment/accepted-limitations.md](../deployment/accepted-limitations.md).
