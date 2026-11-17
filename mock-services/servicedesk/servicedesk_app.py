"""Mock fleet service-desk (Meridian's work-order API): a DIFFERENT contract from the maintenance ticketing mock.

POST /api/v2/work-orders  body {summary, details, urgency: critical|high|normal|low, vehicle_ref, source_ref}
                          -> {"work_order_id": "WO-...", "state": "new"}
Idempotent on the Idempotency-Key header. Rejects any payload that does not follow this contract with 400, so a
connector sending the wrong shape (for example the maintenance system's) fails loudly instead of "working".
Failure injection and admin endpoints behave like the ticketing mock (same State/FailureConfig).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ticketing"))

from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse  # noqa: E402
from ticketing_app import FailureConfig, State  # noqa: E402

REQUIRED = ("summary", "details", "urgency", "vehicle_ref", "source_ref")
URGENCY = {"critical", "high", "normal", "low"}


def create_app(api_key: str | None = None) -> FastAPI:
    api_key = api_key or os.environ.get("MOCK_SERVICEDESK_API_KEY", "")
    app = FastAPI(title="Mock Fleet Service Desk")
    app.state.mock = state = State()
    state.counter = 7000

    def check_key(x_api_key):
        if not api_key or x_api_key != api_key:
            raise HTTPException(status_code=401, detail="bad api key")

    def next_failure():
        with state.lock:
            if not state.failures:
                return None
            failure = state.failures[0]
            failure.count -= 1
            if failure.count <= 0:
                state.failures.pop(0)
            return failure

    def create(payload: dict, key: str | None) -> str:
        with state.lock:
            if key and key in state.by_key:
                return state.by_key[key]
            state.counter += 1
            order_id = f"WO-{state.counter}"
            state.tickets[order_id] = {"work_order_id": order_id, "payload": payload, "idempotency_key": key}
            if key:
                state.by_key[key] = order_id
            return order_id

    @app.post("/api/v2/work-orders")
    async def post_work_order(request: Request, x_api_key: str | None = Header(default=None),
                              idempotency_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with state.lock:
            state.requests += 1
        payload = await request.json()
        missing = [f for f in REQUIRED if not isinstance(payload.get(f), str) or not payload.get(f)]
        if missing or payload.get("urgency") not in URGENCY or set(payload) - set(REQUIRED):
            return JSONResponse({"error": "payload does not match the work-order contract",
                                 "missing": missing, "unexpected": sorted(set(payload) - set(REQUIRED))},
                                status_code=400)
        failure = next_failure()
        if failure:
            if failure.mode == "503":
                return JSONResponse({"error": "unavailable"}, status_code=503)
            if failure.mode == "429":
                return JSONResponse({"error": "rate limited"}, status_code=429, headers={"Retry-After": "1"})
            if failure.mode == "400":
                return JSONResponse({"error": "invalid payload"}, status_code=400)
            if failure.mode == "timeout":
                await asyncio.sleep(failure.timeout_seconds)
                return JSONResponse({"error": "gateway timeout"}, status_code=504)
            if failure.mode == "malformed":
                create(payload, idempotency_key)
                return PlainTextResponse("<html>gateway page</html>", status_code=200)
            if failure.mode == "lost_response":
                create(payload, idempotency_key)
                return JSONResponse({"error": "unavailable"}, status_code=503)
        return {"work_order_id": create(payload, idempotency_key), "state": "new"}

    @app.get("/admin/state")
    def admin_state(x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        return {"count": len(state.tickets), "requests": state.requests, "work_orders": list(state.tickets.values())}

    @app.post("/admin/failure")
    def admin_failure(config: FailureConfig, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with state.lock:
            state.failures.append(config)
        return {"queued": config.model_dump()}

    return app


app = create_app() if os.environ.get("MOCK_SERVICEDESK_API_KEY") else None
