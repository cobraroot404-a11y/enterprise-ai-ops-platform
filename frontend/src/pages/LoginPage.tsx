import { useState } from "react";
import type { FormEvent } from "react";
import { Field, Notice } from "../components/ui";
import { ApiError, login } from "../services/api";
import type { Session } from "../types";

export default function LoginPage({ onLogin, expiredNotice }: { onLogin: (s: Session) => void; expiredNotice?: boolean }) {
  const [tenant, setTenant] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errors: Record<string, string> = {};
    if (!/^\S+@\S+\.\S+$/.test(email)) errors.email = "Enter a valid email address.";
    if (!password) errors.password = "Enter your password.";
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;
    setBusy(true);
    setError(null);
    try {
      onLogin(await login(tenant, email, password));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? `${err.message}. Wait a minute before trying again.` : err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="card narrow" id="main">
      <h1>Enterprise AI Operations Platform</h1>
      {expiredNotice && <Notice tone="warn">Your session expired or was rejected by the server. Please sign in again.</Notice>}
      <form onSubmit={submit} aria-label="Sign in" noValidate>
        <Field label="Tenant" hint="Your organization's tenant name. Leave empty for platform administrators.">
          {(p) => <input {...p} value={tenant} onChange={(e) => setTenant(e.target.value)} autoComplete="organization" />}
        </Field>
        <Field label="Email" error={fieldErrors.email}>
          {(p) => <input {...p} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />}
        </Field>
        <Field label="Password" error={fieldErrors.password}>
          {(p) => <input {...p} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />}
        </Field>
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="muted">Fictional demo data only.</p>
    </main>
  );
}
