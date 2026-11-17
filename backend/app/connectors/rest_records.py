"""REST records source: configuration, bounded pagination, record validation and the live health probe (V41-12.01 REST part, V41-11.01, V41-11.02).

Everything goes through the existing HttpConnector (per-request egress policy with a pinned address, no redirects, 1 MiB response bound, `X-API-Key` from the secret reference). This module
adds no network code of its own: it builds RELATIVE paths for the connector's own base URL, so no user-supplied or source-supplied URL can ever choose a destination. Pagination values
are tokens, never URLs. Every loop is bounded. Errors carry fixed codes only (never upstream text, headers or credentials)."""
import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.connectors.http import MALFORMED, PERMANENT, TRANSIENT, ConnectorError, HttpConnector, resolve_secret
from app.connectors.ratelimit import LIMITERS, MAX_WAIT_SECONDS, RateLimited
from app.core.errors import AppError, Invalid

PARAM = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,39}$")
FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,59}$")
CURSOR = re.compile(r"^[A-Za-z0-9_\-=.:+]{1,512}$")  # no slash, no whitespace: a cursor can never look like a URL or a path
RECORD_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
PAGE_ATTEMPTS = 3  # attempts for one page within one job attempt (the job retries beyond that with backoff)


class SourceError(AppError):
    """A failure of the external source with a fixed code. `transient` failures are retried by the job; the others fail it."""
    status_code = 502

    def __init__(self, code: str, *, transient: bool = False):
        super().__init__(code, code=code)
        self.transient = transient


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(default="none", pattern="^(cursor|offset|page|none)$")
    page_size: int = Field(default=50, ge=1, le=500)
    limit_param: str = "limit"
    cursor_param: str = "cursor"
    offset_param: str = "offset"
    page_param: str = "page"
    next_cursor_field: str = "next_cursor"
    has_more_field: str | None = None
    total_field: str | None = None

    @model_validator(mode="after")
    def _names(self):
        for name in (self.limit_param, self.cursor_param, self.offset_param, self.page_param):
            if not PARAM.match(name):
                raise ValueError("invalid parameter name")
        for name in (self.next_cursor_field, self.has_more_field, self.total_field):
            if name is not None and not FIELD.match(name):
                raise ValueError("invalid field name")
        return self


class Rate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests_per_second: float = Field(default=5.0, ge=0.1, le=50)
    burst: int = Field(default=5, ge=1, le=20)


class RecordsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    record_path: str = "items"
    id_field: str
    version_field: str | None = None
    required_fields: list[str] = Field(default_factory=list, max_length=20)
    document_kind: str = "other"
    pagination: Pagination = Field(default_factory=Pagination)
    max_pages: int = Field(default=20, ge=1, le=100)
    max_records: int = Field(default=500, ge=1, le=5000)
    max_record_bytes: int = Field(default=65536, ge=256, le=262144)
    reject_policy: str = Field(default="skip", pattern="^(skip|fail)$")
    rate: Rate = Field(default_factory=Rate)

    @model_validator(mode="after")
    def _safe(self):
        if not safe_path(self.path):
            raise ValueError("path must be a relative path starting with '/'")
        for name in (self.record_path, self.id_field, self.version_field, *self.required_fields):
            if name is not None and not FIELD.match(name):
                raise ValueError("invalid field name")
        return self


def safe_path(path: str) -> bool:
    """A relative path on the connector's own base URL: no scheme, no authority, no dot segments, no backslash, no query (parameters are added by the pager)."""
    return bool(path) and path.startswith("/") and not path.startswith("//") and not any(c in path for c in "\\?#@ \t\r\n") and "://" not in path and ".." not in path.split("/") and len(path) <= 200


def parse_config(connector_config: dict | None) -> RecordsConfig:
    """The `records` object of a connector's config, validated. Raises Invalid(invalid_connector_config) with a field-free message (no echo of the supplied values)."""
    raw = (connector_config or {}).get("records")
    if not isinstance(raw, dict):
        raise Invalid("This connector has no records configuration", code="invalid_connector_config", status_code=422)
    try:
        return RecordsConfig.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "records" for e in exc.errors()})
        raise Invalid(f"Invalid records configuration (check: {', '.join(fields)})", code="invalid_connector_config", status_code=422) from exc


# ------------------------------------------------------------------------------------------------------------------------------------ pagination
@dataclass
class PageState:
    """Where the pager is. JSON serialisable: it is saved in the job after every page so a retry resumes instead of starting again."""
    cursor: str | None = None
    offset: int = 0
    page: int = 1
    pages: int = 0
    records: int = 0
    seen_cursors: list[str] = field(default_factory=list)
    last_signature: str | None = None
    done: bool = False

    def to_json(self) -> dict:
        return {"cursor": self.cursor, "offset": self.offset, "page": self.page, "pages": self.pages, "records": self.records, "seen_cursors": self.seen_cursors,
                "last_signature": self.last_signature, "done": self.done}

    @classmethod
    def from_json(cls, data: dict | None) -> "PageState":
        data = data or {}
        return cls(cursor=data.get("cursor"), offset=int(data.get("offset") or 0), page=int(data.get("page") or 1), pages=int(data.get("pages") or 0), records=int(data.get("records") or 0),
                   seen_cursors=list(data.get("seen_cursors") or []), last_signature=data.get("last_signature"), done=bool(data.get("done")))


@dataclass
class Page:
    records: list
    state: PageState  # the state AFTER this page (what to save once its records are processed)
    truncated: bool = False  # a configured bound (pages or records) ended the pull while more data was available
    row_numbers: list | None = None  # CSV: the 1-based data row of each record in the file
    malformed: int = 0  # CSV: rows rejected for a wrong number of cells or invalid quoting


class RestRecordsSource:
    def __init__(self, http: HttpConnector, cfg: RecordsConfig, *, tenant_id, connector_id, stop: threading.Event | None = None, sleep=None):
        self.http, self.cfg, self.tenant_id, self.connector_id, self.stop = http, cfg, tenant_id, connector_id, stop or threading.Event()
        self.bucket = LIMITERS.get(tenant_id, connector_id, cfg.rate.requests_per_second, cfg.rate.burst)
        self._sleep = sleep or (lambda s: self.stop.wait(s))

    # -- one request: rate limited, bounded retries for 429 and transient errors
    def _get(self, path: str) -> dict:
        last: ConnectorError | None = None
        for attempt in range(PAGE_ATTEMPTS):
            try:
                self.bucket.acquire(MAX_WAIT_SECONDS, self.stop)
            except RateLimited as exc:
                raise SourceError("source_rate_limited", transient=True) from exc
            try:
                return self.http.request("GET", path)
            except ConnectorError as exc:
                last = exc
                if exc.kind != TRANSIENT or attempt == PAGE_ATTEMPTS - 1:
                    break
                if exc.retry_after is not None:
                    self.bucket.pause(exc.retry_after)  # the upstream said when to come back: nobody (this connector) asks before then
                else:
                    self._sleep(min(0.2 * (2 ** attempt), 2.0))
        raise _classify(last) from last

    def _params(self, state: PageState) -> dict:
        p, params = self.cfg.pagination, {}
        if p.mode == "none":
            return params
        params[p.limit_param] = p.page_size
        if p.mode == "cursor" and state.cursor:
            params[p.cursor_param] = state.cursor
        elif p.mode == "offset":
            params[p.offset_param] = state.offset
        elif p.mode == "page":
            params[p.page_param] = state.page
        return params

    def fetch_page(self, state: PageState) -> Page:
        cfg, p = self.cfg, self.cfg.pagination
        if state.pages >= cfg.max_pages or state.records >= cfg.max_records:
            return Page([], PageState(**{**state.__dict__, "done": True}), truncated=True)
        query = urlencode(self._params(state))
        body = self._get(cfg.path + ("?" + query if query else ""))
        raw = body.get(cfg.record_path)
        if not isinstance(raw, list):
            raise SourceError("source_schema_invalid")
        records = raw[: max(0, cfg.max_records - state.records)]
        signature = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()[:16]
        new = PageState(cursor=state.cursor, offset=state.offset, page=state.page, pages=state.pages + 1, records=state.records + len(records), seen_cursors=list(state.seen_cursors),
                        last_signature=signature)
        if raw and signature == state.last_signature:
            raise SourceError("pagination_loop")  # the source returned exactly the previous page again
        capped = len(raw) > len(records)
        more = False
        if p.mode == "cursor":
            token = body.get(p.next_cursor_field)
            flagged = bool(body.get(p.has_more_field)) if p.has_more_field else None
            if token in (None, ""):
                if flagged:
                    raise SourceError("missing_continuation")
            else:
                if not isinstance(token, str) or not CURSOR.match(token):
                    raise SourceError("invalid_cursor")
                if token == state.cursor or token in state.seen_cursors:
                    raise SourceError("pagination_loop")
                new.cursor, more = token, True
                new.seen_cursors = (state.seen_cursors + [token])[-cfg.max_pages:]
        elif p.mode in ("offset", "page"):
            total = body.get(p.total_field) if p.total_field else None
            if total is not None and (not isinstance(total, int) or isinstance(total, bool) or total < 0):
                raise SourceError("source_schema_invalid")
            if p.mode == "offset":
                new.offset = state.offset + len(raw)
                more = bool(raw) and len(raw) >= p.page_size and (total is None or new.offset < total)
            else:
                new.page = state.page + 1
                more = bool(raw) and len(raw) >= p.page_size and (total is None or state.page * p.page_size < total)
        truncated = bool(more or capped) and (new.pages >= cfg.max_pages or new.records >= cfg.max_records)
        new.done = not more or truncated or capped
        return Page(records, new, truncated=truncated or capped)

    # -- the opt-in health probe: one bounded request, nothing ingested, nothing changed upstream
    def probe(self) -> dict:
        started = time.perf_counter()
        p = self.cfg.pagination
        params = {p.limit_param: 1} if p.mode != "none" else {}
        path = self.cfg.path + ("?" + urlencode(params) if params else "")
        status, http_status = "ok", None
        try:
            self.bucket.acquire(min(2.0, MAX_WAIT_SECONDS), self.stop)
            body = self.http.request("GET", path)
            if not isinstance(body.get(self.cfg.record_path), list):
                status = "schema"
        except RateLimited:
            status = "rate_limited"
        except ConnectorError as exc:
            http_status = exc.status
            status = _probe_class(exc)
        return {"status": status, "http_status": http_status, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}


def _probe_class(exc: ConnectorError) -> str:
    if exc.kind == PERMANENT and "destination not permitted" in str(exc):
        return "denied"
    if exc.status in (401, 403):
        return "authentication"
    if exc.status == 429:
        return "rate_limited"
    if exc.kind == MALFORMED:
        return "schema"
    if exc.status is not None and exc.status >= 500:
        return "upstream_error"
    if exc.kind == TRANSIENT:
        return "connectivity"
    return "upstream_error"


def _classify(exc: ConnectorError | None) -> SourceError:
    if exc is None:
        return SourceError("source_unavailable", transient=True)
    if exc.kind == PERMANENT and "destination not permitted" in str(exc):
        return SourceError("egress_denied")
    if exc.status in (401, 403):
        return SourceError("source_unauthorized")
    if exc.kind == MALFORMED:
        return SourceError("source_schema_invalid")
    if exc.status == 429:
        return SourceError("source_rate_limited", transient=True)
    if exc.kind == TRANSIENT:
        return SourceError("source_unavailable", transient=True)
    return SourceError("source_rejected")


def build_source(row, cfg: RecordsConfig, *, tenant_slug: str | None, timeout: float = 5.0, stop: threading.Event | None = None) -> RestRecordsSource:
    """The source for a connector row. A connector that names a secret which is not set fails here, before any request (nothing is sent without its credentials)."""
    key = resolve_secret(row.secret_ref)
    if row.secret_ref and not key:
        raise SourceError("credentials_missing")
    http = HttpConnector(row.base_url, api_key=key, timeout=timeout, tenant_slug=tenant_slug, tenant_id=str(row.tenant_id))
    return RestRecordsSource(http, cfg, tenant_id=row.tenant_id, connector_id=row.id, stop=stop)


# ------------------------------------------------------------------------------------------------------------------------------------ records
class RecordInvalid(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_record(record, cfg: RecordsConfig) -> tuple[str, str | None, bytes]:
    """(source record id, version marker or None, canonical bytes). Raises RecordInvalid with a fixed reason; the source's ids are never invented."""
    if not isinstance(record, dict):
        raise RecordInvalid("not_an_object")
    rid = record.get(cfg.id_field)
    if isinstance(rid, bool) or not isinstance(rid, (str, int)) or not RECORD_ID.match(str(rid)):
        raise RecordInvalid("invalid_id")
    for name in cfg.required_fields:
        if record.get(name) in (None, ""):
            raise RecordInvalid("missing_required_field")
    version = None
    if cfg.version_field:
        v = record.get(cfg.version_field)
        version = None if v is None else str(v)[:64]
    data = json.dumps([record], sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    if len(data) > cfg.max_record_bytes:
        raise RecordInvalid("record_too_large")
    return str(rid), version, data


def document_name(connector_name: str, record_id: str, prefix: str = "rest") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", connector_name)[:40]
    return f"{prefix}-{safe}-{re.sub(r'[^A-Za-z0-9._-]', '-', record_id)[:100]}.json"


# ------------------------------------------------------------------------------------------------------------------------------------ CSV source (Batch 11B)
class CsvConfig(BaseModel):
    """`config.csv` of a connector of kind `csv`: one CSV file fetched over HTTP (GET) from the connector's own base URL, one document per data row."""
    model_config = ConfigDict(extra="forbid")
    path: str
    id_field: str
    version_field: str | None = None
    required_fields: list[str] = Field(default_factory=list, max_length=20)
    document_kind: str = "other"
    max_rows: int = Field(default=1000, ge=1, le=5000)
    max_bytes: int = Field(default=1048576, ge=1024, le=5242880)
    max_record_bytes: int = Field(default=65536, ge=256, le=262144)
    max_cell_bytes: int = Field(default=8192, ge=16, le=65536)
    delimiter: str = Field(default=",", pattern="^(,|;|\\t)$")
    reject_policy: str = Field(default="skip", pattern="^(skip|fail)$")
    rate: Rate = Field(default_factory=Rate)

    @model_validator(mode="after")
    def _safe(self):
        if not safe_path(self.path):
            raise ValueError("path must be a relative path starting with '/'")
        for name in (self.id_field, self.version_field, *self.required_fields):
            if name is not None and not HEADER.match(name):
                raise ValueError("invalid field name")
        return self


HEADER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\- ]{0,59}$")


def parse_csv_config(connector_config: dict | None) -> CsvConfig:
    raw = (connector_config or {}).get("csv")
    if not isinstance(raw, dict):
        raise Invalid("This connector has no CSV configuration", code="invalid_connector_config", status_code=422)
    try:
        return CsvConfig.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "csv" for e in exc.errors()})
        raise Invalid(f"Invalid CSV configuration (check: {', '.join(fields)})", code="invalid_connector_config", status_code=422) from exc


def parse_csv_records(data: bytes, cfg: CsvConfig) -> tuple[list[tuple[int, dict]], dict]:
    """Deterministic, bounded CSV parsing: (row number, record) pairs and counts. Row numbers are 1-based data rows in the file (the header is row 0).

    Only UTF-8 (with or without a byte-order mark) is accepted; NUL bytes, a missing or duplicate header, a missing id column, rows with the wrong number of cells, oversize cells and rows
    beyond `max_rows` are handled by fixed rules (rejected and counted, never guessed). Cell values stay text; nothing is evaluated (a leading `=`, `+`, `-` or `@` is data, never a formula:
    the platform never writes CSV or spreadsheets from this content)."""
    import csv
    import io
    if b"\x00" in data:
        raise SourceError("source_schema_invalid")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError("source_schema_invalid") from exc
    csv.field_size_limit(cfg.max_cell_bytes)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=cfg.delimiter, strict=True)
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise SourceError("source_schema_invalid") from exc
    header = [h.strip() for h in header]
    if len(set(header)) != len(header) or not all(HEADER.match(h) for h in header) or cfg.id_field not in header:
        raise SourceError("source_schema_invalid")
    records, stats, row_no = [], {"malformed": 0, "blank": 0, "truncated": False}, 0
    while True:
        try:
            cells = next(reader)
        except StopIteration:
            break
        except csv.Error:
            row_no += 1
            stats["malformed"] += 1
            if row_no > cfg.max_rows * 2:
                stats["truncated"] = True
                break
            continue
        row_no += 1
        if not cells or all(c == "" for c in cells):
            stats["blank"] += 1
            continue
        if len(records) >= cfg.max_rows:
            stats["truncated"] = True
            break
        if len(cells) != len(header):
            stats["malformed"] += 1
            continue
        records.append((row_no, dict(zip(header, cells, strict=True))))
    return records, stats


class CsvSource:
    """Pull of one CSV file. It exposes the same `fetch_page` and `probe` shape as RestRecordsSource: the whole (bounded) file is one page."""

    def __init__(self, http: HttpConnector, cfg: CsvConfig, *, tenant_id, connector_id, stop: threading.Event | None = None, sleep=None):
        self.http, self.cfg, self.tenant_id, self.connector_id, self.stop = http, cfg, tenant_id, connector_id, stop or threading.Event()
        self.bucket = LIMITERS.get(tenant_id, connector_id, cfg.rate.requests_per_second, cfg.rate.burst)
        self._sleep = sleep or (lambda s: self.stop.wait(s))

    def _get(self) -> bytes:
        last: ConnectorError | None = None
        for attempt in range(PAGE_ATTEMPTS):
            try:
                self.bucket.acquire(MAX_WAIT_SECONDS, self.stop)
            except RateLimited as exc:
                raise SourceError("source_rate_limited", transient=True) from exc
            try:
                return self.http.request("GET", self.cfg.path, raw=True, max_bytes=self.cfg.max_bytes)
            except ConnectorError as exc:
                last = exc
                if exc.kind != TRANSIENT or attempt == PAGE_ATTEMPTS - 1:
                    break
                if exc.retry_after is not None:
                    self.bucket.pause(exc.retry_after)
                else:
                    self._sleep(min(0.2 * (2 ** attempt), 2.0))
        raise _classify(last) from last

    def fetch_page(self, state: PageState) -> Page:
        if state.done:
            return Page([], state)
        records, stats = parse_csv_records(self._get(), self.cfg)
        new = PageState(pages=1, records=len(records), done=True)
        page = Page([r for _, r in records], new, truncated=stats["truncated"])
        page.row_numbers = [n for n, _ in records]
        page.malformed = stats["malformed"]
        return page

    def probe(self) -> dict:
        started = time.perf_counter()
        status, http_status = "ok", None
        try:
            self.bucket.acquire(min(2.0, MAX_WAIT_SECONDS), self.stop)
            data = self.http.request("GET", self.cfg.path, raw=True, max_bytes=min(self.cfg.max_bytes, 65536))
            head = data.split(b"\n", 1)[0].decode("utf-8-sig", errors="replace")
            if self.cfg.id_field not in [h.strip() for h in head.rstrip("\r").split(self.cfg.delimiter)]:
                status = "schema"
        except RateLimited:
            status = "rate_limited"
        except ConnectorError as exc:
            http_status = exc.status
            status = "schema" if (exc.kind == MALFORMED and "size limit" in str(exc)) else _probe_class(exc)
        return {"status": status, "http_status": http_status, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}


def build_csv_source(row, cfg: CsvConfig, *, tenant_slug: str | None, timeout: float = 5.0, stop: threading.Event | None = None) -> CsvSource:
    key = resolve_secret(row.secret_ref)
    if row.secret_ref and not key:
        raise SourceError("credentials_missing")
    http = HttpConnector(row.base_url, api_key=key, timeout=timeout, tenant_slug=tenant_slug, tenant_id=str(row.tenant_id))
    return CsvSource(http, cfg, tenant_id=row.tenant_id, connector_id=row.id, stop=stop)
