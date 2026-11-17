"""Per-tenant request-rate limit for the expensive operations (AI questions, incident extraction, document upload).

A token bucket per (tenant, operation), shared by every API process through the database (see app/connectors/ratelimit.py), in addition to the per-process concurrency and size limits
in app/core/limits.py. A tenant that exhausts its bucket gets HTTP 429 `rate_limited` with `Retry-After`; other tenants are unaffected because the bucket key carries the tenant id.
Defaults are generous (a normal user never sees them); they exist to stop a runaway client or a loop from monopolising the shared CPU-bound model.
"""
import math

from app.connectors.ratelimit import LIMITERS, RateLimited
from app.core.errors import AppError
from app.observability.metrics import METRICS


def enforce_tenant_rate(request, tenant_id, operation: str) -> None:
    settings = request.app.state.settings
    try:
        LIMITERS.get(tenant_id, f"api:{operation}", settings.api_rate_per_second, settings.api_rate_burst).acquire(0)
    except RateLimited as exc:
        METRICS.incr("api_rate_limited_total", tenant=str(tenant_id), operation=operation)
        wait = max(1, math.ceil(exc.retry_after)) if exc.retry_after else 1
        raise AppError(f"Too many {operation} requests for this organisation; retry shortly", code="rate_limited", status_code=429, retry_after=wait) from exc
