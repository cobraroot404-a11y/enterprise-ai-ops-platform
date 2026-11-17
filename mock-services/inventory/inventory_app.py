"""Mock inventory system (spare parts) with configurable failures."""
import os
import threading

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PARTS = {
    "PN-4417": {"description": "Pump bearing set, drive end", "quantity_on_hand": 6, "location": "Store A-12"},
    "PN-5102": {"description": "Mechanical seal kit", "quantity_on_hand": 0, "location": "Store A-14"},
    "PN-3308": {"description": "Flexible coupling element", "quantity_on_hand": 3, "location": "Store B-03"},
    "PN-7720": {"description": "Vibration sensor", "quantity_on_hand": 2, "location": "Store C-01"},
}


class FailureConfig(BaseModel):
    mode: str  # "503" | "timeout" | "malformed"
    count: int = 1


def create_app(api_key: str | None = None) -> FastAPI:
    api_key = api_key or os.environ.get("MOCK_INVENTORY_API_KEY", "")
    app = FastAPI(title="Mock Inventory")
    lock = threading.Lock()
    failures: list[FailureConfig] = []

    def check_key(x_api_key):
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="bad api key")

    @app.get("/parts/{part_number}")
    def get_part(part_number: str, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            failure = failures[0] if failures else None
            if failure:
                failure.count -= 1
                if failure.count <= 0:
                    failures.pop(0)
        if failure and failure.mode == "503":
            return JSONResponse({"error": "unavailable"}, status_code=503)
        if failure and failure.mode == "malformed":
            return {"unexpected": True}
        part = PARTS.get(part_number)
        if part is None:
            return JSONResponse({"error": "unknown part"}, status_code=404)
        return {"part_number": part_number, **part}

    @app.post("/admin/failure")
    def admin_failure(config: FailureConfig, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            failures.append(config)
        return {"queued": config.model_dump()}

    return app


app = create_app()
