"""Mock fleet-management / telematics system (fictional Meridian vehicles) with configurable failures."""
import os
import threading

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

VEHICLES = {
    "VH-2101": {"odometer_km": 182450, "last_service_date": "2026-07-02", "status": "in_service", "depot": "Harbor Depot"},
    "VH-2102": {"odometer_km": 176120, "last_service_date": "2026-08-19", "status": "in_service", "depot": "Harbor Depot"},
    "VH-2103": {"odometer_km": 94310, "last_service_date": "2026-06-11", "status": "in_service", "depot": "Northside Depot"},
    "VH-2104": {"odometer_km": 301870, "last_service_date": "2026-05-28", "status": "in_service", "depot": "Northside Depot"},
}


class FailureConfig(BaseModel):
    mode: str  # "503" | "malformed"
    count: int = 1


def create_app(api_key: str | None = None) -> FastAPI:
    api_key = api_key or os.environ.get("MOCK_FLEET_API_KEY", "")
    app = FastAPI(title="Mock Fleet Management")
    lock = threading.Lock()
    failures: list[FailureConfig] = []
    app.state.requests = []

    def check_key(x_api_key):
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="bad api key")

    @app.get("/vehicles/{unit_id}")
    def get_vehicle(unit_id: str, x_api_key: str | None = Header(default=None)):
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
        vehicle = VEHICLES.get(unit_id)
        if vehicle is None:
            return JSONResponse({"error": "unknown vehicle"}, status_code=404)
        return {"unit_id": unit_id, **vehicle}

    @app.post("/admin/failure")
    def admin_failure(config: FailureConfig, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            failures.append(config)
        return {"queued": config.model_dump()}

    return app


app = create_app()  # no key required unless MOCK_FLEET_API_KEY is set
