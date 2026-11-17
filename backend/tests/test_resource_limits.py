"""Request-size limits and bounded concurrency (per-process; see app/core/limits.py)."""
import dataclasses
import threading
import time

import pytest
from app.ai.llm import get_llm
from app.api.v1 import domain_routes
from app.core.errors import AppError
from app.core.limits import ConcurrencyLimiter
from app.main import create_app
from fastapi.testclient import TestClient
from support import SAMPLES, login


def test_limiter_bounds_concurrency_and_releases_even_on_error():
    limiter = ConcurrencyLimiter("test", 2, wait_seconds=0.05)
    with limiter.slot():
        with limiter.slot():
            with pytest.raises(AppError) as exc:
                with limiter.slot():
                    pass
            assert exc.value.status_code == 429 and exc.value.code == "server_busy" and exc.value.retry_after
    with pytest.raises(RuntimeError):  # a failing request must still free its slot
        with limiter.slot():
            raise RuntimeError("boom")
    with limiter.slot(), limiter.slot():
        pass


def test_oversized_json_body_is_rejected_before_processing(client, apex):
    headers = login(client, apex, "support_engineer")
    big = {"question": "x" * 2_000_000}
    resp = client.post("/api/v1/ai/ask", headers=headers, json=big)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "payload_too_large"


def test_streamed_body_without_content_length_is_cut_off(client, apex):
    headers = login(client, apex, "support_engineer")

    def chunks():  # chunked transfer: no Content-Length, 3 MB of data
        for _ in range(3):
            yield b"x" * (1024 * 1024)

    resp = client.post("/api/v1/ai/ask", headers={**headers, "Content-Type": "application/json"}, content=chunks())
    assert resp.status_code == 413


def test_oversized_upload_is_rejected_and_normal_upload_still_works(client, apex):
    headers = login(client, apex, "support_engineer")
    limit = client.app.state.settings.max_upload_bytes
    too_big = client.post("/api/v1/documents", headers=headers, data={"kind": "other"},
                          files={"file": ("big.txt", b"a" * (limit + 300_000))})
    assert too_big.status_code == 413
    just_over = client.post("/api/v1/documents", headers=headers, data={"kind": "other"},
                            files={"file": ("over.txt", b"a" * (limit + 10))})
    assert just_over.status_code == 413
    ok = client.post("/api/v1/documents", headers=headers, data={"kind": "equipment_register"},
                     files={"file": ("equipment_register.csv", (SAMPLES / "equipment_register.csv").read_bytes())})
    assert ok.status_code == 201


class SlowLLM:
    name, model = "slow", "test"

    def __init__(self):
        self.inner = get_llm("deterministic")

    def answer(self, question, passages):
        time.sleep(1.0)
        return self.inner.answer(question, passages)

    def extract_fields(self, report_text):
        time.sleep(1.0)
        return self.inner.extract_fields(report_text)


def test_inference_endpoints_apply_bounded_concurrency(settings, app_db, apex_loaded, monkeypatch):
    tight = dataclasses.replace(settings, max_concurrent_llm=1, busy_wait_seconds=0.2)
    client = TestClient(create_app(tight, app_db))
    monkeypatch.setattr(domain_routes, "get_llm", lambda _name: SlowLLM())
    headers = login(client, apex_loaded, "support_engineer")
    codes, retry = [], []

    def ask():
        r = client.post("/api/v1/ai/ask", headers=headers, json={"question": "What should I check when pump P-101 shows abnormal vibration?"})
        codes.append(r.status_code)
        if r.status_code == 429:
            retry.append(r.headers.get("Retry-After"))

    threads = [threading.Thread(target=ask) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes.count(200) >= 1 and codes.count(429) >= 1, codes
    assert all(r for r in retry)
    again = client.post("/api/v1/ai/ask", headers=headers, json={"question": "What should I check when pump P-101 shows abnormal vibration?"})
    assert again.status_code == 200  # the slot was released; the service recovered


def test_ingestion_is_bounded_too(settings, app_db, apex, monkeypatch):
    tight = dataclasses.replace(settings, max_concurrent_ingest=1, busy_wait_seconds=0.1)
    client = TestClient(create_app(tight, app_db))
    real_ingest = domain_routes.ingestion_jobs.run_upload  # the upload's processing seam since Batch 9 (it was domain_routes.ingest)

    def slow_ingest(*a, **kw):
        time.sleep(1.0)
        return real_ingest(*a, **kw)

    monkeypatch.setattr(domain_routes.ingestion_jobs, "run_upload", slow_ingest)
    headers = login(client, apex, "support_engineer")
    codes = []

    def upload(i):
        r = client.post("/api/v1/documents", headers=headers, data={"kind": "other"},
                        files={"file": (f"note{i}.txt", f"unique note number {i} about pumps".encode())})
        codes.append(r.status_code)

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes.count(201) >= 1 and codes.count(429) >= 1, codes
