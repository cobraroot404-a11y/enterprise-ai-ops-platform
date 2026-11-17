"""Server-controlled outbound destination policy for every tenant-configurable connector.

Tenant administrators choose a connector's `base_url`, but they cannot choose where the platform may connect:
the allow-list lives in server configuration (environment), is scoped per tenant, and is enforced on EVERY
request (initial calls, retries, worker submissions, enrichments), not only when a connector is saved.

Layers, in order, for each request:
 1. URL hygiene: http/https only; no userinfo, whitespace/control characters, fragments, zone ids or
    non-ASCII hosts; numeric hosts must be canonical dotted-quad IPv4 or a bracketed IPv6 literal
    (decimal/hex/octal/short forms such as 2130706433, 0x7f000001, 0177.0.0.1, 127.1 are rejected).
 2. Origin allow-list: scheme://host:port (default ports made explicit) must be listed for this tenant's slug or
    for "*" in EGRESS_ALLOWLIST. Anything else is denied (unknown public domains, unexpected ports).
 3. Address policy: the host is resolved ONCE; every returned address must be globally routable (no loopback,
    private, link-local, multicast, reserved, unspecified, CGNAT or cloud-metadata addresses; IPv4-mapped IPv6
    is unwrapped first). Development-only mock origins (EGRESS_DEV_MOCKS) may additionally resolve to loopback,
    and only loopback; they are rejected outright when EAOP_ENV=production.
 4. Pinning: the connection is made to the validated IP (Host header and TLS SNI/verification keep the original
    name), so DNS cannot change between check and use (rebinding / TOCTOU).
Redirects are never followed, response size and time are bounded, and the API key is attached only to the pinned
origin. This policy is not a substitute for network-level egress controls in a real deployment.
"""
import ipaddress
import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

METADATA_ADDRESSES = {ipaddress.ip_address(a) for a in ("169.254.169.254", "169.254.170.2", "100.100.100.200",
                                                         "fd00:ec2::254", "192.0.0.192")}
_CONTROL = re.compile(r"[\s\x00-\x1f\x7f\\]")
_NETLOC = re.compile(r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.\-]+)(:[0-9]{1,5})?$")
_NUMERIC_LOOKING = re.compile(r"^[0-9a-fx.]+$", re.IGNORECASE)
DEFAULT_PORTS = {"http": 80, "https": 443}


class EgressDenied(Exception):
    """The destination is not authorized. `reason` is safe to show to administrators."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    address: str  # the validated, pinned IP literal

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _canonical_host(host: str) -> str:
    """Return a normalized host or raise. Rejects alternative numeric representations."""
    if not host.isascii():
        raise EgressDenied("non-ASCII host names are not allowed (use the punycode form)")
    if "%" in host:
        raise EgressDenied("IPv6 zone identifiers are not allowed")
    lowered = host.lower()
    if ":" in lowered:  # IPv6 literal (urlsplit strips the brackets)
        try:
            return str(ipaddress.IPv6Address(lowered))
        except ValueError as exc:
            raise EgressDenied("invalid IPv6 literal") from exc
    if _NUMERIC_LOOKING.match(lowered) and not re.search(r"[g-wyz]", lowered):
        # Looks like an IP in some notation. Only canonical dotted-quad is accepted.
        try:
            parsed = ipaddress.IPv4Address(lowered)
        except ValueError as exc:
            raise EgressDenied("alternative or malformed numeric host representation") from exc
        if str(parsed) != lowered:
            raise EgressDenied("alternative numeric host representation")
        return lowered
    if lowered.endswith(".") or ".." in lowered or lowered.startswith("."):
        raise EgressDenied("malformed host name")
    return lowered


def normalize_origin(url: str) -> tuple[str, str, int, str]:
    """(scheme, host, port, path) for a URL, or EgressDenied."""
    if _CONTROL.search(url):
        raise EgressDenied("URL contains whitespace, control characters or backslashes")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise EgressDenied("malformed URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise EgressDenied("only http and https are allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise EgressDenied("embedded credentials are not allowed")
    if parts.fragment or parts.query:
        raise EgressDenied("fragments and query strings are not allowed in a connector base URL")
    if not parts.hostname:
        raise EgressDenied("missing host")
    if not _NETLOC.match(parts.netloc):  # anything urlsplit would silently ignore (e.g. text after a bracket)
        raise EgressDenied("malformed host or port")
    try:
        port = parts.port or DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise EgressDenied("invalid port") from exc
    return scheme, _canonical_host(parts.hostname), port, parts.path


def _address_ok(ip, loopback_ok: bool) -> str | None:
    """None if the address may be used, otherwise the reason it may not."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip in METADATA_ADDRESSES:
        return "cloud metadata address"
    if ip.is_loopback:
        return None if loopback_ok else "loopback address"
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return "unspecified, multicast, link-local or reserved address"
    if ip.is_private or not ip.is_global:
        return "private or non-global address"
    return None


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressDenied("host name does not resolve") from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


class EgressPolicy:
    def __init__(self, allowlist: dict[str, list[str]] | None = None, dev_mocks: dict[str, list[str]] | None = None,
                 production: bool = False, resolver=None):
        if production and dev_mocks:
            raise ValueError("EGRESS_DEV_MOCKS must not be set when EAOP_ENV=production")
        self.production = production
        self._lock = threading.Lock()
        self._allow = {k: {self._origin_key(o) for o in v} for k, v in (allowlist or {}).items()}
        self._dev = {k: {self._origin_key(o) for o in v} for k, v in (dev_mocks or {}).items()}
        self._resolver = resolver or _resolve

    @staticmethod
    def _origin_key(origin: str) -> str:
        scheme, host, port, path = normalize_origin(origin)
        if path not in ("", "/"):
            raise ValueError(f"allow-list entry must be an origin without a path: {origin}")
        return f"{scheme}://{host}:{port}"

    def add_dev_mock(self, tenant: str, origin: str) -> None:
        """Development/test only: authorize one mock origin (it may resolve to loopback)."""
        if self.production:
            raise ValueError("development mock origins are disabled in production")
        with self._lock:
            self._dev.setdefault(tenant, set()).add(self._origin_key(origin))

    def _classify(self, origin: str, tenant_slug: str | None) -> str | None:
        """'prod', 'dev' or None for an origin as allowed for this tenant."""
        tenants = [t for t in (tenant_slug, "*") if t]
        with self._lock:
            if any(origin in self._allow.get(t, ()) for t in tenants):
                return "prod"
            if not self.production and any(origin in self._dev.get(t, ()) for t in tenants):
                return "dev"
        return None

    def check_config(self, base_url: str, tenant_slug: str | None) -> None:
        """Save-time validation (no DNS). Enforcement still happens again on every request."""
        scheme, host, port, _ = normalize_origin(base_url)
        origin = f"{scheme}://{host}:{port}"
        if self._classify(origin, tenant_slug) is None:
            raise EgressDenied(f"{origin} is not an approved connector destination for this tenant")

    def authorize(self, base_url: str, tenant_slug: str | None) -> Target:
        """Full connection-time check. Resolves the name once and returns the pinned address to connect to."""
        scheme, host, port, _ = normalize_origin(base_url)
        origin = f"{scheme}://{host}:{port}"
        kind = self._classify(origin, tenant_slug)
        if kind is None:
            raise EgressDenied(f"{origin} is not an approved connector destination for this tenant")
        try:
            literal = [str(ipaddress.ip_address(host))]
        except ValueError:
            literal = None
        addresses = literal or self._resolver(host, port)
        if not addresses:
            raise EgressDenied("host name does not resolve")
        for raw in addresses:
            try:
                ip = ipaddress.ip_address(raw.split("%")[0])
            except ValueError as exc:
                raise EgressDenied("resolver returned an invalid address") from exc
            reason = _address_ok(ip, loopback_ok=(kind == "dev"))
            if reason:  # every answer must be acceptable, so a mixed (rebinding) answer is refused
                raise EgressDenied(f"{origin} resolves to a disallowed destination ({reason})")
        return Target(scheme, host, port, addresses[0])


_policy: EgressPolicy | None = None


def _parse_json_env(name: str) -> dict:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise ValueError(f"{name} must be a JSON object mapping a tenant slug (or '*') to a list of origins")
    return data


def policy_from_environment() -> EgressPolicy:
    production = os.environ.get("EAOP_ENV", "development").lower() == "production"
    return EgressPolicy(_parse_json_env("EGRESS_ALLOWLIST"), _parse_json_env("EGRESS_DEV_MOCKS"), production)


def get_policy() -> EgressPolicy:
    global _policy
    if _policy is None:
        _policy = policy_from_environment()
    return _policy


def set_policy(policy: EgressPolicy | None) -> None:
    global _policy
    _policy = policy


def tenant_slug(session, tenant_id) -> str | None:
    """Slug of the connector's tenant, through a narrow database function (usable by the worker role too)."""
    from sqlalchemy import text
    return session.execute(text("SELECT connector_tenant_slug(CAST(:t AS uuid))"), {"t": str(tenant_id)}).scalar()
