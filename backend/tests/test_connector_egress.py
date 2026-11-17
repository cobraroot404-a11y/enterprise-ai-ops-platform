"""SSRF / outbound-destination security for tenant-configurable connectors.

Unit tests drive EgressPolicy with a fake resolver (no network); connector tests use httpx.MockTransport to
prove what is (not) sent; API and worker tests prove enforcement on every execution path: connector creation,
enrichment lookups, background submission, and retries. Positive tests confirm approved mock connectors work.
"""
import httpx
import pytest
from app.connectors import egress
from app.connectors.egress import EgressDenied, EgressPolicy, normalize_origin
from app.connectors.http import PERMANENT, ConnectorError, HttpConnector
from app.workflows import worker
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from support import login, onboard_meridian

PUBLIC = "93.184.216.34"


def fake(mapping):
    calls = []

    def resolver(host, port):
        calls.append(host)
        return list(mapping[host])

    resolver.calls = calls
    return resolver


# ---- URL hygiene and alternative representations ----------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "ftp://partner.example.test", "file:///etc/passwd", "gopher://partner.example.test", "javascript:alert(1)",
    "https://user:pw@partner.example.test", "https://partner.example.test@evil.example.org",
    "https://partner.example.test#frag", "https://partner.example.test/?q=1", "https://partner.example.test\\@evil.test",
    "https://partner.example.test /x", "https://partner.example.test:99999",
    # alternative IP representations that parsers or resolvers may treat as loopback / private
    "http://2130706433", "http://0x7f000001", "http://0177.0.0.1", "http://127.1", "http://0x7f.0.0.1",
    "http://[::ffff:7f00:1]%25eth0", "http://１２７.0.0.1", "http://10.1", "http://0300.0250.0.1",
])
def test_unsafe_or_alternative_urls_are_rejected(url):
    with pytest.raises(EgressDenied):
        normalize_origin(url)


# ---- address policy: even an allow-listed origin cannot reach unsafe addresses -----------------------------------------
UNSAFE_LITERALS = [
    "http://127.0.0.1", "http://127.8.8.8", "http://10.0.0.5", "http://172.16.4.4", "http://192.168.1.1",
    "http://169.254.169.254", "http://169.254.170.2", "http://100.100.100.200", "http://0.0.0.0", "http://224.0.0.1",
    "http://240.0.0.1", "http://100.64.0.1", "http://[::1]", "http://[fd00:ec2::254]", "http://[fd00::1]",
    "http://[fe80::1]", "http://[ff02::1]", "http://[::ffff:127.0.0.1]", "http://[::ffff:10.0.0.1]", "http://[::]",
]


@pytest.mark.parametrize("origin", UNSAFE_LITERALS)
def test_allow_listing_an_unsafe_address_still_does_not_permit_it(origin):
    policy = EgressPolicy(allowlist={"*": [origin]})  # a misconfigured production allow-list
    with pytest.raises(EgressDenied):
        policy.authorize(origin, "acme")


@pytest.mark.parametrize("answer", ["169.254.169.254", "10.0.0.8", "127.0.0.1", "::1", "fe80::1", "::ffff:10.0.0.8",
                                    "fd00:ec2::254"])
def test_names_that_resolve_to_unsafe_addresses_are_refused(answer):
    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]}, resolver=fake({"partner.example.test": [answer]}))
    with pytest.raises(EgressDenied, match="disallowed destination"):
        policy.authorize("https://partner.example.test", "acme")


def test_public_allow_listed_destination_is_authorized_and_pinned():
    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]}, resolver=fake({"partner.example.test": [PUBLIC]}))
    target = policy.authorize("https://partner.example.test/api", "acme")
    assert (target.scheme, target.host, target.port, target.address) == ("https", "partner.example.test", 443, PUBLIC)


def test_ipv6_public_literal_is_accepted_when_allow_listed():
    policy = EgressPolicy(allowlist={"*": ["https://[2606:4700:4700::1111]"]})
    assert policy.authorize("https://[2606:4700:4700::1111]", "acme").address == "2606:4700:4700::1111"


# ---- allow-list: unauthorized domains, ports, schemes, tenant scoping -------------------------------------------------------
def test_unlisted_domains_ports_and_schemes_are_denied_and_scoping_is_per_tenant():
    policy = EgressPolicy(allowlist={"meridian": ["https://crm.partner.example.test"], "*": ["https://shared.example.test"]},
                          resolver=fake({"crm.partner.example.test": [PUBLIC], "shared.example.test": [PUBLIC],
                                         "evil.example.org": [PUBLIC]}))
    assert policy.authorize("https://crm.partner.example.test", "meridian")
    assert policy.authorize("https://shared.example.test", "apex") and policy.authorize("https://shared.example.test", None)
    for url, tenant in (("https://evil.example.org", "meridian"),           # unauthorized public domain
                        ("https://crm.partner.example.test", "apex"),       # another tenant's destination
                        ("https://crm.partner.example.test", None),
                        ("https://crm.partner.example.test:8443", "meridian"),  # unexpected port
                        ("http://crm.partner.example.test", "meridian"),    # downgraded scheme
                        ("https://CRM.partner.example.test.evil.org", "meridian"),  # look-alike suffix
                        ("https://sub.crm.partner.example.test", "meridian")):
        with pytest.raises(EgressDenied):
            policy.authorize(url, tenant)


def test_default_policy_denies_everything_and_production_rejects_dev_exceptions():
    empty = EgressPolicy()
    with pytest.raises(EgressDenied):
        empty.authorize("https://partner.example.test", "acme")
    with pytest.raises(ValueError):
        EgressPolicy(dev_mocks={"*": ["http://127.0.0.1:8101"]}, production=True)
    prod = EgressPolicy(production=True)
    with pytest.raises(ValueError):
        prod.add_dev_mock("*", "http://127.0.0.1:8101")


# ---- development-only mock exceptions are narrow -------------------------------------------------------------------------
def test_dev_mock_exception_allows_only_that_origin_and_only_loopback():
    policy = EgressPolicy(dev_mocks={"meridian": ["http://127.0.0.1:8105"]},
                          resolver=fake({"mock.test": ["10.0.0.9"]}))
    assert policy.authorize("http://127.0.0.1:8105", "meridian").address == "127.0.0.1"
    for url, tenant in (("http://127.0.0.1:8106", "meridian"),     # other port on loopback
                        ("http://127.0.0.1:8105", "apex"),          # other tenant
                        ("http://127.0.0.2:8105", "meridian"),      # other loopback address
                        ("http://localhost:8105", "meridian"),
                        ("http://10.0.0.9:8105", "meridian")):      # private network is never unlocked
        with pytest.raises(EgressDenied):
            policy.authorize(url, tenant)
    named = EgressPolicy(dev_mocks={"*": ["http://mock.test:8105"]}, resolver=fake({"mock.test": ["10.0.0.9"]}))
    with pytest.raises(EgressDenied):  # a dev mock may resolve to loopback, never to the private network
        named.authorize("http://mock.test:8105", "meridian")


def test_loopback_is_not_reachable_through_the_production_allow_list():
    policy = EgressPolicy(allowlist={"*": ["http://127.0.0.1:8105"]})
    with pytest.raises(EgressDenied):
        policy.authorize("http://127.0.0.1:8105", "meridian")


# ---- DNS rebinding / time-of-check-time-of-use ---------------------------------------------------------------------------
def test_mixed_dns_answer_is_refused_and_connection_is_pinned_to_the_validated_address():
    mixed = EgressPolicy(allowlist={"*": ["https://partner.example.test"]},
                         resolver=fake({"partner.example.test": [PUBLIC, "169.254.169.254"]}))
    with pytest.raises(EgressDenied):
        mixed.authorize("https://partner.example.test", "acme")

    answers = iter([[PUBLIC], ["169.254.169.254"], ["10.0.0.1"]])  # the name "rebinds" after the first lookup
    calls = []

    def rebinding(host, port):
        calls.append(host)
        return next(answers)

    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]}, resolver=rebinding)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    conn = HttpConnector("https://partner.example.test", api_key="k", tenant_slug="acme", policy=policy,
                         transport=httpx.MockTransport(handler))
    assert conn.request("GET", "/x") == {"ok": True}
    assert len(calls) == 1  # resolved once; the connection cannot be redirected by a later DNS answer
    assert seen[0].url.host == PUBLIC and seen[0].headers["host"] == "partner.example.test"
    assert seen[0].extensions.get("sni_hostname") == "partner.example.test"  # TLS name check keeps the real name
    # The next request re-validates from scratch: the rebound answer is now refused and nothing is sent.
    with pytest.raises(ConnectorError) as exc:
        conn.request("GET", "/x")
    assert exc.value.kind == PERMANENT and len(seen) == 1


# ---- what is (not) sent ---------------------------------------------------------------------------------------------------
def test_denied_destination_sends_nothing_so_credentials_cannot_leak():
    sent = []
    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]}, resolver=fake({"evil.example.org": [PUBLIC]}))
    conn = HttpConnector("https://evil.example.org", api_key="super-secret", tenant_slug="acme", policy=policy,
                         transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={})))
    with pytest.raises(ConnectorError) as exc:
        conn.request("POST", "/tickets", json={"a": 1}, headers={"Idempotency-Key": "k"})
    assert exc.value.kind == PERMANENT and sent == []


def test_redirects_are_never_followed_and_credentials_are_not_forwarded():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]},
                          resolver=fake({"partner.example.test": [PUBLIC]}))
    conn = HttpConnector("https://partner.example.test", api_key="super-secret", tenant_slug="acme", policy=policy,
                         transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectorError) as exc:
        conn.request("GET", "/x")
    assert exc.value.kind == PERMANENT and "redirect" in str(exc.value) and len(seen) == 1
    assert all("169.254" not in str(r.url) for r in seen)


def test_response_size_is_bounded():
    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]},
                          resolver=fake({"partner.example.test": [PUBLIC]}))
    conn = HttpConnector("https://partner.example.test", tenant_slug="acme", policy=policy,
                         transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024))))
    with pytest.raises(ConnectorError, match="size limit"):
        conn.request("GET", "/x")


def test_connection_and_read_timeouts_are_bounded():
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={})

    policy = EgressPolicy(allowlist={"*": ["https://partner.example.test"]},
                          resolver=fake({"partner.example.test": [PUBLIC]}))
    HttpConnector("https://partner.example.test", timeout=30, tenant_slug="acme", policy=policy,
                  transport=httpx.MockTransport(handler)).request("GET", "/x")
    assert seen[0]["connect"] <= 3.0 and seen[0]["read"] == 30


# ---- API: unauthorized connector configuration changes -----------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:1", "http://localhost:8101", "http://[::1]:8101", "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5:8101", "http://192.168.0.10", "http://0x7f000001:8101", "http://2130706433:8101",
    "http://127.1:8101", "https://evil.example.org", "http://metadata.google.internal", "http://user:pw@127.0.0.1:8101",
    "http://[::ffff:127.0.0.1]:8101",
])
def test_tenant_admin_cannot_configure_unauthorized_destinations(client, apex, url):
    admin = login(client, apex, "tenant_admin")
    for kind in ("ticketing", "fleet", "rest"):
        resp = client.post("/api/v1/connectors", headers=admin,
                           json={"kind": kind, "name": f"x-{kind}", "base_url": url})
        assert resp.status_code == 422, (url, resp.text)
        if "error" in resp.json():
            assert resp.json()["error"]["code"] in ("connector_destination_not_allowed", "validation_error")
    assert {c["name"] for c in client.get("/api/v1/connectors", headers=admin).json()["items"]} \
        == {"mock-ticketing", "mock-inventory"}  # nothing was saved


def test_non_admins_cannot_configure_connectors_even_for_approved_destinations(client, apex, ticketing):
    for role in ("support_engineer", "maintenance_supervisor", "read_only_auditor"):
        resp = client.post("/api/v1/connectors", headers=login(client, apex, role),
                           json={"kind": "rest", "name": "x-rest", "base_url": ticketing.url})
        assert resp.status_code == 403


def test_approved_mock_destination_can_still_be_configured(client, apex, ticketing):
    resp = client.post("/api/v1/connectors", headers=login(client, apex, "tenant_admin"),
                       json={"kind": "rest", "name": "extra-mock", "base_url": ticketing.url})
    assert resp.status_code == 201


# ---- execution paths: worker, retries, enrichment, per-tenant scoping ----------------------------------------------------------
@pytest.fixture()
def restore_policy(_egress_policy):
    yield
    egress.set_policy(_egress_policy)


def _approved_ticket(client, tenant, report):
    eng, sup = login(client, tenant, "support_engineer"), login(client, tenant, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report}).json()
    if inc["review_status"] == "needs_review":
        client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup,
                    json={"decision": "accept", "comment": "Reviewed by supervisor."})
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    assert client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                       json={"decision": "approved"}).status_code == 200
    return ticket, eng


def test_worker_never_sends_to_a_destination_that_is_not_authorized_for_the_tenant(
        client, apex_loaded, owner_engine, worker_db, ticketing, servicedesk_server, restore_policy):
    """A connector row that points at ANOTHER tenant's approved system (or any unauthorized place) is refused at
    connection time, even though the origin is on the server allow-list for a different tenant."""
    scoped = EgressPolicy(dev_mocks={apex_loaded.slug: [ticketing.url], "meridian-only": [servicedesk_server.url]})
    egress.set_policy(scoped)
    ticket, eng = _approved_ticket(client, apex_loaded, "Pump P-101 shows abnormal vibration at 8.4 mm/s, grinding noise.")
    with owner_engine.begin() as conn:  # simulate a misconfigured / maliciously edited connector row
        conn.execute(text("UPDATE connectors SET base_url = :u, config = '{}'::jsonb "
                          "WHERE tenant_id = :t AND kind = 'ticketing'"), {"u": servicedesk_server.url, "t": apex_loaded.id})
    assert worker.drain(worker_db, worker.WorkerConfig(backoff_base=0)) == ["failed_permanent"]
    assert servicedesk_server.state.requests == 0 and ticketing.state.requests == 0
    final = client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()
    assert final["state"] == "FAILED" and "destination not permitted" in final["last_error"]


def test_retry_after_a_transient_failure_is_revalidated_and_blocked_if_the_destination_changed(
        client, apex_loaded, owner_engine, worker_db, ticketing, restore_policy):
    httpx.post(f"{ticketing.url}/admin/failure", json={"mode": "503", "count": 1}, headers={"X-API-Key": "test-ticketing-key"})
    ticket, eng = _approved_ticket(client, apex_loaded, "Pump P-101 shows abnormal vibration at 8.4 mm/s, grinding noise.")
    cfg = worker.WorkerConfig(backoff_base=0, backoff_cap=0)
    assert worker.process_one(worker_db, cfg) == "retry_scheduled"  # first attempt reached the approved mock and failed
    requests_before = ticketing.state.requests
    with owner_engine.begin() as conn:  # destination changes between attempts (e.g. cloud metadata)
        conn.execute(text("UPDATE connectors SET base_url = 'http://169.254.169.254' "
                          "WHERE tenant_id = :t AND kind = 'ticketing'"), {"t": apex_loaded.id})
    assert worker.drain(worker_db, cfg) == ["failed_permanent"]
    assert ticketing.state.requests == requests_before
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()["state"] == "FAILED"


def test_enrichment_lookups_are_policy_checked_too(client, owner_engine, servicedesk_server, fleet_server, crm_server):
    meridian = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server, "egress")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE connectors SET base_url = 'http://169.254.169.254' "
                          "WHERE tenant_id = :t AND kind = 'fleet'"), {"t": meridian.id})
    fleet_server.app.state.requests.clear()
    eng = login(client, meridian, "support_engineer")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={
        "report_text": "Vehicle VH-2101 shows low brake pressure of 52 psi."}).json()
    assert any("Fleet telematics lookup failed (permanent)" in n for n in inc["notes"])
    assert fleet_server.app.state.requests == []  # nothing was contacted
    assert any("Harbor Fresh Foods" in n for n in inc["notes"])  # the approved CRM mock still works


def test_per_tenant_scoping_blocks_cross_tenant_destinations_at_configuration_time(
        client, owner_engine, apex, servicedesk_server, fleet_server, crm_server, restore_policy):
    meridian_slug_policy = EgressPolicy()
    egress.set_policy(meridian_slug_policy)
    for origin in (servicedesk_server.url, fleet_server.url, crm_server.url):
        meridian_slug_policy.add_dev_mock("meridian-*-placeholder", origin)  # not matching any real slug
    # Nothing is authorized for the Apex tenant, so even a "real" mock URL is refused for it.
    resp = client.post("/api/v1/connectors", headers=login(client, apex, "tenant_admin"),
                       json={"kind": "ticketing", "name": "to-meridian", "base_url": servicedesk_server.url})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "connector_destination_not_allowed"
    meridian_slug_policy.add_dev_mock(apex.slug, servicedesk_server.url)  # explicit server-side authorization
    ok = client.post("/api/v1/connectors", headers=login(client, apex, "tenant_admin"),
                     json={"kind": "ticketing", "name": "to-servicedesk", "base_url": servicedesk_server.url})
    assert ok.status_code == 201


def test_approved_mock_connectors_still_function_end_to_end(client, apex_loaded, worker_db, ticketing):
    ticket, eng = _approved_ticket(client, apex_loaded, "Pump P-101 shows abnormal vibration at 8.4 mm/s, grinding noise.")
    assert worker.drain(worker_db) == ["submitted"]
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()["external_ticket_id"].startswith("MNT-")


def test_tenant_slug_lookup_works_for_the_worker_role_without_table_access(worker_db, apex):
    with worker_db.session() as s:
        assert egress.tenant_slug(s, apex.id) == apex.slug
        with pytest.raises(DBAPIError):
            s.execute(text("SELECT slug FROM tenants"))


def test_no_api_or_connector_config_can_modify_the_server_side_allow_list(client, apex, ticketing, restore_policy):
    paths = " ".join(client.app.openapi()["paths"])
    assert "egress" not in paths and "allowlist" not in paths and "allow-list" not in paths
    admin = login(client, apex, "tenant_admin")
    sneaky = {"allowed_origins": ["https://evil.example.org"], "egress_allowlist": {"*": ["https://evil.example.org"]},
              "allow": "*"}
    created = client.post("/api/v1/connectors", headers=admin, json={
        "kind": "rest", "name": "sneaky-config", "base_url": ticketing.url, "config": sneaky})
    assert created.status_code == 201  # accepted as inert data for an approved destination...
    for url in ("https://evil.example.org", "http://169.254.169.254"):  # ...but it widens nothing
        rejected = client.post("/api/v1/connectors", headers=admin, json={
            "kind": "rest", "name": "evil", "base_url": url, "config": sneaky})
        assert rejected.status_code == 422
    policy = egress.get_policy()
    with pytest.raises(EgressDenied):
        policy.authorize("https://evil.example.org", apex.slug)
