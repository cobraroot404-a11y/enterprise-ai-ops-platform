/**
 * Mirror of the backend role/permission table, used ONLY to decide what to show. The server enforces every
 * permission independently on every request; hiding a control here is a usability aid, never a security control.
 */
export type Permission =
  | "documents:write"
  | "incidents:write"
  | "incidents:review"
  | "tickets:write"
  | "tickets:retry"
  | "approvals:decide"
  | "audit:read"
  | "connectors:read"
  | "connectors:write"
  | "connectors:sync"
  | "webhooks:write"
  | "members:write"
  | "profile:write";

const ADMIN = "tenant_admin";
const SUP = "maintenance_supervisor";
const ENG = "support_engineer";
const AUD = "read_only_auditor";

const TABLE: Record<Permission, string[]> = {
  "documents:write": [ADMIN, SUP, ENG],
  "incidents:write": [ADMIN, SUP, ENG],
  "incidents:review": [ADMIN, SUP],
  "tickets:write": [ADMIN, SUP, ENG],
  "tickets:retry": [ADMIN, SUP],
  "approvals:decide": [ADMIN, SUP],
  "audit:read": [ADMIN, AUD],
  "connectors:read": [ADMIN],
  "connectors:write": [ADMIN],
  "connectors:sync": [ADMIN, SUP],
  "webhooks:write": [ADMIN],
  "members:write": [ADMIN],
  "profile:write": [ADMIN],
};

export const can = (role: string, permission: Permission): boolean => TABLE[permission].includes(role);
export const isPlatformAdmin = (role: string): boolean => role === "platform_admin";

export const ROLE_LABELS: Record<string, string> = {
  tenant_admin: "Tenant administrator",
  maintenance_supervisor: "Maintenance supervisor",
  support_engineer: "Support engineer",
  read_only_auditor: "Read-only auditor",
  platform_admin: "Platform administrator",
};
