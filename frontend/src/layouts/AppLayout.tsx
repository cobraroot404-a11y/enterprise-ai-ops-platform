import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { Notice } from "../components/ui";
import type { PageDef } from "../nav";
import { ROLE_LABELS } from "../services/rbac";
import type { Session } from "../types";

interface Props {
  session: Session;
  /** Pages this role may see (navigation only; the API enforces access independently). */
  pages: PageDef[];
  path: string;
  expiringSoon: boolean;
  onSignOut: () => void;
  children: ReactNode;
}

/** The signed-in shell: skip link, top bar with tenant and role, main navigation and the main landmark that holds a page. */
export default function AppLayout({ session, pages, path, expiringSoon, onSignOut, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const main = useRef<HTMLElement>(null);
  return (
    <div className="shell">
      <a href="#main" className="skip" onClick={(e) => {
        e.preventDefault();
        main.current?.focus({ preventScroll: true });
        // Show the main heading below the sticky header, including when the header wraps.
        if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
      }}>Skip to content</a>
      <header className="topbar">
        <button className="secondary menu-toggle" aria-expanded={menuOpen} aria-controls="sidebar" onClick={() => setMenuOpen(!menuOpen)}>
          Menu
        </button>
        <h1 className="brand">Enterprise AI Operations Platform</h1>
        <span className="who" aria-label="Signed in as">
          <span className="tenant-chip" title="Current tenant">{session.tenant || "platform"}</span>
          <span>{session.email}</span>
          <span className="muted">{ROLE_LABELS[session.role] ?? session.role}</span>
        </span>
        <button className="secondary" onClick={onSignOut}>Sign out</button>
      </header>
      <div className="body">
        <nav id="sidebar" aria-label="Main" className={menuOpen ? "open" : ""}>
          <ul>
            {pages.map((p) => (
              <li key={p.id}>
                <a href={`#${p.path}`} aria-current={path === p.path ? "page" : undefined} onClick={() => setMenuOpen(false)}>{p.label}</a>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main" ref={main} tabIndex={-1}>
          {expiringSoon && <Notice tone="warn">Your session expires in under two minutes. Finish what you are doing, then sign in again.</Notice>}
          {children}
        </main>
      </div>
    </div>
  );
}
