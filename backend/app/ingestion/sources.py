"""Controlled storage of the ORIGINAL uploaded content (migration 0011; V41-12.03, V41-12.04).

Storage is the `document_sources` table in PostgreSQL: it commits atomically with the job and the document, is covered by the existing backups, sits under the same row-level security
as every tenant table, and is removed by the existing deletion cleanup. There is no file path anywhere (nothing for a client to forge), no download route, and the bytes are
reachable only through tenant-scoped sessions of the server and the worker. Content is immutable once stored and its SHA-256 is re-verified every time it is read."""
import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import DocumentSource


class SourceMissing(AppError):
    status_code = 409
    code = "source_missing"


class SourceCorrupted(AppError):
    status_code = 409
    code = "source_corrupted"


@dataclass
class SourceContent:
    id: uuid.UUID
    filename: str
    kind: str
    media_type: str
    size_bytes: int
    content_hash: str
    parse_options: dict
    data: bytes


def store(session: Session, *, tenant_id, filename: str, kind: str, media_type: str, data: bytes, content_hash: str, parse_options: dict | None = None) -> uuid.UUID:
    """Persist the original bytes inside the caller's transaction. The hash is recomputed here: a caller can not store content under another content's hash."""
    if hashlib.sha256(data).hexdigest() != content_hash:
        raise SourceCorrupted("The content does not match its checksum")
    source = DocumentSource(tenant_id=tenant_id, filename=filename, kind=kind, media_type=media_type, size_bytes=len(data), content_hash=content_hash,
                            parse_options=parse_options or {}, content=data)
    session.add(source)
    session.flush()
    return source.id


def load(session: Session, *, tenant_id, source_id) -> SourceContent:
    """Read a source of THIS tenant and verify its integrity. An unknown id, another tenant's id and a removed source are all `source_missing`; changed bytes are `source_corrupted`."""
    source = session.scalar(select(DocumentSource).where(DocumentSource.id == source_id, DocumentSource.tenant_id == tenant_id))
    if source is None:
        raise SourceMissing("The original content is no longer available")
    data = bytes(source.content)
    if len(data) != source.size_bytes or hashlib.sha256(data).hexdigest() != source.content_hash:
        raise SourceCorrupted("The retained original content failed its integrity check")
    return SourceContent(source.id, source.filename, source.kind, source.media_type, source.size_bytes, source.content_hash, source.parse_options or {}, data)


def link(session: Session, *, tenant_id, source_id, document_id, version: int) -> None:
    session.execute(update(DocumentSource).where(DocumentSource.id == source_id, DocumentSource.tenant_id == tenant_id).values(document_id=document_id, version=version))


def release(session: Session, *, tenant_id, source_id) -> int:
    """Remove a source that is NOT linked to a document version (a cancelled, duplicate or permanently failed job). A linked source is never removed here."""
    if source_id is None:
        return 0
    return session.execute(delete(DocumentSource).where(DocumentSource.id == source_id, DocumentSource.tenant_id == tenant_id, DocumentSource.document_id.is_(None))).rowcount


def purge_document(session: Session, *, tenant_id, document_id) -> int:
    """Deletion cleanup: remove every retained source of the document (all versions). Tenant predicate included besides RLS."""
    return session.execute(delete(DocumentSource).where(DocumentSource.document_id == document_id, DocumentSource.tenant_id == tenant_id)).rowcount


def remaining(session: Session, *, tenant_id, document_id) -> int:
    return session.scalar(select(func.count()).select_from(DocumentSource).where(DocumentSource.document_id == document_id, DocumentSource.tenant_id == tenant_id)) or 0
