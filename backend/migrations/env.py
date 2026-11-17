from alembic import context
from app.core.config import get_settings
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    return config.attributes.get("url") or get_settings().url("owner")


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
