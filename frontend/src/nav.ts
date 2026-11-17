import type { Session } from "./types";
import { can, isPlatformAdmin } from "./services/rbac";

export interface PageDef {
  id: string;
  path: string;
  label: string;
  /** Usability visibility only; the API enforces access independently. */
  visible: (s: Session) => boolean;
  deniedMessage?: string;
}

const tenantUser = (s: Session) => !isPlatformAdmin(s.role);

/** The 13 pages of the V4.1 specification, in specification order. */
export const PAGES: PageDef[] = [
  { id: "overview", path: "/overview", label: "Overview", visible: tenantUser },
  { id: "onboarding", path: "/onboarding", label: "Customer Onboarding", visible: tenantUser },
  { id: "data-sources", path: "/data-sources", label: "Data Sources", visible: tenantUser },
  { id: "documents", path: "/documents", label: "Document Library", visible: tenantUser },
  { id: "assistant", path: "/assistant", label: "AI Knowledge Assistant", visible: tenantUser },
  { id: "incidents", path: "/incidents", label: "Incident Explorer", visible: tenantUser },
  { id: "tickets", path: "/tickets", label: "Support Tickets", visible: tenantUser },
  { id: "approvals", path: "/approvals", label: "Approval Queue", visible: tenantUser },
  { id: "workflows", path: "/workflows", label: "Workflow History", visible: tenantUser },
  { id: "integrations", path: "/integrations", label: "Integration Health", visible: tenantUser },
  { id: "evaluation", path: "/evaluation", label: "Evaluation Dashboard", visible: tenantUser },
  {
    id: "audit",
    path: "/audit",
    label: "Audit Logs",
    visible: (s) => tenantUser(s) && can(s.role, "audit:read"),
    deniedMessage: "Audit logs are available to tenant administrators and read-only auditors.",
  },
  {
    id: "administration",
    path: "/administration",
    label: "Administration",
    visible: (s) => isPlatformAdmin(s.role) || can(s.role, "members:write"),
    deniedMessage: "Administration is available to tenant administrators and platform administrators.",
  },
];

export const defaultPath = (s: Session): string => (isPlatformAdmin(s.role) ? "/administration" : "/overview");
