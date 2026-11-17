import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useRoute } from "./hooks/useRoute";
import AppLayout from "./layouts/AppLayout";
import { defaultPath, PAGES } from "./nav";
import AdministrationPage from "./pages/AdministrationPage";
import ApprovalsPage from "./pages/ApprovalsPage";
import AssistantPage from "./pages/AssistantPage";
import AuditPage from "./pages/AuditPage";
import DataSourcesPage from "./pages/DataSourcesPage";
import DocumentsPage from "./pages/DocumentsPage";
import EvaluationPage from "./pages/EvaluationPage";
import IncidentsPage from "./pages/IncidentsPage";
import IntegrationHealthPage from "./pages/IntegrationHealthPage";
import LoginPage from "./pages/LoginPage";
import OnboardingPage from "./pages/OnboardingPage";
import OverviewPage from "./pages/OverviewPage";
import TicketsPage from "./pages/TicketsPage";
import WorkflowsPage from "./pages/WorkflowsPage";
import { getSession, onSessionExpired, setSession } from "./services/api";
import type { Session } from "./types";

function renderPage(id: string, session: Session): ReactNode {
  switch (id) {
    case "overview": return <OverviewPage session={session} />;
    case "onboarding": return <OnboardingPage session={session} />;
    case "data-sources": return <DataSourcesPage session={session} />;
    case "documents": return <DocumentsPage session={session} />;
    case "assistant": return <AssistantPage />;
    case "incidents": return <IncidentsPage session={session} />;
    case "tickets": return <TicketsPage session={session} />;
    case "approvals": return <ApprovalsPage session={session} />;
    case "workflows": return <WorkflowsPage />;
    case "integrations": return <IntegrationHealthPage session={session} />;
    case "evaluation": return <EvaluationPage />;
    case "audit": return <AuditPage />;
    case "administration": return <AdministrationPage session={session} />;
    default: return null;
  }
}

export default function App() {
  const [session, setLocal] = useState<Session | null>(getSession());
  const [expired, setExpired] = useState(false);
  const [expiringSoon, setExpiringSoon] = useState(false);
  const [path, navigate] = useRoute();

  // The server rejected the token (expired, revoked or tampered): drop the session and say why.
  useEffect(() => onSessionExpired(() => { setLocal(null); setExpired(true); }), []);

  // Client-side hint about the token's own expiry so the user is warned before an action fails.
  useEffect(() => {
    if (!session?.expiresAt) return;
    const tick = () => {
      const left = session.expiresAt! - Date.now() / 1000;
      if (left <= 0) { setSession(null); setLocal(null); setExpired(true); }
      else setExpiringSoon(left < 120);
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, [session]);

  if (!session) {
    return (
      <LoginPage
        expiredNotice={expired}
        onLogin={(s) => { setExpired(false); setLocal(s); if (!window.location.hash) navigate(defaultPath(s)); }}
      />
    );
  }

  const visible = PAGES.filter((p) => p.visible(session));
  const page = PAGES.find((p) => p.path === path) ?? null;
  const allowed = page ? page.visible(session) : false;
  const signOut = () => { setSession(null); setLocal(null); setExpired(false); window.location.hash = ""; };

  return (
    <AppLayout session={session} pages={visible} path={path} expiringSoon={expiringSoon} onSignOut={signOut}>
      {!page && <NotFound go={() => navigate(defaultPath(session))} />}
      {page && !allowed && (
        <section className="card" aria-labelledby="denied-h">
          <h2 id="denied-h">Not available for your role</h2>
          <p>{page.deniedMessage ?? "This page is not available for your role."}</p>
          <p className="muted small">The server enforces access independently of what this interface shows.</p>
        </section>
      )}
      {page && allowed && <div key={`${session.tenant}-${page.id}`}>{renderPage(page.id, session)}</div>}
    </AppLayout>
  );
}

function NotFound({ go }: { go: () => void }) {
  return (
    <section className="card" aria-labelledby="nf-h">
      <h2 id="nf-h">Page not found</h2>
      <button onClick={go}>Go to the start page</button>
    </section>
  );
}
