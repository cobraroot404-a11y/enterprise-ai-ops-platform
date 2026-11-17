"""Structured JSON logging with redaction. Never log secrets, tokens, passwords, credentials or document contents."""

import json
import logging
import re

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|api[_-]?key|credential|cookie|bearer)", re.IGNORECASE
)
_VALUE_PATTERNS = [
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), "[REDACTED-JWT]"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(x-api-key|authorization)\s*:\s*\S+"), r"\1: [REDACTED]"),
]
MAX_VALUE_CHARS = 500


def redact_value(value):
    if isinstance(value, str):
        for pattern, replacement in _VALUE_PATTERNS:
            value = pattern.sub(replacement, value)
        return value if len(value) <= MAX_VALUE_CHARS else value[:MAX_VALUE_CHARS] + "...[truncated]"
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SENSITIVE_KEY.search(str(k)) else redact_value(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value][:50]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_value(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED:
                continue
            payload[key] = "[REDACTED]" if _SENSITIVE_KEY.search(key) else redact_value(value)
        if "trace_id" not in payload:
            from app.observability.tracing import current

            if current():
                payload["trace_id"] = current()
        if record.exc_info:
            payload["exc"] = redact_value(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("eaop")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """One structured event line: `event` names what happened; fields are technical identifiers and numbers only."""
    logger.log(level, event, extra={"event": event, **fields})
