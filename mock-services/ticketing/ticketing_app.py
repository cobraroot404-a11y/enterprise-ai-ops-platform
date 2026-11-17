"""Mock enterprise ticketing system with configurable failure injection.

POST /tickets is idempotent on the Idempotency-Key header. Failure modes (set via /admin/failure) are
consumed one request at a time:
  503            respond 503 without creating anything
  429            respond 429 without creating anything
  timeout        sleep past the client timeout without creating anything
  malformed      create the ticket but respond with a body lacking ticket_id
  lost_response  create the ticket, then respond 503 (client cannot know it succeeded)
  400            respond 400 (permanent error)
"""
import asyncio
import os
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel


class FailureConfig(BaseModel):
    mode: str
    count: int = 1
    timeout_seconds: float = 3.0


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.tickets: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.failures: list[FailureConfig] = []
        self.counter = 1000
        self.requests = 0


def create_app(api_key: str | None = None) -> FastAPI:
    api_key = api_key or os.environ.get("MOCK_TICKETING_API_KEY", "")
    app = FastAPI(title="Mock Ticketing")
    app.state.mock = state = State()

    def check_key(x_api_key: str | None):
        if not api_key or x_api_key != api_key:
            raise HTTPException(status_code=401, detail="bad api key")

    def next_failure() -> FailureConfig | None:
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
            ticket_id = f"MNT-{state.counter}"
            state.tickets[ticket_id] = {"ticket_id": ticket_id, "payload": payload, "idempotency_key": key}
            if key:
                state.by_key[key] = ticket_id
            return ticket_id

    @app.post("/tickets")
    async def post_ticket(request: Request, x_api_key: str | None = Header(default=None),
                          idempotency_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with state.lock:
            state.requests += 1
        payload = await request.json()
        failure = next_failure()
        if failure:
            if failure.mode == "503":
                return JSONResponse({"error": "unavailable"}, status_code=503)
            if failure.mode == "429":
                return JSONResponse({"error": "rate limited"}, status_code=429, headers={"Retry-After": "1"})
            if failure.mode == "400":
                return JSONResponse({"error": "invalid payload"}, status_code=400)
            if failure.mode == "timeout":
                await asyncio.sleep(failure.timeout_seconds)  # must not block the event loop
                return JSONResponse({"error": "gateway timeout"}, status_code=504)  # creates nothing
            elif failure.mode == "malformed":
                create(payload, idempotency_key)
                return PlainTextResponse("<html>gateway page</html>", status_code=200)
            elif failure.mode == "lost_response":
                create(payload, idempotency_key)
                return JSONResponse({"error": "unavailable"}, status_code=503)
        ticket_id = create(payload, idempotency_key)
        return {"ticket_id": ticket_id, "status": "open"}

    @app.get("/admin/state")
    def admin_state(x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        return {"ticket_count": len(state.tickets), "requests": state.requests,
                "tickets": list(state.tickets.values()), "pending_failures": len(state.failures)}

    @app.post("/admin/failure")
    def admin_failure(config: FailureConfig, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with state.lock:
            state.failures.append(config)
        return {"queued": config.model_dump()}

    @app.post("/admin/reset")
    def admin_reset(x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with state.lock:
            state.tickets.clear()
            state.by_key.clear()
            state.failures.clear()
            state.requests = 0
        return {"reset": True}

    return app


app = create_app() if os.environ.get("MOCK_TICKETING_API_KEY") else None
