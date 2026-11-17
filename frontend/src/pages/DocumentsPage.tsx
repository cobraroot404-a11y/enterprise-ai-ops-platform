import { useState } from "react";
import type { FormEvent } from "react";
import { Badge, Card, Field, fmtTime, Notice, PageHeader, Pager, SortHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useDebounced } from "../hooks/useDebounced";
import { usePagedList } from "../hooks/usePagedList";
import { profileKinds, useTenantProfile } from "../hooks/useTenantProfile";
import { api } from "../services/api";
import { can } from "../services/rbac";
import type { DocumentDetail, DocumentRow, Session } from "../types";

const DEFAULT_KINDS = ["equipment_manual", "inspection_report", "incident_history", "equipment_register", "maintenance_log", "other"];
const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED = [".pdf", ".csv", ".json", ".txt", ".md"];

export default function DocumentsPage({ session }: { session: Session }) {
  const profile = useTenantProfile();
  const kinds = Array.from(new Set([...DEFAULT_KINDS, ...profileKinds(profile.data)]));
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const q = useDebounced(search);
  const [reload, setReload] = useState(0);
  const list = usePagedList<DocumentRow>("/documents", { q, kind: kindFilter }, { defaultSort: "created_at", defaultOrder: "desc", refreshKey: reload });
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useAsync(() => (selected ? api<DocumentDetail>(`/documents/${selected}`) : Promise.resolve(null)), [selected]);
  const [kind, setKind] = useState("equipment_manual");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canUpload = can(session.role, "documents:write");

  function pick(f: File | null) {
    setFile(f);
    setMessage(null);
    if (!f) return setFileError(null);
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ALLOWED.includes(ext)) setFileError(`Unsupported file type ${ext || "(none)"}. Allowed: ${ALLOWED.join(", ")}.`);
    else if (f.size > MAX_BYTES) setFileError("File is larger than 10 MB.");
    else if (f.size === 0) setFileError("File is empty.");
    else setFileError(null);
  }

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return setFileError("Choose a file.");
    if (fileError) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    try {
      const res = await api<{ status: string; chunk_count: number; version: number }>("/documents", { method: "POST", body: form });
      const word = res.status === "duplicate" ? "was already ingested (identical content, nothing changed)" : res.status === "new_version" ? `ingested as a new version (v${res.version})` : "ingested";
      setMessage(`${file.name} ${word}: ${res.chunk_count} passages.`);
      setFile(null);
      setReload((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  const data = list.state.data;
  return (
    <section aria-labelledby="doc-h">
      <PageHeader title="Document Library" intro="Documents are versioned, hashed and split into passages that carry their page or record provenance." />
      {canUpload && (
        <Card title="Ingest a document" id="doc-up">
          <form onSubmit={upload} aria-label="Upload document" noValidate>
            <div className="row">
              <Field label="File (PDF, CSV, JSON, TXT, MD · max 10 MB)" error={fileError}>
                {(p) => <input {...p} type="file" accept={ALLOWED.join(",")} onChange={(e) => pick(e.target.files?.[0] ?? null)} />}
              </Field>
              <Field label="Kind">{(p) => <select {...p} value={kind} onChange={(e) => setKind(e.target.value)}>{kinds.map((k) => <option key={k}>{k}</option>)}</select>}</Field>
              <button type="submit" disabled={busy || !file || !!fileError}>{busy ? "Ingesting…" : "Ingest"}</button>
            </div>
          </form>
          {message && <Notice tone="ok" onDismiss={() => setMessage(null)}>{message}</Notice>}
          {error && <Notice tone="bad" onDismiss={() => setError(null)}>{error}</Notice>}
        </Card>
      )}
      <Card title="Documents" id="doc-list">
        <div className="row" role="search" aria-label="Filter documents">
          <Field label="Search file name">{(p) => <input {...p} type="search" value={search} onChange={(e) => setSearch(e.target.value)} />}</Field>
          <Field label="Kind">{(p) => <select {...p} value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}><option value="">All kinds</option>{kinds.map((k) => <option key={k}>{k}</option>)}</select>}</Field>
        </div>
        <Status state={list.state} label="documents" empty={data && data.items.length === 0 ? (q || kindFilter ? "No documents match the filters." : "No documents yet.") : undefined} />
        {data && data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <caption className="sr-only">Documents</caption>
              <thead>
                <tr>
                  <SortHeader column="filename" label="File" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <SortHeader column="kind" label="Kind" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <th scope="col">Version</th><th scope="col">Passages</th><th scope="col">Pages</th>
                  <SortHeader column="created_at" label="Added" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                </tr>
              </thead>
              <tbody>
                {data.items.map((d) => (
                  <tr key={d.id} className={selected === d.id ? "selected" : ""}>
                    <td><button className="linklike" aria-pressed={selected === d.id} onClick={() => setSelected(selected === d.id ? null : d.id)}>{d.filename}</button></td>
                    <td>{d.kind}</td><td>v{d.current_version}</td><td>{d.chunk_count ?? "–"}</td><td>{d.page_count ?? "–"}</td><td>{fmtTime(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager total={data.total} limit={data.limit} offset={list.offset} onChange={list.setOffset} />}
      </Card>
      {selected && (
        <Card title="Document details" id="doc-detail">
          <Status state={detail} label="document" />
          {detail.data && (
            <>
              <p><strong>{detail.data.filename}</strong> <Badge>{detail.data.kind}</Badge> current version v{detail.data.current_version}</p>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table"><table>
                <thead><tr><th scope="col">Version</th><th scope="col">SHA-256</th><th scope="col">Passages</th><th scope="col">Size</th><th scope="col">Embeddings</th><th scope="col">Ingested</th></tr></thead>
                <tbody>
                  {detail.data.versions.map((v) => (
                    <tr key={v.version}><td>v{v.version}</td><td><code>{v.sha256.slice(0, 16)}…</code></td><td>{v.chunks}</td><td>{(v.size_bytes / 1024).toFixed(1)} KB</td><td>{v.embedding_backend}</td><td>{fmtTime(v.created_at)}</td></tr>
                  ))}
                </tbody>
              </table></div>
            </>
          )}
        </Card>
      )}
    </section>
  );
}
