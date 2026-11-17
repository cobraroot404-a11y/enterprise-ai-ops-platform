import { useState } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import { Badge, Card, Field, fmtTime, KeyValues, Notice, PageHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, del, patch, post } from "../services/api";
import { can, isPlatformAdmin, ROLE_LABELS } from "../services/rbac";
import type { Member, Session } from "../types";

const ROLES = ["tenant_admin", "maintenance_supervisor", "support_engineer", "read_only_auditor"];
type Pending = { kind: "role"; member: Member; role: string } | { kind: "remove"; member: Member } | { kind: "add" } | { kind: "tenant" } | null;

export default function AdministrationPage({ session }: { session: Session }) {
  return (
    <section aria-labelledby="adm-h">
      <PageHeader title="Administration" intro={isPlatformAdmin(session.role) ? "Platform administration: create customer tenants and review platform sign-ins." : "Manage who can use this tenant and what they can do. Every change is audited."} />
      {isPlatformAdmin(session.role) ? <PlatformAdmin /> : can(session.role, "members:write") ? <MemberAdmin session={session} /> : null}
    </section>
  );
}

function MemberAdmin({ session }: { session: Session }) {
  const tenantId = session.tenantId ?? "";
  const members = useAsync(() => api<{ items: Member[] }>(`/tenants/${tenantId}/members`), [tenantId]);
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "support_engineer" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<Pending>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  function validate(): boolean {
    const e: Record<string, string> = {};
    if (!/^\S+@\S+\.\S+$/.test(form.email)) e.email = "Enter a valid email address.";
    if (form.full_name.trim().length < 2) e.full_name = "Enter the person's name.";
    if (form.password.length < 10) e.password = "Use at least 10 characters.";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function confirm() {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === "add") {
        await post(`/tenants/${tenantId}/members`, { ...form, full_name: form.full_name.trim() });
        setMessage({ tone: "ok", text: `${form.email} was added as ${ROLE_LABELS[form.role]}.` });
        setForm({ email: "", full_name: "", password: "", role: "support_engineer" });
      } else if (pending.kind === "role") {
        await patch(`/tenants/${tenantId}/members/${pending.member.user_id}`, { role: pending.role });
        setMessage({ tone: "ok", text: `${pending.member.email} is now ${ROLE_LABELS[pending.role]}.` });
      } else if (pending.kind === "remove") {
        await del(`/tenants/${tenantId}/members/${pending.member.user_id}`);
        setMessage({ tone: "ok", text: `${pending.member.email} was removed from this tenant.` });
      }
      members.reload();
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof Error ? err.message : "The change failed" });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <>
      {message && <Notice tone={message.tone} onDismiss={() => setMessage(null)}>{message.text}</Notice>}
      <Card title="Members" id="adm-members">
        <Status state={members} label="members" empty={members.data && members.data.items.length === 0 ? "No members." : undefined} />
        {members.data && members.data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <caption className="sr-only">Members</caption>
              <thead><tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Actions</th></tr></thead>
              <tbody>
                {members.data.items.map((m) => {
                  const self = m.user_id === session.userId;
                  return (
                    <tr key={m.user_id}>
                      <td>{m.full_name}{self && <> <Badge>you</Badge></>}</td><td>{m.email}</td>
                      <td>
                        <label className="sr-only" htmlFor={`role-${m.user_id}`}>Role for {m.email}</label>
                        <select id={`role-${m.user_id}`} value={m.role} disabled={self} onChange={(e) => setPending({ kind: "role", member: m, role: e.target.value })}>
                          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                        </select>
                      </td>
                      <td>{self ? <span className="muted small">You cannot change or remove yourself</span> : <button className="danger small" onClick={() => setPending({ kind: "remove", member: m })}>Remove…</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Add a member" id="adm-add">
        <form onSubmit={(e) => { e.preventDefault(); if (validate()) setPending({ kind: "add" }); }} aria-label="Add member" noValidate>
          <div className="row">
            <Field label="Email" error={errors.email}>{(p) => <input {...p} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} autoComplete="off" />}</Field>
            <Field label="Full name" error={errors.full_name}>{(p) => <input {...p} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />}</Field>
          </div>
          <div className="row">
            <Field label="Initial password" error={errors.password} hint="At least 10 characters. If the person already has an account, their existing password is kept.">{(p) => <input {...p} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />}</Field>
            <Field label="Role">{(p) => <select {...p} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}</select>}</Field>
          </div>
          <button type="submit">Review and add…</button>
        </form>
      </Card>
      <ConfirmDialog open={!!pending} tone={pending?.kind === "remove" ? "danger" : "primary"} busy={busy} onConfirm={() => void confirm()} onCancel={() => setPending(null)}
        title={pending?.kind === "remove" ? "Remove this member?" : pending?.kind === "role" ? "Change this member's role?" : "Add this member?"}
        confirmLabel={pending?.kind === "remove" ? "Remove" : pending?.kind === "role" ? "Change role" : "Add member"}>
        {pending?.kind === "remove" && <p>{pending.member.email} will lose all access to this tenant immediately.</p>}
        {pending?.kind === "role" && <p>{pending.member.email} will become <strong>{ROLE_LABELS[pending.role]}</strong>. Permissions change immediately and are checked on the server for every request.</p>}
        {pending?.kind === "add" && <p>{form.email} will be added as <strong>{ROLE_LABELS[form.role]}</strong>.</p>}
      </ConfirmDialog>
    </>
  );
}

function PlatformAdmin() {
  const audit = useAsync(() => api<{ items: { id: number; action: string; actor_id: string; details: Record<string, unknown>; created_at: string }[] }>("/platform/audit?limit=20"), []);
  const [form, setForm] = useState({ slug: "", name: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    try {
      const t = await post<{ id: string; slug: string }>("/tenants", form);
      setMessage({ tone: "ok", text: `Tenant ${t.slug} created. Add its first administrator through the members API, then continue onboarding as that administrator.` });
      setForm({ slug: "", name: "" });
      audit.reload();
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof Error ? err.message : "Could not create the tenant" });
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <>
      {message && <Notice tone={message.tone} onDismiss={() => setMessage(null)}>{message.text}</Notice>}
      <Card title="Create a tenant" id="adm-tenant">
        <form onSubmit={(e) => {
          e.preventDefault();
          const errs: Record<string, string> = {};
          if (!/^[a-z0-9][a-z0-9-]{1,40}$/.test(form.slug)) errs.slug = "Use 2–41 lowercase letters, digits or hyphens.";
          if (form.name.trim().length < 2) errs.name = "Enter a display name.";
          setErrors(errs);
          if (!Object.keys(errs).length) setConfirm(true);
        }} aria-label="Create tenant" noValidate>
          <div className="row">
            <Field label="Tenant name (slug)" error={errors.slug}>{(p) => <input {...p} value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />}</Field>
            <Field label="Display name" error={errors.name}>{(p) => <input {...p} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
          </div>
          <button type="submit">Review and create…</button>
        </form>
        <p className="muted small">Platform administrators cannot read tenant business data. Cross-tenant administration is audited in the tenant&apos;s own log.</p>
      </Card>
      <Card title="Platform sign-ins" id="adm-audit">
        <Status state={audit} label="platform audit" empty={audit.data && audit.data.items.length === 0 ? "No platform events yet." : undefined} />
        {audit.data && audit.data.items.length > 0 && (
          <KeyValues rows={audit.data.items.map((a) => [fmtTime(a.created_at), `${a.action} · ${String(a.details.email ?? a.actor_id)}`])} />
        )}
      </Card>
      <ConfirmDialog open={confirm} title="Create this tenant?" confirmLabel="Create tenant" busy={busy} onConfirm={() => void create()} onCancel={() => setConfirm(false)}>
        <p>Create <strong>{form.slug}</strong> ({form.name}). The tenant is empty until it is onboarded.</p>
      </ConfirmDialog>
    </>
  );
}
