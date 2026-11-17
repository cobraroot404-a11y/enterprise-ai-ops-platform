import { useEffect, useRef } from "react";

/** Call `fn` every `ms` while `active` (for example while a background submission is still in flight). */
export function usePoll(active: boolean, ms: number, fn: () => void): void {
  const latest = useRef(fn);
  useEffect(() => { latest.current = fn; });
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => latest.current(), ms);
    return () => clearInterval(id);
  }, [active, ms]);
}
