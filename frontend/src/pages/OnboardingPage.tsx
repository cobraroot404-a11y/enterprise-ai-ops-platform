import { useState } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import { Badge, Card, fmtTime, KeyValues, Notice, PageHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import type { AsyncState } from "../hooks/useAsync";
import { api, put } from "../services/api";
import { can } from "../services/rbac";
import type { OnboardingHealth, Session, TenantProfileInfo } from "../types";

export default function OnboardingPage({ session }: { session: Session }) {
  const health = useAsync(() => api<OnboardingHealth>("/onboarding/health"), []);
  const profile = useAsync(() => api<TenantProfileInfo>("/tenant-profile"), []);
  const canEdit = can(session.role, "profile:write");
  const [saved, setSaved] = useState<string | null>(null);
  const p = profile.data?.profile;

  return (
    <section aria-labelledby="onb-h">
      <PageHeader
        title="Customer Onboarding"
        intro="A customer is onboarded through configuration: a domain profile, connectors, members and documents. No application code changes are involved."
        actions={<button className="secondary" onClick={() => { health.reload(); profile.reload(); }}>Refresh</button>}
      />
      <HealthCard health={health} />
      <Card title="Domain profile" id="onb-profile">
        <Status state={profile} label="profile" />
        {profile.data && <ProfileSummary info={profile.data} />}
        {saved && <Notice tone="ok" onDismiss={() => setSaved(null)}>{saved}</Notice>}
        {canEdit && p && (
          <ProfileEditor
            key={profile.data?.version}
            initial={JSON.stringify(p, null, 2)}
            onSaved={(version) => { setSaved(`Profile saved as version ${version}.`); profile.reload(); health.reload(); }}
          />
        )}
        {!canEdit && <p className="muted small">Only tenant administrators can change the profile.</p>}
      </Card>
    </section>
  );
}

function HealthCard({ health }: { health: AsyncState<OnboardingHealth> }) {
  return (
    <Card title="Onboarding health checks" id="onb-health">
      <Status state={health} label="health checks" />
      {health.data && (
        <>
          <p><Badge tone={health.data.passed === health.data.total ? "ok" : "warn"}>{health.data.passed} of {health.data.total} checks passing</Badge></p>
          <ul className="checklist" aria-label="Checks">
            {health.data.checks.map((c) => (
              <li key={c.id}>
                <span className={c.status === "pass" ? "ok" : c.status === "fail" ? "error" : "muted"} aria-hidden="true">{c.status === "pass" ? "✓" : c.status === "fail" ? "✗" : "–"}</span>{" "}
                <strong>{c.label}</strong> <span className="sr-only">{c.status}</span>
                <div className="muted small">{c.detail}</div>
              </li>
            ))}
          </ul>
          <p className="muted small">Each check reads real configuration and records. Connector checks are visible to tenant administrators only.</p>
        </>
      )}
    </Card>
  );
}

function ProfileSummary({ info }: { info: TenantProfileInfo }) {
  const p = info.profile;
  return (
    <KeyValues rows={[
      ["Source", info.using_defaults ? "Platform defaults (equipment maintenance); no tenant profile saved" : `Tenant profile, version ${info.version}`],
      ["Last updated", fmtTime(info.updated_at)],
      ...(p ? ([
        ["Asset wording", p.asset_label],
        ["Authoritative register kind", p.register_kind],
        ["Guidance document kinds", p.guidance_kinds.join(", ")],
        ["History document kind", p.history_kind ?? "–"],
        ["Categories", (p.categories ?? []).map((c) => c.name).join(", ") || "–"],
        ["Numeric signals", (p.signals ?? []).map((s) => `${s.name}${s.unit ? ` (${s.unit})` : ""}`).join(", ") || "–"],
        ["Deterministic priority rules", `${(p.priority_rules ?? []).length} rule(s), default ${p.default_priority ?? "P4"}`],
        ["Read-only enrichments", (p.enrichments ?? []).map((e) => `${e.label} (${e.connector_kind})`).join(", ") || "–"],
      ] as [string, string][]) : []),
    ]} />
  );
}

function ProfileEditor({ initial, onSaved }: { initial: string; onSaved: (version: number) => void }) {
  const [draft, setDraft] = useState(initial);
  const [parseError, setParseError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  function validateLocally(): unknown | null {
    try {
      const parsed = JSON.parse(draft);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("The profile must be a JSON object.");
      setParseError(null);
      return parsed;
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "Invalid JSON");
      return null;
    }
  }

  async function save() {
    const parsed = validateLocally();
    if (!parsed) { setConfirm(false); return; }
    setBusy(true);
    setSaveError(null);
    try {
      const res = await put<{ version: number }>("/tenant-profile", parsed);
      onSaved(res.version);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <>
      <form onSubmit={(e) => { e.preventDefault(); if (validateLocally()) setConfirm(true); }} aria-label="Edit profile">
        <label htmlFor="profile-json">Profile (JSON)</label>
        <textarea id="profile-json" rows={14} spellCheck={false} className="mono" value={draft} onChange={(e) => setDraft(e.target.value)}
          aria-invalid={parseError ? true : undefined} aria-describedby="profile-help" />
        <p id="profile-help" className="muted small">The server validates every field (regular expressions, rule references, kinds). Priority is always decided by these deterministic rules, never by the model.</p>
        {parseError && <p role="alert" className="error">{parseError}</p>}
        {saveError && <p role="alert" className="error">{saveError}</p>}
        <button type="submit">Validate and save…</button>
      </form>
      <ConfirmDialog open={confirm} title="Replace the domain profile?" confirmLabel="Save profile" busy={busy} onConfirm={() => void save()} onCancel={() => setConfirm(false)}>
        <p>This replaces the profile used for new incident extractions, priorities and document mappings. The change is audited and creates a new version. Existing incidents and tickets are not changed.</p>
      </ConfirmDialog>
    </>
  );
}
