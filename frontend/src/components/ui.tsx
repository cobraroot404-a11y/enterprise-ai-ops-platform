import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import type { AsyncState } from "../hooks/useAsync";

export function Status({ state, empty, label = "data" }: { state: AsyncState<unknown>; empty?: string; label?: string }) {
  if (state.loading && !state.data) return <p role="status" className="muted loading">Loading {label}…</p>;
  if (state.error)
    return (
      <div role="alert" className="notice notice-bad">
        <span>Could not load {label}: {state.error}</span>
        <button className="secondary small" onClick={state.reload}>Retry</button>
      </div>
    );
  return empty ? <p className="muted empty">{empty}</p> : null;
}

export function Notice({ tone = "ok", children, onDismiss }: { tone?: "ok" | "bad" | "warn" | "info"; children: ReactNode; onDismiss?: () => void }) {
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={`notice notice-${tone}`}>
      <span>{children}</span>
      {onDismiss && <button className="secondary small" onClick={onDismiss} aria-label="Dismiss message">×</button>}
    </div>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: string; title?: string }) {
  return <span className={`badge badge-${tone}`} title={title}>{children}</span>;
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return total > 0 ? <p className="muted small" aria-live="polite">{total} result{total === 1 ? "" : "s"}</p> : null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav aria-label="Pagination" className="pager">
      <button className="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
      <span aria-live="polite">{offset + 1}–{Math.min(total, offset + limit)} of {total} (page {page} of {pages})</span>
      <button className="secondary" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</button>
    </nav>
  );
}

export function SortHeader({ column, label, sort, order, onSort }: { column: string; label: string; sort: string; order: "asc" | "desc"; onSort: (c: string) => void }) {
  const active = sort === column;
  return (
    <th scope="col" aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button className="linklike" onClick={() => onSort(column)} aria-label={`Sort by ${label}`}>
        {label}
        <span aria-hidden="true">{active ? (order === "asc" ? " ▲" : " ▼") : ""}</span>
      </button>
    </th>
  );
}

export function Field({ label, error, hint, children }: { label: string; error?: string | null; hint?: string; children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode }) {
  const id = useId();
  const describedBy = [error ? `${id}-err` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && <span id={`${id}-hint`} className="muted small">{hint}</span>}
      {error && <span id={`${id}-err`} className="error small" role="alert">{error}</span>}
    </div>
  );
}

export function Card({ title, children, actions, id }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <section className="card" aria-labelledby={id}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h3 id={id}>{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, intro, actions }: { title: string; intro?: ReactNode; actions?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => ref.current?.focus(), [title]); // move focus to the new page heading for keyboard and screen-reader users
  return (
    <div className="page-head">
      <div>
        <h2 tabIndex={-1} ref={ref}>{title}</h2>
        {intro && <p className="muted">{intro}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? "–" : v.toFixed(digits);
}
