import { describe, expect, it } from "vitest";
import { defaultPath, PAGES } from "../nav";
import { can, isPlatformAdmin } from "./rbac";
import { signIn } from "../../tests/utils";

const labels = (role: string) => PAGES.filter((p) => p.visible(signIn(role))).map((p) => p.label);

describe("role-aware navigation (usability only; the server enforces access)", () => {
  it("defines exactly the 13 specified pages in order", () => {
    expect(PAGES.map((p) => p.label)).toEqual([
      "Overview", "Customer Onboarding", "Data Sources", "Document Library", "AI Knowledge Assistant", "Incident Explorer", "Support Tickets",
      "Approval Queue", "Workflow History", "Integration Health", "Evaluation Dashboard", "Audit Logs", "Administration",
    ]);
  });

  it("shows tenant administrators all 13 pages", () => expect(labels("tenant_admin")).toHaveLength(13));
  it("hides Audit Logs and Administration from engineers and supervisors", () => {
    for (const role of ["support_engineer", "maintenance_supervisor"]) {
      expect(labels(role)).toHaveLength(11);
      expect(labels(role)).not.toContain("Audit Logs");
      expect(labels(role)).not.toContain("Administration");
    }
  });
  it("shows auditors the audit log but not administration", () => {
    expect(labels("read_only_auditor")).toContain("Audit Logs");
    expect(labels("read_only_auditor")).not.toContain("Administration");
  });
  it("gives platform administrators only Administration", () => {
    expect(labels("platform_admin")).toEqual(["Administration"]);
    expect(defaultPath(signIn("platform_admin"))).toBe("/administration");
    expect(isPlatformAdmin("platform_admin")).toBe(true);
  });
  it("mirrors the permission table for the controls that matter", () => {
    expect(can("support_engineer", "approvals:decide")).toBe(false);
    expect(can("maintenance_supervisor", "approvals:decide")).toBe(true);
    expect(can("support_engineer", "incidents:review")).toBe(false);
    expect(can("read_only_auditor", "tickets:write")).toBe(false);
    expect(can("maintenance_supervisor", "members:write")).toBe(false);
  });
});
