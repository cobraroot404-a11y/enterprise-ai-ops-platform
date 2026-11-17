"""Mock CRM (fictional customer accounts and SLA tiers for Meridian's delivery customers)."""
import os
import threading

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

ACCOUNT_BY_VEHICLE = {
    "VH-2101": "ACC-501", "VH-2102": "ACC-501", "VH-2103": "ACC-502", "VH-2104": "ACC-503",
}
ACCOUNTS = {
    "ACC-501": {"account_name": "Harbor Fresh Foods (fictional)", "sla_tier": "gold", "sla_response_hours": 4},
    "ACC-502": {"account_name": "Northside Pharmacy Supply (fictional)", "sla_tier": "platinum", "sla_response_hours": 2},
    "ACC-503": {"account_name": "Regional Building Materials (fictional)", "sla_tier": "standard", "sla_response_hours": 24},
}


class FailureConfig(BaseModel):
    mode: str  # "503" | "malformed"
    count: int = 1


def create_app(api_key: str | None = None) -> FastAPI:
    api_key = api_key or os.environ.get("MOCK_CRM_API_KEY", "")
    app = FastAPI(title="Mock CRM")
    lock = threading.Lock()
    failures: list[FailureConfig] = []
    app.state.requests = []

    def check_key(x_api_key):
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="bad api key")

    @app.get("/accounts/by-vehicle/{unit_id}")
    def account_for_vehicle(unit_id: str, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            app.state.requests.append(unit_id)
            failure = failures[0] if failures else None
            if failure:
                failure.count -= 1
                if failure.count <= 0:
                    failures.pop(0)
        if failure and failure.mode == "503":
            return JSONResponse({"error": "unavailable"}, status_code=503)
        if failure and failure.mode == "malformed":
            return {"unexpected": True}
        code = ACCOUNT_BY_VEHICLE.get(unit_id)
        if code is None:
            return JSONResponse({"error": "no account for vehicle"}, status_code=404)
        return {"account_code": code, **ACCOUNTS[code]}

    @app.post("/admin/failure")
    def admin_failure(config: FailureConfig, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            failures.append(config)
        return {"queued": config.model_dump()}

    return app


app = create_app()  # no key required unless MOCK_CRM_API_KEY is set
