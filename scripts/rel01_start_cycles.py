#!/usr/bin/env python
"""Bounded REL-01 investigation helper: repeat the one-command start and stop, recording the exit codes and the elapsed time of every cycle.

    python scripts/rel01_start_cycles.py --cycles 10

REL-01 is an unexplained, once-seen stall ("api was not ready after 90s"). This script does not try to cause it; it only counts how often a cold start fails and how long a healthy one takes,
so the defect register can state its observed frequency honestly. Each cycle runs `scripts/demo.py up` then `down` (a disposable database, only project-owned processes). A failed `up`
keeps its own diagnostics in the launcher output (printed here, truncated). The result table is written to the file given by --out (default evaluation/demo-runs/rel01-start-cycles.md)."""
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], timeout: int) -> tuple[int, float, str]:
    started = time.perf_counter()
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py"), *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return res.returncode, time.perf_counter() - started, (res.stdout + res.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "demo-runs" / "rel01-start-cycles.md"))
    args = ap.parse_args()
    rows, failures, notes = [], 0, []
    for n in range(1, args.cycles + 1):
        started = datetime.now().strftime("%H:%M:%S")
        up_code, up_s, up_out = run(["up"], 400)
        down_code, down_s, _ = run(["down"], 300)
        if up_code or down_code:
            failures += 1
            notes.append(f"cycle {n}: up exit {up_code}, down exit {down_code}; launcher output tail: {up_out[-600:]!r}")
        rows.append(f"| {n} | {started} | {up_code} | {up_s:.1f} | {down_code} | {down_s:.1f} |")
        print(f"cycle {n}: up {up_code} ({up_s:.1f}s) down {down_code} ({down_s:.1f}s)", flush=True)
    text = [f"# REL-01 start/stop cycles ({datetime.now().date()})", "",
            f"`python scripts/rel01_start_cycles.py --cycles {args.cycles}`: {args.cycles - failures} of {args.cycles} cycles started every service and stopped cleanly; {failures} failed.", "",
            "| Cycle | Start | `up` exit | `up` seconds | `down` exit | `down` seconds |", "|---|---|---|---|---|---|", *rows, ""]
    if notes:
        text += ["## Failures", *[f"- {n}" for n in notes], ""]
    text += ["These cycles are diagnostic evidence about frequency only; they do not explain the one stall seen in Batch 7 and do not resolve REL-01.", ""]
    Path(args.out).write_text("\n".join(text), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
