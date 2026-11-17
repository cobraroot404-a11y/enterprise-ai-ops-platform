"""Typed clients for the ticketing and inventory systems."""
from app.connectors.http import MALFORMED, ConnectorError, HttpConnector, resolve_secret


def _from_row(row, timeout: float, tenant_slug: str | None) -> HttpConnector:
    return HttpConnector(row.base_url, api_key=resolve_secret(row.secret_ref), timeout=timeout,
                         tenant_slug=tenant_slug, tenant_id=str(row.tenant_id))


class TicketingClient:
    """Submits to the tenant's ticketing system. The API contract is connector CONFIG, not code:
    create_path, id_field, payload_map (canonical field -> remote field) and priority_map (P1..P4 -> remote
    values). With an empty config the original maintenance-ticketing contract is used."""

    def __init__(self, connector: HttpConnector, config: dict | None = None):
        self.connector = connector
        self.config = config or {}

    @classmethod
    def from_row(cls, row, *, tenant_slug: str | None, timeout: float = 5.0) -> "TicketingClient":
        return cls(_from_row(row, timeout, tenant_slug), row.config or {})

    def _remote_payload(self, payload: dict) -> dict:
        mapping = self.config.get("payload_map")
        if not mapping:
            return payload
        priorities = self.config.get("priority_map") or {}
        return {mapping[k]: (priorities.get(v, v) if k == "priority" else v)
                for k, v in payload.items() if k in mapping}

    def create_ticket(self, payload: dict, idempotency_key: str) -> str:
        body = self.connector.request("POST", self.config.get("create_path", "/tickets"),
                                      json=self._remote_payload(payload), headers={"Idempotency-Key": idempotency_key})
        id_field = self.config.get("id_field", "ticket_id")
        ticket_id = body.get(id_field)
        if not isinstance(ticket_id, str) or not ticket_id:
            raise ConnectorError(f"response missing {id_field}", MALFORMED)
        return ticket_id


class RestClient:
    """Read-only GET lookups for profile enrichments (fleet telematics, CRM, ...)."""

    def __init__(self, connector: HttpConnector):
        self.connector = connector

    @classmethod
    def from_row(cls, row, *, tenant_slug: str | None, timeout: float = 3.0) -> "RestClient":
        return cls(_from_row(row, timeout, tenant_slug))

    def get(self, path: str) -> dict:
        return self.connector.request("GET", path)


class InventoryClient:
    def __init__(self, connector: HttpConnector):
        self.connector = connector

    @classmethod
    def from_row(cls, row, *, tenant_slug: str | None, timeout: float = 3.0) -> "InventoryClient":
        return cls(_from_row(row, timeout, tenant_slug))

    def get_part(self, part_number: str) -> dict:
        body = self.connector.request("GET", f"/parts/{part_number}")
        if "quantity_on_hand" not in body:
            raise ConnectorError("inventory response missing quantity_on_hand", MALFORMED)
        return body
