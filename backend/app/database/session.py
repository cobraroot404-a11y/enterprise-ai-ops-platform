"""Engines and tenant-scoped sessions.

Tenant context is applied with set_config(..., is_local=true) at the start of every transaction, so it
is discarded on COMMIT/ROLLBACK and can never leak to another request through the connection pool.
"""
import uuid

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session, transaction, connection):
    tenant_id = session.info.get("tenant_id")
    if tenant_id:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    user_id = session.info.get("user_id")
    if user_id:
        connection.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


class Database:
    def __init__(self, settings: Settings | None = None, role: str = "app", pool_size: int = 5,
                 max_overflow: int = 5):
        self.settings = settings or get_settings()
        self.engine = create_engine(
            self.settings.url(role), pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True
        )
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    def session(self, tenant_id: uuid.UUID | str | None = None,
                user_id: uuid.UUID | str | None = None) -> Session:
        session = self._factory()
        if tenant_id:
            session.info["tenant_id"] = str(tenant_id)
        if user_id:
            session.info["user_id"] = str(user_id)
        return session

    def dispose(self) -> None:
        self.engine.dispose()
