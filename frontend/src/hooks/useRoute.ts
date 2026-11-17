import { useEffect, useState } from "react";

const current = () => {
  const hash = window.location.hash.replace(/^#/, "");
  const path = hash.split("?")[0];
  return path.startsWith("/") ? path : "";
};

/** Minimal hash router: deep links like #/tickets?id=... work and the back button behaves. */
export function useRoute(): [string, (path: string) => void] {
  const [path, setPath] = useState(current());
  useEffect(() => {
    const onChange = () => setPath(current());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return [path, (next: string) => { window.location.hash = next; }];
}

export function hashParam(name: string): string | null {
  const query = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(query).get(name);
}
