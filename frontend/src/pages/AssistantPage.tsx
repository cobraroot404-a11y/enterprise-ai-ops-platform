import { useState } from "react";
import type { FormEvent } from "react";
import { CitationList, ProvenanceTag } from "../components/provenance";
import { Badge, Card, Field, fmtNum, fmtTime, PageHeader } from "../components/ui";
import { assetLabel, useTenantProfile } from "../hooks/useTenantProfile";
import { post } from "../services/api";
import type { AnswerResult, SearchHit } from "../types";

interface Turn {
  id: number;
  question: string;
  asked: string;
  result: AnswerResult;
}

export default function AssistantPage() {
  const profile = useTenantProfile();
  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [hits, setHits] = useState<{ query: string; items: SearchHit[]; backend: string } | null>(null);
  const placeholder = profile.data?.profile
    ? `Ask about a ${assetLabel(profile.data)} problem or a maintenance procedure`
    : "What should I check when pump P-101 shows abnormal vibration?";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const text = question.trim();
    if (text.length < 3) return setFieldError("Enter a question of at least 3 characters.");
    setFieldError(null);
    setBusy(true);
    setError(null);
    try {
      if (mode === "ask") {
        const result = await post<AnswerResult>("/ai/ask", { question: text });
        setTurns((t) => [{ id: Date.now(), question: text, asked: new Date().toISOString(), result }, ...t]);
      } else {
        const res = await post<{ items: SearchHit[]; embedding_backend: string }>("/search", { query: text, k: 8 });
        setHits({ query: text, items: res.items, backend: res.embedding_backend });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="ask-h">
      <PageHeader title="AI Knowledge Assistant" intro="Answers are generated from this tenant's documents only. Every citation is checked against the stored passage before an answer is shown." />
      <Card id="ask-form">
        <form onSubmit={submit} aria-label="Ask a question" noValidate>
          <fieldset className="mode">
            <legend className="sr-only">Mode</legend>
            <label className="inline"><input type="radio" name="mode" checked={mode === "ask"} onChange={() => setMode("ask")} /> Ask (AI answer with citations)</label>
            <label className="inline"><input type="radio" name="mode" checked={mode === "search"} onChange={() => setMode("search")} /> Search evidence only (no AI answer)</label>
          </fieldset>
          <Field label="Question" error={fieldError}>
            {(p) => <input {...p} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={placeholder} maxLength={500} />}
          </Field>
          <button type="submit" disabled={busy}>{busy ? "Working…" : mode === "ask" ? "Ask" : "Search"}</button>
        </form>
        {error && <p role="alert" className="error">{error}</p>}
      </Card>

      {mode === "search" && hits && (
        <Card title={`Retrieved passages for "${hits.query}"`} id="ask-hits">
          <p className="muted small">Hybrid retrieval (vector + full text) using {hits.backend} embeddings. Nothing here was written by a model.</p>
          {hits.items.length === 0 && <p className="muted empty">No passages found.</p>}
          <ol className="hits">
            {hits.items.map((h) => (
              <li key={h.chunk_id}>
                <div className="row tight">
                  <strong>{h.filename}</strong>
                  <span className="muted">{h.page_number ? `page ${h.page_number}` : h.record_id ? `record ${h.record_id}` : ""} · v{h.version ?? "?"} · {h.kind}</span>
                  <ProvenanceTag kind="evidence" />
                  <Badge title="Cosine similarity between the question and the passage">similarity {fmtNum(h.similarity, 3)}</Badge>
                  {h.suspicious && <Badge tone="bad" title="Looks like an instruction aimed at the AI; excluded from answers">quarantined</Badge>}
                </div>
                <blockquote>{h.text.length > 400 ? `${h.text.slice(0, 400)}…` : h.text}</blockquote>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {turns.length === 0 && mode === "ask" && <p className="muted empty">Ask a question to see an evidence-grounded answer. Answers from this session stay listed below.</p>}
      {turns.map((t) => (
        <article key={t.id} className="card" aria-label={`Answer to: ${t.question}`}>
          <h3>{t.question}</h3>
          <p className="muted small">Asked {fmtTime(t.asked)} · model {t.result.llm_backend} · embeddings {t.result.embedding_backend}</p>
          {t.result.grounded ? (
            <>
              <div className="answer">
                <ProvenanceTag kind="ai" />
                <p>{t.result.answer}</p>
              </div>
              <h4>Supporting evidence</h4>
              <CitationList citations={t.result.citations} />
            </>
          ) : t.result.insufficient_evidence ? (
            <p role="status"><Badge tone="warn">Insufficient evidence</Badge> The documents do not contain enough verified evidence to answer. No answer was generated from outside knowledge.</p>
          ) : (
            <p role="status"><Badge tone="warn">Answer withheld</Badge> The model&apos;s answer failed verification, so it is not shown.</p>
          )}
          {t.result.problems.length > 0 && (
            <details>
              <summary>Why this was not accepted ({t.result.problems.length})</summary>
              <ul>{t.result.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </details>
          )}
          {t.result.excluded_suspicious.length > 0 && <p className="warn small">{t.result.excluded_suspicious.length} retrieved passage(s) were excluded because they looked like instructions to the AI.</p>}
        </article>
      ))}
    </section>
  );
}
