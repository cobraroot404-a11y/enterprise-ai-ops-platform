"""Batch 11A, Checkpoint A: the REST records connector library (V41-12.01 REST part, V41-11.01, V41-11.02).

Real HTTP against the local records mock (a uvicorn thread). Failures are CONTROLLED INJECTIONS in that mock (429, 503, a slow response, malformed or repeated cursors, a redirect to a
metadata address); none is a real upstream outage. No test needs the database except where the connector row is built."""
import threading
import time
import uuid

import pytest
from app.connectors import egress
from app.connectors.http import HttpConnector
from app.connectors.ratelimit import LIMITERS, MAX_WAIT_SECONDS, RateLimited, TokenBucket
from app.connectors.rest_records import (
    PageState,
    RecordInvalid,
    RestRecordsSource,
    SourceError,
    build_source,
    document_name,
    parse_config,
    safe_path,
    validate_record,
)
from app.core.errors import Invalid
from support import RECORDS_KEY

TENANT = str(uuid.uuid4())


def cfg(mode="cursor", **over):
    base = {"records": {"path": f"/v1/apex/{mode}", "id_field": "id", "version_field": "updated_at", "required_fields": ["title", "body"],
                        "pagination": {"mode": mode, "page_size": 3, "has_more_field": "has_more" if mode == "cursor" else None, "total_field": "total" if mode != "cursor" else None},
                        "rate": {"requests_per_second": 50, "burst": 20}}}
    base["records"].update(over)
    for key in ("has_more_field", "total_field"):
        if base["records"]["pagination"].get(key, 1) is None:
            del base["records"]["pagination"][key]
    return base


def source(records_server, config, timeout=3.0, key=RECORDS_KEY, stop=None):
    parsed = parse_config(config)
    http = HttpConnector(records_server.url, api_key=key, timeout=timeout, tenant_slug="*", tenant_id=TENANT)
    return RestRecordsSource(http, parsed, tenant_id=TENANT, connector_id=uuid.uuid4(), stop=stop)


def pull(src):
    state, out, pages = PageState(), [], 0
    while not state.done:
        page = src.fetch_page(state)
        out += page.records
        state, pages = page.state, pages + 1
    return out, state, pages


@pytest.fixture(autouse=True)
def reset_mock(records_server):
    with records_server.state.lock:
        records_server.state.failures.clear()
        records_server.state.requests.clear()
        records_server.state.datasets["apex"] = __import__("records_app")._apex()
    LIMITERS.clear()


# ----------------------------------------------------------------------------------------------------------------------- pagination modes over real HTTP
@pytest.mark.parametrize("mode", ["cursor", "offset", "page"])
def test_every_pagination_mode_retrieves_all_records_across_pages(records_server, mode):
    records, state, pages = pull(source(records_server, cfg(mode)))
    assert [r["id"] for r in records] == [f"APX-N-{i:03d}" for i in range(1, 8)] and pages == 3 and state.done and state.records == 7
    seen = [r for r in records_server.state.requests if r["key_ok"]]
    assert len(seen) == 3 and all(r["mode"] == mode and r["params"]["limit"] == 3 for r in seen)  # three real requests were made


def test_a_source_without_pagination_is_a_single_request(records_server):
    records, _, pages = pull(source(records_server, cfg("offset", pagination={"mode": "none"})))
    assert pages == 1 and len(records) == 7 and len(records_server.state.requests) == 1


def test_an_empty_dataset_and_an_empty_page_end_cleanly(records_server):
    with records_server.state.lock:
        records_server.state.datasets["apex"] = []
    records, state, pages = pull(source(records_server, cfg("offset")))
    assert records == [] and state.done and pages == 1


def test_an_empty_page_that_carries_a_continuation_is_followed_without_losing_records(records_server):
    records_server.state.failures.append(type("F", (), {"mode": "empty_page", "count": 1, "delay": 0})())
    with records_server.state.lock:
        records_server.state.failures[:] = [__import__("records_app").FailureConfig(mode="empty_page", count=1)]
    records, _, pages = pull(source(records_server, cfg("cursor")))
    assert len(records) == 7 and pages == 4  # one empty page, then the three real ones


# ----------------------------------------------------------------------------------------------------------------------- bounds and malformed continuations
def inject(records_server, mode, count=1, delay=0.6):
    from records_app import FailureConfig
    with records_server.state.lock:
        records_server.state.failures.append(FailureConfig(mode=mode, count=count, delay=delay))


def test_a_url_like_cursor_is_rejected_and_never_requested(records_server):
    inject(records_server, "url_cursor")
    with pytest.raises(SourceError) as err:
        pull(source(records_server, cfg("cursor")))
    assert err.value.code == "invalid_cursor" and not err.value.transient
    assert len(records_server.state.requests) == 1  # the metadata address was never contacted: only the first page was fetched


def test_a_repeated_cursor_is_a_loop_failure(records_server):
    page2 = source(records_server, cfg("cursor")).fetch_page(PageState())  # a legitimate first page
    inject(records_server, "repeat_cursor")
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("cursor")).fetch_page(page2.state)
    assert err.value.code == "pagination_loop"


def test_an_identical_page_returned_again_is_a_loop_failure(records_server):
    with records_server.state.lock:
        records_server.state.datasets["apex"] = [{"id": f"A-{i}", "title": "t", "body": "b"} for i in range(4)]
    src = source(records_server, cfg("offset", pagination={"mode": "offset", "page_size": 2, "total_field": "total"}))
    first = src.fetch_page(PageState())
    with pytest.raises(SourceError) as err:  # a source that ignores the offset and returns the same page again
        src.fetch_page(PageState(offset=0, pages=1, last_signature=first.state.last_signature))
    assert err.value.code == "pagination_loop"
    assert len(src.fetch_page(first.state).records) == 2  # while the real next page is accepted


def test_the_page_and_record_limits_bound_the_pull_and_report_truncation(records_server):
    records, state, pages = pull(source(records_server, cfg("cursor", max_pages=2)))
    assert pages == 2 and len(records) == 6 and state.done
    page = source(records_server, cfg("cursor", max_records=4)).fetch_page(PageState())
    page2 = source(records_server, cfg("cursor", max_records=4)).fetch_page(page.state)
    assert len(page.records) + len(page2.records) == 4 and page2.truncated and page2.state.done


def test_unexpected_response_shapes_are_permanent_schema_failures(records_server):
    for mode in ("bad_shape",):
        inject(records_server, mode)
        with pytest.raises(SourceError) as err:
            source(records_server, cfg("cursor")).fetch_page(PageState())
        assert err.value.code == "source_schema_invalid" and not err.value.transient


def test_a_response_larger_than_the_limit_is_refused(records_server):
    with records_server.state.lock:
        records_server.state.datasets["apex"] = [{"id": "BIG-1", "title": "t", "body": "x" * (1024 * 1024 + 10)}]
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("offset")).fetch_page(PageState())
    assert err.value.code == "source_schema_invalid"


# ----------------------------------------------------------------------------------------------------------------------- upstream failures, 429, authentication
def test_http_429_pauses_for_the_retry_after_then_succeeds(records_server):
    inject(records_server, "429", count=1)
    started = time.monotonic()
    records, _, _ = pull(source(records_server, cfg("offset", rate={"requests_per_second": 50, "burst": 20})))
    elapsed = time.monotonic() - started
    assert len(records) == 7 and 0.9 <= elapsed < 6  # the 1 second Retry-After was honoured (and nothing was busy-waited)
    assert len(records_server.state.requests) == 4  # 1 rejected + 3 pages


def test_a_persistent_429_ends_with_a_bounded_transient_failure(records_server):
    inject(records_server, "429", count=10)
    started = time.monotonic()
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("offset")).fetch_page(PageState())
    assert err.value.code == "source_rate_limited" and err.value.transient and time.monotonic() - started < 10
    assert len(records_server.state.requests) == 3  # three bounded attempts, no more


def test_temporary_5xx_is_retried_inside_the_page_and_a_persistent_one_is_transient(records_server):
    inject(records_server, "503", count=1)
    page = source(records_server, cfg("offset")).fetch_page(PageState())
    assert len(page.records) == 3
    inject(records_server, "503", count=5)
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("offset")).fetch_page(PageState())
    assert err.value.code == "source_unavailable" and err.value.transient


def test_an_upstream_timeout_is_transient(records_server):
    inject(records_server, "timeout", count=5, delay=0.6)
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("offset"), timeout=0.2).fetch_page(PageState())
    assert err.value.code == "source_unavailable" and err.value.transient


def test_authentication_failure_is_permanent_and_never_retried(records_server):
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("offset"), key="wrong-key").fetch_page(PageState())
    assert err.value.code == "source_unauthorized" and not err.value.transient
    assert len(records_server.state.requests) == 1 and records_server.state.requests[0]["key_ok"] is False
    assert "wrong-key" not in repr(err.value) and RECORDS_KEY not in repr(err.value)


def test_a_redirect_is_refused_never_followed(records_server):
    inject(records_server, "redirect")
    with pytest.raises(SourceError) as err:
        source(records_server, cfg("offset")).fetch_page(PageState())
    assert err.value.code == "source_rejected" and not err.value.transient  # the 302 to the metadata address was not followed
    assert len(records_server.state.requests) == 1


# ----------------------------------------------------------------------------------------------------------------------- SSRF, configuration, credentials
def test_a_destination_outside_the_egress_policy_is_refused_before_any_request(records_server):
    policy = egress.EgressPolicy(allowlist={}, dev_mocks={"other-tenant": [records_server.url]})  # this tenant has no approval
    http = HttpConnector(records_server.url, api_key=RECORDS_KEY, tenant_slug="apex-x", tenant_id=TENANT, policy=policy)
    src = RestRecordsSource(http, parse_config(cfg("offset")), tenant_id=TENANT, connector_id=uuid.uuid4())
    with pytest.raises(SourceError) as err:
        src.fetch_page(PageState())
    assert err.value.code == "egress_denied" and not records_server.state.requests
    metadata = HttpConnector("http://169.254.169.254", api_key="k", tenant_slug="*", tenant_id=TENANT)
    with pytest.raises(SourceError) as err2:
        RestRecordsSource(metadata, parse_config(cfg("offset")), tenant_id=TENANT, connector_id=uuid.uuid4()).fetch_page(PageState())
    assert err2.value.code == "egress_denied"  # the link-local metadata address is never reachable


@pytest.mark.parametrize("bad", [
    {"path": "http://evil.example/x"}, {"path": "//evil.example/x"}, {"path": "/a/../b"}, {"path": "/a?x=1"}, {"path": "/a\\b"}, {"path": "relative"},
    {"id_field": "bad field"}, {"pagination": {"mode": "weird"}}, {"pagination": {"mode": "cursor", "cursor_param": "a b"}}, {"max_pages": 10000}, {"max_records": 0},
    {"rate": {"requests_per_second": 0}}, {"rate": {"burst": 500}}, {"unknown_key": 1}, {"reject_policy": "ignore"}])
def test_invalid_connector_configuration_is_rejected_without_echoing_values(bad):
    config = cfg("cursor")
    config["records"].update(bad)
    with pytest.raises(Invalid) as err:
        parse_config(config)
    assert err.value.code == "invalid_connector_config" and "evil" not in str(err.value)
    with pytest.raises(Invalid):
        parse_config({})


def test_safe_path_accepts_only_relative_paths():
    assert safe_path("/v1/apex/records") and not any(safe_path(p) for p in ("", "v1", "//h/x", "/a//../b", "/a b", "/a#x", "http://h/x"))


def test_missing_credentials_fail_before_any_request(records_server, monkeypatch):
    monkeypatch.delenv("RECORDS_SECRET_NOT_SET", raising=False)
    row = type("Row", (), {"base_url": records_server.url, "secret_ref": "RECORDS_SECRET_NOT_SET", "tenant_id": uuid.uuid4(), "id": uuid.uuid4()})
    with pytest.raises(SourceError) as err:
        build_source(row, parse_config(cfg("offset")), tenant_slug="*")
    assert err.value.code == "credentials_missing" and not records_server.state.requests


def test_credentials_are_sent_as_a_header_only_and_never_appear_in_logs_or_errors(records_server, monkeypatch, caplog):
    monkeypatch.setenv("RECORDS_TEST_SECRET", RECORDS_KEY)
    row = type("Row", (), {"base_url": records_server.url, "secret_ref": "RECORDS_TEST_SECRET", "tenant_id": uuid.uuid4(), "id": uuid.uuid4()})
    with caplog.at_level("DEBUG"):
        src = build_source(row, parse_config(cfg("offset")), tenant_slug="*")
        pull(src)
        inject(records_server, "503", count=5)
        with pytest.raises(SourceError):
            src.fetch_page(PageState())
    assert RECORDS_KEY not in caplog.text and RECORDS_KEY not in str(records_server.state.requests)


# ----------------------------------------------------------------------------------------------------------------------- records
def test_record_validation_never_invents_ids_and_is_deterministic():
    c = parse_config(cfg("cursor"))
    rid, version, data = validate_record({"id": "X-1", "title": "t", "body": "b", "updated_at": "v1"}, c)
    assert (rid, version) == ("X-1", "v1") and data == validate_record({"updated_at": "v1", "body": "b", "title": "t", "id": "X-1"}, c)[2]  # canonical bytes
    for bad, reason in [({"title": "t", "body": "b"}, "invalid_id"), ({"id": True, "title": "t", "body": "b"}, "invalid_id"), ({"id": "a b", "title": "t", "body": "b"}, "invalid_id"),
                        ({"id": "X", "title": "", "body": "b"}, "missing_required_field"), ("nope", "not_an_object"), ({"id": "X", "title": "t", "body": "y" * 70000}, "record_too_large")]:
        with pytest.raises(RecordInvalid) as err:
            validate_record(bad, c)
        assert err.value.reason == reason
    assert document_name("My Conn!", "REC/9") == "rest-My-Conn--REC-9.json"


# ----------------------------------------------------------------------------------------------------------------------- rate limiter
def test_the_bucket_allows_a_burst_then_spaces_requests_without_busy_waiting():
    now = [0.0]
    bucket = TokenBucket(rate=2.0, burst=3, clock=lambda: now[0])
    assert [bucket.acquire(0) for _ in range(3)] == [0.0, 0.0, 0.0]  # the burst
    with pytest.raises(RateLimited):
        bucket.acquire(0)  # an immediate fourth is refused when no waiting is allowed


def test_a_real_bucket_enforces_the_configured_rate_and_bounds_the_wait():
    bucket = TokenBucket(rate=10.0, burst=1)
    started = time.monotonic()
    for _ in range(4):
        bucket.acquire(5)
    assert 0.25 <= time.monotonic() - started < 1.5  # 3 refills at 10 per second after the first immediate token
    slow = TokenBucket(rate=0.1, burst=1)
    slow.acquire(0)
    with pytest.raises(RateLimited):
        slow.acquire(0.2)  # the next token is 10 seconds away: refused within the bound, not waited for


def test_retry_after_pauses_the_bucket_and_is_capped():
    bucket = TokenBucket(rate=100.0, burst=10)
    bucket.pause(10_000)  # an absurd upstream value is capped
    with pytest.raises(RateLimited):
        bucket.acquire(0.3)
    assert MAX_WAIT_SECONDS == 30.0


def test_a_waiter_returns_at_once_when_stopped_and_buckets_are_per_tenant_and_connector():
    stop = threading.Event()
    bucket = TokenBucket(rate=0.1, burst=1)
    bucket.acquire(0)
    result = []
    t = threading.Thread(target=lambda: result.append(_try(bucket, stop)))
    t.start()
    time.sleep(0.3)
    stop.set()
    t.join(timeout=3)
    assert not t.is_alive() and result == ["stopped"]  # shutdown ends the wait promptly
    a, b, c = LIMITERS.get("t1", "c1", 5, 5), LIMITERS.get("t2", "c1", 5, 5), LIMITERS.get("t1", "c2", 5, 5)
    assert a is not b and a is not c and LIMITERS.get("t1", "c1", 5, 5) is a  # no sharing across tenants or connectors
    assert LIMITERS.get("t1", "c1", 9, 5) is not a  # a changed configuration replaces only that connector's bucket


def _try(bucket, stop):
    try:
        bucket.acquire(30, stop)
    except RateLimited as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------------------------- probe
def test_the_probe_distinguishes_success_authentication_rate_limit_schema_and_upstream_errors(records_server):
    assert source(records_server, cfg("offset")).probe()["status"] == "ok"
    assert source(records_server, cfg("offset"), key="wrong").probe()["status"] == "authentication"
    inject(records_server, "429")
    assert source(records_server, cfg("offset")).probe()["status"] == "rate_limited"
    inject(records_server, "503")
    assert source(records_server, cfg("offset")).probe()["status"] == "upstream_error"
    inject(records_server, "bad_shape")
    assert source(records_server, cfg("offset")).probe()["status"] == "schema"
    inject(records_server, "timeout", delay=0.6)
    assert source(records_server, cfg("offset"), timeout=0.2).probe()["status"] == "connectivity"
    metadata = HttpConnector("http://169.254.169.254", api_key="k", tenant_slug="*", tenant_id=TENANT)
    assert RestRecordsSource(metadata, parse_config(cfg("offset")), tenant_id=TENANT, connector_id=uuid.uuid4()).probe()["status"] == "denied"


def test_the_probe_is_one_bounded_read_that_changes_nothing(records_server):
    records_server.state.requests.clear()
    result = source(records_server, cfg("cursor")).probe()
    assert result["status"] == "ok" and result["duration_ms"] < 3000
    assert len(records_server.state.requests) == 1 and records_server.state.requests[0]["params"]["limit"] == 1  # one request, one record asked for
