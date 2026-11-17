import base64
import json
import time
import uuid

import jwt
from sqlalchemy import text
from support import PASSWORD, login, make_tenant


def _uid(owner_engine, email):
    with owner_engine.connect() as c:
        return str(c.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar())


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _get(client, token):
    return client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})


def test_alg_none_and_algorithm_confusion_rejected(client, apex, owner_engine, settings):
    uid = _uid(owner_engine, apex.users["tenant_admin"])
    claims = {"sub": uid, "tid": apex.id, "role": "tenant_admin", "exp": int(time.time()) + 600}
    unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."
    hs512 = jwt.encode(claims, settings.jwt_secret, algorithm="HS512")  # right key, wrong algorithm
    for token in (unsigned, hs512):
        assert _get(client, token).status_code == 401


def test_tokens_missing_required_or_malformed_claims_rejected(client, apex, owner_engine, settings):
    uid = _uid(owner_engine, apex.users["tenant_admin"])
    base = {"sub": uid, "tid": apex.id, "role": "tenant_admin", "exp": int(time.time()) + 600}
    cases = {
        "no exp": {k: v for k, v in base.items() if k != "exp"},
        "no sub": {k: v for k, v in base.items() if k != "sub"},
        "sub not a uuid": {**base, "sub": "not-a-uuid"},
        "tid not a uuid": {**base, "tid": "../../etc"},
        "sub of wrong type": {**base, "sub": 12345},
    }
    for name, claims in cases.items():
        token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
        resp = _get(client, token)
        assert resp.status_code == 401, name  # never a 500
        assert resp.json()["error"]["code"] == "invalid_token", name


def test_token_for_unknown_user_gets_no_access(client, apex, settings):
    claims = {"sub": str(uuid.uuid4()), "tid": apex.id, "role": "tenant_admin", "exp": int(time.time()) + 600}
    assert _get(client, jwt.encode(claims, settings.jwt_secret, algorithm="HS256")).status_code == 403


def test_bearer_scheme_and_empty_header_rejected(client, apex):
    token = login(client, apex, "tenant_admin")["Authorization"].split(" ")[1]
    for header in ("", "Bearer", "Basic " + token, token):
        assert client.get("/api/v1/documents", headers={"Authorization": header}).status_code == 401


def test_login_throttle_blocks_bruteforce_and_is_per_account(client, owner_engine):
    tenant = make_tenant(owner_engine, "thr")
    victim, other = tenant.users["tenant_admin"], tenant.users["support_engineer"]
    body = {"password": "wrong-password", "tenant": tenant.slug}
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json={"email": victim, **body}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"email": victim, **body})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "too_many_attempts"
    assert int(blocked.headers["Retry-After"]) > 0
    # even the correct password is refused while throttled, so guessing cannot continue
    assert client.post("/api/v1/auth/login", json={"email": victim, "password": PASSWORD,
                                                   "tenant": tenant.slug}).status_code == 429
    # another account is unaffected
    assert client.post("/api/v1/auth/login", json={"email": other, "password": PASSWORD,
                                                   "tenant": tenant.slug}).status_code == 200


def test_successful_login_clears_failure_count(client, owner_engine):
    tenant = make_tenant(owner_engine, "thr2")
    email = tenant.users["support_engineer"]
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": email, "password": "nope", "tenant": tenant.slug})
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD,
                                                   "tenant": tenant.slug}).status_code == 200
    for _ in range(9):  # the earlier 5 failures no longer count
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "nope",
                                                       "tenant": tenant.slug}).status_code == 401
