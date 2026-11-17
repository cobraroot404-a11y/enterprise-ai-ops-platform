"""Onboard a customer tenant through the PUBLIC API only (no database access, no code changes).

  python scripts/onboard_tenant.py onboarding/meridian.json [--api http://127.0.0.1:8000]

Environment (never stored in the config file; for local development the demo defaults apply):
  PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD   creates the tenant and its first administrator
                                                   (default: the seeded demo platform admin and SEED_PASSWORD)
  ONBOARD_PASSWORD                                 initial password for the listed members (default: SEED_PASSWORD)
  <secret_ref names>                               connector secrets are referenced by NAME only (server-side env)

Idempotent: existing tenant, members and connectors are left as they are; the profile is replaced (versioned);
unchanged documents are reported as duplicates. Refuses to run against a non-local API unless --allow-remote
is given. Prints no credentials. `onboard()` also accepts a Starlette TestClient (used by the test-suite).
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


class OnboardingError(Exception):
    pass


def onboard(config: dict, client, *, password: str, platform: tuple[str, str] | None = None,
            prefix: str = "/api/v1", root: Path = ROOT, log=print) -> dict:
    tenant, members = config["tenant"], config["members"]
    first_admin = next((m for m in members if m["role"] == "tenant_admin"), None)
    if first_admin is None:
        raise OnboardingError("config needs a tenant_admin member")
    if len(password) < 10:
        raise OnboardingError("the initial member password must be at least 10 characters")

    def call(method, path, token=None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, prefix + path, headers=headers, **kw)

    def login(email, slug=None, pw=password):
        body = {"email": email, "password": pw, **({"tenant": slug} if slug else {})}
        res = call("POST", "/auth/login", json=body)
        return res.json() if res.status_code == 200 else None

    session = login(first_admin["email"], tenant["slug"])
    if session is None:  # tenant (or its administrator) does not exist yet: the platform administrator creates them
        if not platform:
            raise OnboardingError("tenant not found and no platform administrator credentials were supplied")
        admin = login(platform[0], None, platform[1])
        if admin is None:
            raise OnboardingError("platform administrator sign-in failed")
        created = call("POST", "/tenants", admin["access_token"], json=tenant)
        if created.status_code != 201:
            raise OnboardingError(f"tenant creation failed: {created.status_code} {created.text[:200]}")
        tenant_id = created.json()["id"]
        added = call("POST", f"/tenants/{tenant_id}/members", admin["access_token"], json={
            "email": first_admin["email"], "full_name": first_admin["full_name"], "password": password,
            "role": "tenant_admin"})
        if added.status_code not in (201, 409):
            raise OnboardingError(f"adding the first administrator failed: {added.status_code}")
        session = login(first_admin["email"], tenant["slug"])
        if session is None:
            raise OnboardingError("the first administrator cannot sign in")
        log(f"created tenant {tenant['slug']}")
    token, tenant_id = session["access_token"], session["tenant_id"]

    summary = {"tenant_id": tenant_id, "members": {}, "connectors": {}, "documents": {}}
    for member in members:
        if member is first_admin:
            continue
        res = call("POST", f"/tenants/{tenant_id}/members", token, json={
            "email": member["email"], "full_name": member["full_name"], "password": password, "role": member["role"]})
        summary["members"][member["role"]] = "added" if res.status_code == 201 else "exists" if res.status_code == 409 \
            else f"error {res.status_code}"
        log(f"member {member['role']}: {summary['members'][member['role']]}")
    for connector in config.get("connectors", []):
        res = call("POST", "/connectors", token, json={k: v for k, v in connector.items() if v is not None})
        summary["connectors"][connector["kind"]] = "created" if res.status_code == 201 else "exists" \
            if res.status_code == 409 else f"error {res.status_code}: {res.text[:160]}"
        log(f"connector {connector['kind']}: {summary['connectors'][connector['kind']]}")
    res = call("PUT", "/tenant-profile", token, json=config["profile"])
    if res.status_code != 200:
        raise OnboardingError(f"profile rejected: {res.status_code} {res.text[:400]}")
    summary["profile_version"] = res.json()["version"]
    log(f"profile: version {summary['profile_version']}")
    for doc in config.get("documents", []):
        path = root / doc["file"]
        res = call("POST", "/documents", token, data={"kind": doc["kind"]},
                   files={"file": (path.name, path.read_bytes())})
        if res.status_code != 201:
            raise OnboardingError(f"upload of {path.name} failed: {res.status_code} {res.text[:200]}")
        summary["documents"][path.name] = res.json()["status"]
        log(f"document {path.name}: {res.json()['status']} ({res.json()['chunk_count']} chunks)")
    return summary


def main() -> None:
    import httpx

    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--allow-remote", action="store_true")
    args = ap.parse_args()
    if urlparse(args.api).hostname not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        sys.exit("onboard_tenant: refusing to onboard against a non-local API (use --allow-remote if intended)")
    seed = os.environ.get("SEED_PASSWORD", "")  # local development default: the demo accounts share SEED_PASSWORD
    email = os.environ.get("PLATFORM_ADMIN_EMAIL") or ("platform-admin@example.test" if seed else "")
    secret = os.environ.get("PLATFORM_ADMIN_PASSWORD") or seed
    platform = (email, secret) if email and secret else None
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    try:
        with httpx.Client(base_url=args.api.rstrip("/"), timeout=300) as client:
            onboard(config, client, password=os.environ.get("ONBOARD_PASSWORD") or seed, platform=platform)
    except OnboardingError as exc:
        sys.exit(f"onboard_tenant: {exc}")
    print("onboarding complete")


if __name__ == "__main__":
    main()
