"""Profile-driven, read-only enrichment lookups. They add notes to an incident; they never decide priority and
a failing lookup never blocks the incident."""
import re
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.clients import RestClient
from app.connectors.egress import tenant_slug
from app.connectors.http import ConnectorError
from app.models import Connector
from app.profile.schema import TenantProfile

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _render(template: str, body: dict) -> str:
    def value(match):
        v = body.get(match.group(1))
        return str(v)[:100] if isinstance(v, (str, int, float, bool)) else "n/a"

    return _PLACEHOLDER.sub(value, template)


def run_enrichments(session: Session, tenant_id, profile: TenantProfile, asset_id: str) -> list[str]:
    if not profile.enrichments:
        return []
    rows = {c.kind: c for c in session.scalars(select(Connector).where(Connector.tenant_id == tenant_id))}
    slug = tenant_slug(session, tenant_id)
    notes = []
    for item in profile.enrichments:
        row = rows.get(item.connector_kind)
        if row is None:
            notes.append(f"{item.label}: no {item.connector_kind} connector configured; lookup skipped.")
            continue
        path = item.path.replace("{asset_id}", quote(asset_id, safe=""))
        try:
            body = RestClient.from_row(row, tenant_slug=slug).get(path)
        except ConnectorError as exc:
            notes.append(f"{item.label} lookup failed ({exc.kind})")
            continue
        if any(field not in body for field in item.required_fields):
            notes.append(f"{item.label} lookup failed (malformed response)")
            continue
        notes.append(f"{_render(item.template, body)}")
    return notes
