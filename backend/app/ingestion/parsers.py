"""Parse uploaded files into provenance-preserving segments (page numbers, record identifiers)."""
import csv
import io
import json
import re
from dataclasses import dataclass

from pypdf import PdfReader

from app.core.errors import Invalid
from app.retrieval.text import chunk_text

ALLOWED_EXTENSIONS = {".pdf", ".csv", ".json", ".txt", ".md"}
MEDIA_TYPES = {
    ".pdf": "application/pdf", ".csv": "text/csv", ".json": "application/json",
    ".txt": "text/plain", ".md": "text/markdown",
}


@dataclass
class Segment:
    text: str
    page_number: int | None = None
    record_id: str | None = None


@dataclass
class Parsed:
    segments: list[Segment]
    page_count: int | None = None


def safe_filename(name: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    if not base:
        raise Invalid("Invalid filename", code="invalid_filename")
    return base[:200]


def extension_of(filename: str) -> str:
    dot = filename.rfind(".")
    ext = filename[dot:].lower() if dot >= 0 else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise Invalid(f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
                      code="unsupported_file_type", status_code=415)
    return ext


def parse_pdf(data: bytes) -> Parsed:
    try:
        reader = PdfReader(io.BytesIO(data))
        segments = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            for piece in chunk_text(text):
                segments.append(Segment(piece, page_number=number))
        return Parsed(segments, page_count=len(reader.pages))
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types for corrupt files
        raise Invalid("Could not parse PDF", code="unparseable_document") from exc


def parse_csv(data: bytes, id_field: str | None = None, field_map: dict[str, str] | None = None) -> Parsed:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Invalid("CSV must be UTF-8", code="unparseable_document") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise Invalid("CSV has no header row", code="unparseable_document")
    field_map = field_map or {}
    id_field = id_field or reader.fieldnames[0]
    segments = []
    for row in reader:
        mapped = {field_map.get(k, k): (v or "").strip() for k, v in row.items() if k}
        record_id = mapped.get(field_map.get(id_field, id_field)) or None
        body = "; ".join(f"{k}: {v}" for k, v in mapped.items() if v)
        if body:
            segments.append(Segment(body, record_id=record_id))
    return Parsed(segments)


def parse_json(data: bytes, id_field: str = "id") -> Parsed:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Invalid("Invalid JSON", code="unparseable_document") from exc
    records = payload if isinstance(payload, list) else [payload]
    segments = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise Invalid("JSON records must be objects", code="unparseable_document")
        record_id = str(rec.get(id_field)) if rec.get(id_field) is not None else f"record-{i + 1}"
        body = "; ".join(f"{k}: {v}" for k, v in rec.items() if v not in (None, ""))
        segments.append(Segment(body, record_id=record_id))
    return Parsed(segments)


def parse_text(data: bytes) -> Parsed:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Invalid("Text files must be UTF-8", code="unparseable_document") from exc
    return Parsed([Segment(c) for c in chunk_text(text)])


def parse(filename: str, data: bytes, field_map: dict[str, str] | None = None,
          id_field: str | None = None) -> tuple[Parsed, str]:
    ext = extension_of(filename)
    if ext == ".pdf":
        parsed = parse_pdf(data)
    elif ext == ".csv":
        parsed = parse_csv(data, id_field=id_field, field_map=field_map)
    elif ext == ".json":
        parsed = parse_json(data, id_field=id_field or "id")
    else:
        parsed = parse_text(data)
    if not parsed.segments:
        raise Invalid("Document contains no extractable text", code="empty_document")
    return parsed, MEDIA_TYPES[ext]
