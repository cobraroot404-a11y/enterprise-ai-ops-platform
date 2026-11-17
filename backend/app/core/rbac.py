"""Role-based access control. Enforced server-side on every route."""

PLATFORM_ADMIN = "platform_admin"
TENANT_ADMIN = "tenant_admin"
SUPERVISOR = "maintenance_supervisor"
SUPPORT = "support_engineer"
AUDITOR = "read_only_auditor"

TENANT_ROLES = {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR}

PERMISSIONS: dict[str, set[str]] = {
    "documents:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "documents:write": {TENANT_ADMIN, SUPERVISOR, SUPPORT},
    "documents:delete": {TENANT_ADMIN, SUPERVISOR},
    "documents:reprocess": {TENANT_ADMIN, SUPERVISOR},
    "search:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "incidents:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "incidents:write": {TENANT_ADMIN, SUPERVISOR, SUPPORT},
    "incidents:review": {TENANT_ADMIN, SUPERVISOR},
    "tickets:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "tickets:write": {TENANT_ADMIN, SUPERVISOR, SUPPORT},
    "tickets:retry": {TENANT_ADMIN, SUPERVISOR},
    "approvals:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "approvals:decide": {TENANT_ADMIN, SUPERVISOR},
    "audit:read": {TENANT_ADMIN, AUDITOR},
    "metrics:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "workflows:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "connectors:read": {TENANT_ADMIN},
    "connectors:write": {TENANT_ADMIN},
    "connectors:sync": {TENANT_ADMIN, SUPERVISOR},
    "webhooks:read": {TENANT_ADMIN},
    "webhooks:write": {TENANT_ADMIN},
    "members:write": {TENANT_ADMIN},
    "profile:read": {TENANT_ADMIN, SUPERVISOR, SUPPORT, AUDITOR},
    "profile:write": {TENANT_ADMIN},
}


def can(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
