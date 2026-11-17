"""FastAPI application factory."""
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import core_routes, domain_routes, ops_routes, profile_routes, webhook_routes
from app.api.v1.error_contracts import apply_error_contract
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.limits import BodyLimitMiddleware, ConcurrencyLimiter
from app.core.production_guard import assert_production_safe
from app.database.session import Database
from app.observability.logging import configure_logging
from app.observability.metrics import METRICS

log = logging.getLogger("eaop.api")


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()
    assert_production_safe(settings)  # no-op outside production; refuses test-only configuration inside it
    app = FastAPI(title="Enterprise AI Operations Platform", version="0.1.0",
                  description="Multi-tenant AI operations platform (fictional customers).")
    app.state.settings = settings
    app.state.db = db or Database(settings, role="app")
    from app.connectors.ratelimit import LIMITERS

    LIMITERS.use_database(app.state.db)  # connector, webhook, per-tenant and sign-in limits are shared by every process using this database
    from app.observability.metrics import start_flusher

    start_flusher(app.state.db, settings.metrics_flush_seconds)  # durable metrics: deltas are written to PostgreSQL every few seconds
    app.state.limiters = {
        "ingestion": ConcurrencyLimiter("document ingestion", settings.max_concurrent_ingest,
                                        settings.busy_wait_seconds, shared_key="ingestion"),
        "inference": ConcurrencyLimiter("AI inference", settings.max_concurrent_llm, settings.busy_wait_seconds, shared_key="inference"),
    }
    app.add_middleware(BodyLimitMiddleware, default_limit=settings.max_json_bytes,
                       upload_limit=settings.max_upload_bytes + 256 * 1024, upload_path="/api/v1/documents")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Correlation-ID", "X-Trace-ID"])

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        from app.observability import tracing

        incoming_trace = tracing.parse_traceparent(request.headers.get("traceparent"))
        cid = request.headers.get("X-Correlation-ID") or incoming_trace or str(uuid.uuid4())
        request.state.correlation_id = cid
        trace_id = incoming_trace or tracing.trace_id_for(cid)
        request.state.trace_id = trace_id
        token = tracing.set_current(trace_id)
        started = time.perf_counter()
        try:
            with tracing.span("http.request", method=request.method) as attrs:
                response = await call_next(request)
                attrs["route"] = getattr(request.scope.get("route"), "path", None) or "unmatched"
                attrs["status"] = response.status_code
        finally:
            tracing.reset(token)
        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Trace-ID"] = trace_id
        elapsed = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"  # the route TEMPLATE: no ids, no query
        METRICS.observe("http_request_seconds", elapsed, route=route, method=request.method,
                        status_class=f"{response.status_code // 100}xx")
        log.info("request", extra={"correlation_id": cid, "trace_id": trace_id, "method": request.method,
                                   "path": request.url.path,
                                   "route": route, "status": response.status_code,
                                   "duration_ms": round(elapsed * 1000, 1)})
        return response

    def error_body(request: Request, code: str, message: str, details=None) -> dict:
        body = {"error": {"code": code, "message": message,
                          "correlation_id": getattr(request.state, "correlation_id", None)}}
        if details is not None:
            body["error"]["details"] = details
        return body

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        METRICS.incr("errors_total", source="api", error=exc.code, status=exc.status_code)
        headers = {"Retry-After": str(exc.retry_after)} if getattr(exc, "retry_after", None) else None
        return JSONResponse(error_body(request, exc.code, exc.message), status_code=exc.status_code,
                            headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        METRICS.incr("errors_total", source="api", error="validation_error", status=422)
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(error_body(request, "validation_error", "Request validation failed", details),
                            status_code=422)

    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError):
        METRICS.incr("errors_total", source="api", error="database_unavailable", status=503)
        log.error("database unavailable", extra={"correlation_id": getattr(request.state, "correlation_id", None)})
        return JSONResponse(error_body(request, "database_unavailable",
                                       "The database is temporarily unavailable; retry shortly"),
                            status_code=503, headers={"Retry-After": "5"})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        """Routing-level errors (unknown path, wrong method) use the same standardized body as every other error."""
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = {404: "Not found", 405: "Method not allowed"}.get(exc.status_code, str(exc.detail))
        METRICS.incr("errors_total", source="api", error=code, status=exc.status_code)
        headers = dict(exc.headers) if getattr(exc, "headers", None) else None
        return JSONResponse(error_body(request, code, message), status_code=exc.status_code, headers=headers)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        METRICS.incr("errors_total", source="api", error="internal_error", status=500)
        cid = getattr(request.state, "correlation_id", None)
        log.exception("unhandled error", extra={"correlation_id": cid})
        # this handler runs outside the correlation middleware, so the header is set here
        return JSONResponse(error_body(request, "internal_error", "Internal server error"), status_code=500,
                            headers={"X-Correlation-ID": cid} if cid else None)

    public_operations = {("post", "/api/v1/auth/login"), ("get", "/api/v1/health")}

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        bearer = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                  "description": "Access token from POST /api/v1/auth/login"}
        signature = {"type": "apiKey", "in": "header", "name": "X-Webhook-Signature",
                     "description": (
                         "sha256=HMAC-SHA256(secret, timestamp.delivery_id.raw_body); also X-Webhook-Timestamp "
                         "and X-Webhook-Delivery-Id")}
        schema.setdefault("components", {})["securitySchemes"] = {"bearerAuth": bearer, "webhookSignature": signature}
        for path, ops in schema["paths"].items():
            for method, op in ops.items():
                if method in ("get", "post", "put", "patch", "delete") and (method, path) not in public_operations:
                    is_receiver = path == "/api/v1/webhooks/{endpoint_id}"
                    op["security"] = [{"webhookSignature": []}] if is_receiver else [{"bearerAuth": []}]
        app.openapi_schema = apply_error_contract(schema)
        return schema
    app.openapi = custom_openapi

    prefix = "/api/v1"
    for router in (core_routes.auth_router, core_routes.tenants_router, core_routes.platform_router,
                   core_routes.connectors_router, core_routes.health_router, domain_routes.documents_router,
                   domain_routes.ingestion_router,
                   domain_routes.search_router, domain_routes.ai_router, domain_routes.incidents_router,
                   domain_routes.tickets_router, domain_routes.approvals_router,
                   domain_routes.workflows_router, domain_routes.audit_router, domain_routes.metrics_router,
                   profile_routes.profile_router, ops_routes.history_router, ops_routes.connectors_health_router,
                   ops_routes.onboarding_router, ops_routes.evaluation_router, ops_routes.observability_router,
                   webhook_routes.webhook_endpoints_router, webhook_routes.webhooks_router):
        app.include_router(router, prefix=prefix)
    app.include_router(ops_routes.prometheus_router)  # /metrics: Prometheus text, not part of the typed JSON contract
    return app
