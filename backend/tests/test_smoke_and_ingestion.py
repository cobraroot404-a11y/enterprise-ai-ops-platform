from support import SAMPLES, login


def test_health(client, owner_engine):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "X-Correlation-ID" in resp.headers


def test_correlation_id_is_echoed(client):
    resp = client.get("/api/v1/health", headers={"X-Correlation-ID": "abc-123"})
    assert resp.headers["X-Correlation-ID"] == "abc-123"


def test_error_shape_is_standardized(client):
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 401
    body = resp.json()["error"]
    assert body["code"] == "unauthorized" and body["correlation_id"]


def test_ingest_preserves_provenance_and_is_idempotent(client, apex):
    headers = login(client, apex, "support_engineer")
    data = (SAMPLES / "apex_cp200_pump_manual.pdf").read_bytes()
    first = client.post("/api/v1/documents", headers=headers, data={"kind": "equipment_manual"},
                        files={"file": ("manual.pdf", data)})
    assert first.status_code == 201 and first.json()["status"] == "created"
    again = client.post("/api/v1/documents", headers=headers, data={"kind": "equipment_manual"},
                        files={"file": ("manual-copy.pdf", data)})
    assert again.json()["status"] == "duplicate"
    assert again.json()["document_id"] == first.json()["document_id"]

    hits = client.post("/api/v1/search", headers=headers,
                       json={"query": "drive-end bearing vibration exceeds 7.1 mm/s", "k": 3}).json()["items"]
    assert hits[0]["page_number"] == 2  # page provenance preserved


def test_csv_ingestion_keeps_record_ids(client, apex):
    headers = login(client, apex, "support_engineer")
    data = (SAMPLES / "incident_history.csv").read_bytes()
    assert client.post("/api/v1/documents", headers=headers, data={"kind": "incident_history"},
                       files={"file": ("incidents.csv", data)}).status_code == 201
    hits = client.post("/api/v1/search", headers=headers,
                       json={"query": "cavitation strainer P-101", "kinds": ["incident_history"]}).json()["items"]
    assert hits[0]["record_id"] == "INC-2025-0107"


def test_new_version_supersedes_old_chunks(client, apex):
    headers = login(client, apex, "support_engineer")
    post = lambda body: client.post("/api/v1/documents", headers=headers, data={"kind": "other"},  # noqa: E731
                                    files={"file": ("notes.txt", body)})
    assert post(b"Pump alpha uses red grease.").json()["status"] == "created"
    second = post(b"Pump alpha uses blue grease.").json()
    assert second["status"] == "new_version" and second["version"] == 2
    hits = client.post("/api/v1/search", headers=headers, json={"query": "grease colour alpha"}).json()["items"]
    assert all("red" not in h["text"] for h in hits)


def test_upload_restrictions(client, apex):
    headers = login(client, apex, "support_engineer")
    bad = client.post("/api/v1/documents", headers=headers, data={"kind": "other"},
                      files={"file": ("payload.exe", b"MZ")})
    assert bad.status_code == 415
    corrupt = client.post("/api/v1/documents", headers=headers, data={"kind": "other"},
                          files={"file": ("broken.pdf", b"not a pdf")})
    assert corrupt.status_code == 422
    traversal = client.post("/api/v1/documents", headers=headers, data={"kind": "other"},
                            files={"file": ("../../etc/passwd.txt", b"hello world text")})
    assert traversal.status_code == 201
    names = [d["filename"] for d in client.get("/api/v1/documents", headers=headers).json()["items"]]
    assert "passwd.txt" in names and not any("/" in n or ".." in n for n in names)
