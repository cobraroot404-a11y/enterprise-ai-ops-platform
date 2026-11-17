"""Mock REST records source (fictional maintenance notes and service bulletins) for the REST pull connector, with configurable failures.

Three pagination styles over the same datasets so every pager mode runs against real HTTP:
    GET /v1/{dataset}/cursor?limit=&cursor=   -> {"items": [...], "next_cursor": "...", "has_more": bool}
    GET /v1/{dataset}/offset?limit=&offset=   -> {"items": [...], "total": N}
    GET /v1/{dataset}/page?limit=&page=       -> {"items": [...], "total": N}          (page is 1-based)
Authentication: `X-API-Key` (401 otherwise) when an API key is configured. Test/demo control (also key protected):
    POST /admin/dataset/{name}   body {"records": [...]}      replace a dataset (updated, duplicated or invalid records)
    POST /admin/failure          body {"mode": ..., "count": n}   the next n DATA requests fail:
        "429" (Retry-After: 1) | "503" | "timeout" (sleeps `delay` seconds) | "bad_shape" (items is not a list) | "url_cursor" (next_cursor points at a URL)
        | "repeat_cursor" (next_cursor equals the cursor sent) | "empty_page" (an empty page that still carries a continuation) | "redirect" (302 to a local metadata address)
    GET  /v1/{dataset}/csv       the dataset as one CSV file (also failure modes bad_csv, bad_encoding, no_id_column)
    GET  /admin/requests         the data requests seen so far (dataset, mode, params, whether the key was valid)
"""
import base64
import os
import threading
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel


def _apex() -> list[dict]:
    notes = [("P-101", "Seal weep on pump P-101", "Mechanical seal on pump P-101 weeps under load; replace the seal and recheck alignment."),
             ("P-101", "Bearing temperature trend P-101", "Bearing temperature on P-101 trends up 3 C per week; schedule lubrication."),
             ("C-210", "Compressor C-210 filter change", "Inlet filter on compressor C-210 is due; differential pressure above limit."),
             ("C-210", "Compressor C-210 vibration", "Vibration on C-210 is within limits after rebalancing."),
             ("V-330", "Valve V-330 packing leak", "Gland packing on valve V-330 leaks slightly; tighten packing nuts evenly."),
             ("T-415", "Tank T-415 level sensor drift", "Level sensor on tank T-415 drifts; recalibrate against the sight glass."),
             ("P-102", "Pump P-102 coupling inspection", "Flexible coupling on P-102 shows wear; replace at next shutdown.")]
    return [{"id": f"APX-N-{i + 1:03d}", "title": t, "body": b, "asset": a, "updated_at": f"2026-11-0{(i % 7) + 1}T08:00:00Z"} for i, (a, t, b) in enumerate(notes)]


def _meridian() -> list[dict]:
    notes = [("VH-2101", "Brake pad wear bulletin VH-2101", "Front brake pads on VH-2101 are at 18 percent; order pads before the next route block."),
             ("VH-2102", "Coolant leak bulletin VH-2102", "Coolant leak at the upper hose clamp of VH-2102; replace the clamp and top up coolant."),
             ("VH-2103", "Tyre pressure advisory VH-2103", "Rear tyres of VH-2103 lose pressure; inspect the valve stems."),
             ("VH-2104", "Telematics fault code VH-2104", "Intermittent telematics fault code on VH-2104; reseat the connector."),
             ("VH-2101", "Service interval notice VH-2101", "VH-2101 reaches its service interval at 185000 km.")]
    return [{"id": f"MER-B-{i + 1:03d}", "title": t, "body": b, "unit": a, "revision": i + 1} for i, (a, t, b) in enumerate(notes)]


class FailureConfig(BaseModel):
    mode: str
    count: int = 1
    delay: float = 0.6
    after: int = 0  # let this many data requests succeed first, then start failing


class DatasetBody(BaseModel):
    records: list


def create_app(api_key: str | None = None) -> FastAPI:
    api_key = api_key if api_key is not None else os.environ.get("MOCK_RECORDS_API_KEY", "")
    app = FastAPI(title="Mock REST Records Source")
    lock = threading.Lock()
    datasets = {"apex": _apex(), "meridian": _meridian()}
    failures: list[FailureConfig] = []
    app.state.mock = type("Mock", (), {"lock": lock, "datasets": datasets, "failures": failures, "requests": []})

    def check_key(x_api_key):
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="bad api key")

    def take_failure():
        with lock:
            if not failures:
                return None
            failure = failures[0]
            if failure.after > 0:
                failure.after -= 1
                return None
            failure.count -= 1
            if failure.count <= 0:
                failures.pop(0)
            return failure

    def data_request(dataset, mode, params, x_api_key):
        with lock:
            app.state.mock.requests.append({"dataset": dataset, "mode": mode, "params": dict(params), "key_ok": (not api_key) or x_api_key == api_key})
        check_key(x_api_key)
        if dataset not in datasets:
            raise HTTPException(status_code=404, detail="unknown dataset")
        failure = take_failure()
        if failure is None:
            return None
        if failure.mode == "429":
            return JSONResponse({"error": "slow down"}, status_code=429, headers={"Retry-After": "1"})
        if failure.mode == "503":
            return JSONResponse({"error": "unavailable"}, status_code=503)
        if failure.mode == "timeout":
            time.sleep(failure.delay)
            return JSONResponse({"items": []})
        if failure.mode == "redirect":
            return Response(status_code=302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        return failure

    def encode(offset: int) -> str:
        return base64.urlsafe_b64encode(f"o{offset}".encode()).decode().rstrip("=")

    def decode(token: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
            if not raw.startswith("o"):
                raise ValueError
            return int(raw[1:])
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="invalid cursor") from None

    @app.get("/v1/{dataset}/cursor")
    def cursor_page(dataset: str, limit: int = Query(50, ge=1, le=500), cursor: str | None = None, x_api_key: str | None = Header(default=None)):
        outcome = data_request(dataset, "cursor", {"limit": limit, "cursor": cursor}, x_api_key)
        if isinstance(outcome, (JSONResponse, Response)):
            return outcome
        offset = decode(cursor) if cursor else 0
        rows = datasets[dataset][offset: offset + limit]
        nxt = offset + len(rows)
        has_more = nxt < len(datasets[dataset])
        body = {"items": rows, "next_cursor": encode(nxt) if has_more else None, "has_more": has_more}
        if isinstance(outcome, FailureConfig):
            if outcome.mode == "bad_shape":
                body["items"] = {"not": "a list"}
            elif outcome.mode == "url_cursor":
                body.update(next_cursor="http://169.254.169.254/latest/meta-data/", has_more=True)
            elif outcome.mode == "repeat_cursor":
                body.update(next_cursor=cursor or encode(0), has_more=True)
            elif outcome.mode == "empty_page":
                body.update(items=[], next_cursor=encode(0), has_more=True)
        return body

    @app.get("/v1/{dataset}/offset")
    def offset_page(dataset: str, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), x_api_key: str | None = Header(default=None)):
        outcome = data_request(dataset, "offset", {"limit": limit, "offset": offset}, x_api_key)
        if isinstance(outcome, (JSONResponse, Response)):
            return outcome
        rows = datasets[dataset][offset: offset + limit]
        body = {"items": rows, "total": len(datasets[dataset])}
        if isinstance(outcome, FailureConfig) and outcome.mode == "bad_shape":
            body["items"] = "nope"
        return body

    @app.get("/v1/{dataset}/page")
    def page_page(dataset: str, limit: int = Query(50, ge=1, le=500), page: int = Query(1, ge=1), x_api_key: str | None = Header(default=None)):
        outcome = data_request(dataset, "page", {"limit": limit, "page": page}, x_api_key)
        if isinstance(outcome, (JSONResponse, Response)):
            return outcome
        rows = datasets[dataset][(page - 1) * limit: page * limit]
        body = {"items": rows, "total": len(datasets[dataset])}
        if isinstance(outcome, FailureConfig) and outcome.mode == "bad_shape":
            body["items"] = None
        return body

    @app.get("/v1/{dataset}/csv")
    def csv_file(dataset: str, x_api_key: str | None = Header(default=None)):
        outcome = data_request(dataset, "csv", {}, x_api_key)
        if isinstance(outcome, (JSONResponse, Response)):
            return outcome
        import csv
        import io
        mode = getattr(outcome, "mode", "")
        if mode == "bad_csv":  # a BOM, a short row, a blank line, a long row and a quoted comma
            lines = ["﻿id,title,body", "C-1,Valid row,Body one", "C-2,Short row", "", "C-3,Long row,Body,extra", 'C-4,"Quoted, comma",Body four']
            return Response(content=("\n".join(lines) + "\n").encode("utf-8"), media_type="text/csv")
        if mode == "bad_encoding":
            return Response(content=b"id,title,body\nC-1,caf\xe9,Latin-1 bytes\n", media_type="text/csv")
        if mode == "no_id_column":
            return Response(content=b"ref,title,body\nX-1,t,b\n", media_type="text/csv")
        rows = [r for r in datasets[dataset] if isinstance(r, dict)]
        fields = ["id", "title", "body"] + sorted({k for r in rows for k in r} - {"id", "title", "body"})
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
        return Response(content=out.getvalue().encode("utf-8"), media_type="text/csv")

    @app.post("/admin/dataset/{name}")
    def set_dataset(name: str, body: DatasetBody, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            datasets[name] = list(body.records)
        return {"dataset": name, "records": len(body.records)}

    @app.post("/admin/failure")
    def admin_failure(config: FailureConfig, x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            failures.append(config)
        return {"queued": config.model_dump()}

    @app.get("/admin/requests")
    def admin_requests(x_api_key: str | None = Header(default=None)):
        check_key(x_api_key)
        with lock:
            return {"requests": list(app.state.mock.requests)}

    return app


app = create_app()
