"""Manual versus automated workflow comparison (V41-21.14): a transparent measurement protocol. See evaluation/comparison/protocol.md.

Three kinds of numbers are kept strictly apart and every output says which kind it is:

  A  MEASURED AUTOMATED   wall-clock time of the platform's own steps for equivalent synthetic tasks, measured here (system time only: no human think time is included).
  B  OBSERVED MANUAL      times a real person was actually observed taking, read from evaluation/comparison/observed-manual.csv. NONE exist in this repository; without that file this
                          section says so and no comparison is made.
  C  SIMULATED MANUAL     a hypothetical baseline computed ONLY from assumptions the reader supplies in a JSON file (evaluation/comparison/assumptions.json). The repository ships no
                          assumed manual times and this module never invents any.

No result of this module may be described as a real productivity gain: the scenarios are fictional and the tasks synthetic."""
import csv
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_DIR = ROOT / "evaluation" / "comparison"
STEPS = ("extract_incident", "review_incident", "draft_ticket", "request_approval", "approve", "worker_submission")  # review_incident only for incidents the platform sends to human review
HUMAN_TOUCHPOINTS = ["engineer: writes the fault report", "engineer: reviews the structured incident", "supervisor: reviews incidents the platform routes to human review", "engineer: drafts the ticket and requests approval", "supervisor: reviews and decides the approval"]
CLAIMS = {"A": "measured automated system time", "B": "observed human performance", "C": "simulated, hypothetical baseline"}


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q / 100 * len(ordered)) - 1))]


def summarise(values: list[float]) -> dict:
    return {"n": len(values), "median_s": round(statistics.median(values), 4), "p95_s": round(percentile(values, 95), 4), "min_s": round(min(values), 4), "max_s": round(max(values), 4)}


def load_tasks(path: Path | None = None) -> list[dict]:
    return json.loads((path or COMPARISON_DIR / "synthetic-tasks.json").read_text(encoding="utf-8"))["tasks"]


def read_observed(path: Path) -> list[float] | None:
    """Observed human times in seconds from a CSV with columns task_id, participant_role, seconds, notes. None when there is no file (the usual case)."""
    if not path.exists():
        return None
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    values = []
    for row in rows:
        try:
            seconds = float(row["seconds"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("observed-manual.csv: every row needs a numeric `seconds`") from None
        if not (0 < seconds < 86400):
            raise ValueError("observed-manual.csv: `seconds` must be between 0 and 86400")
        values.append(seconds)
    if not values:
        raise ValueError("observed-manual.csv has no rows")
    return values


def read_assumptions(path: Path) -> dict | None:
    """Assumed manual step durations (lo and hi seconds per step) supplied by the reader. None when there is no file. A null or missing number is refused: nothing is filled in."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data.get("steps")
    if not isinstance(steps, dict) or not steps:
        raise ValueError("assumptions.json needs a non-empty `steps` object")
    for name, pair in steps.items():
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0 for x in pair) and pair[0] <= pair[1]):
            raise ValueError(f"assumptions.json: step `{name}` must be [low, high] seconds with 0 <= low <= high (no nulls: nothing is invented)")
    if not data.get("source"):
        raise ValueError("assumptions.json needs a `source` stating where the numbers come from (for example 'my own estimate')")
    return data


def build_report(automated: list[dict], tasks: int, backend: dict, observed: list[float] | None, assumptions: dict | None) -> dict:
    per_step = {step: summarise([row[step] for row in automated if step in row]) for step in STEPS if any(step in row for row in automated)}
    totals = [sum(row[s] for s in STEPS if s in row) for row in automated]
    report = {
        "claim": "No real productivity gain is claimed: fictional scenarios, synthetic tasks, same-author measurement.",
        "A_measured_automated": {"kind": CLAIMS["A"], "tasks": tasks, "backend": backend, "per_step": per_step, "end_to_end_system_time": summarise(totals),
                                 "excluded": "human think and reading time, network distance, real external systems (local mocks are used)", "human_touchpoints_that_remain": HUMAN_TOUCHPOINTS},
        "B_observed_manual": {"kind": CLAIMS["B"], "available": observed is not None, "summary": summarise(observed) if observed else None,
                              "note": "no observed human data exist; no comparison is made" if observed is None else "observed seconds per task as recorded by the observer (see the CSV); not paired with the automated measurement by this module"},
        "C_simulated_manual": {"kind": CLAIMS["C"], "available": assumptions is not None, "assumptions": assumptions, "result": None,
                               "note": "no assumptions were supplied; nothing is simulated" if assumptions is None else None},
    }
    if assumptions:
        lo, hi = sum(p[0] for p in assumptions["steps"].values()), sum(p[1] for p in assumptions["steps"].values())
        report["C_simulated_manual"]["result"] = {"hypothetical_manual_total_s": [lo, hi], "automated_system_median_s": report["A_measured_automated"]["end_to_end_system_time"]["median_s"],
                                                  "label": "HYPOTHETICAL: derived only from the supplied assumptions, not observed, and the human touchpoints above remain in the automated workflow"}
    return report


def markdown(report: dict) -> str:
    a, b, c = report["A_measured_automated"], report["B_observed_manual"], report["C_simulated_manual"]
    lines = ["# Manual versus automated workflow comparison", "", f"**{report['claim']}**", "", f"## A. Measured automated ({a['kind']})", "",
             f"{a['tasks']} equivalent synthetic tasks; backend: `{json.dumps(a['backend'])}`. Excluded: {a['excluded']}.", "", "| Step | n | median s | p95 s | min s | max s |", "|---|---|---|---|---|---|"]
    for step, s in a["per_step"].items():
        lines.append(f"| {step} | {s['n']} | {s['median_s']} | {s['p95_s']} | {s['min_s']} | {s['max_s']} |")
    e = a["end_to_end_system_time"]
    lines += [f"| **end to end (system time)** | {e['n']} | {e['median_s']} | {e['p95_s']} | {e['min_s']} | {e['max_s']} |", "", "Human touchpoints that remain in the automated workflow (not timed here): " + "; ".join(a["human_touchpoints_that_remain"]) + ".", "",
              f"## B. Observed manual ({b['kind']})", "", b["note"] + ("." if not b["note"].endswith(".") else ""), ""]
    if b["summary"]:
        lines += [f"Observed: n {b['summary']['n']}, median {b['summary']['median_s']} s, p95 {b['summary']['p95_s']} s.", ""]
    lines += [f"## C. Simulated manual ({c['kind']})", ""]
    if c["result"]:
        lines += [f"Assumptions (source: {c['assumptions']['source']}): " + ", ".join(f"{k} {v[0]} to {v[1]} s" for k, v in c["assumptions"]["steps"].items()) + ".", "",
                  f"HYPOTHETICAL manual total {c['result']['hypothetical_manual_total_s'][0]} to {c['result']['hypothetical_manual_total_s'][1]} s against a measured automated system median of {c['result']['automated_system_median_s']} s. {c['result']['label']}.", ""]
    else:
        lines += [c["note"] + ".", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------------------------------- live measurement
def _call(api: str, method: str, path: str, token: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data=data, method=method, headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - local URL
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def measure(api: str, tokens: dict, tasks: list[dict]) -> list[dict]:
    """Run each synthetic task through the real API and worker, timing each step. Raises if a step does not succeed: a failed task is never silently dropped."""
    rows = []
    for task in tasks:
        row = {"task_id": task["id"]}
        t = time.perf_counter()
        code, inc = _call(api, "POST", "/incidents/extract", tokens["engineer"], {"report_text": task["report"]})
        row["extract_incident"] = time.perf_counter() - t
        if code != 201:
            raise RuntimeError(f"task {task['id']}: extraction failed (HTTP {code})")
        if inc.get("review_status") == "needs_review":  # the platform routes this incident to a human: the supervisor's decision is a measured API step (a person's time is NOT included)
            t = time.perf_counter()
            code, _ = _call(api, "POST", f"/incidents/{inc['id']}/review", tokens["supervisor"], {"decision": "accept", "comment": "Comparison protocol: synthetic task."})
            row["review_incident"] = time.perf_counter() - t
            if code != 200:
                raise RuntimeError(f"task {task['id']}: incident review failed (HTTP {code})")
        t = time.perf_counter()
        code, ticket = _call(api, "POST", "/tickets", tokens["engineer"], {"incident_id": inc["id"]})
        row["draft_ticket"] = time.perf_counter() - t
        if code != 201:
            raise RuntimeError(f"task {task['id']}: ticket draft failed (HTTP {code}: {(ticket or {}).get('error', {}).get('code')})")
        t = time.perf_counter()
        code, _ = _call(api, "POST", f"/tickets/{ticket['id']}/request-approval", tokens["engineer"])
        row["request_approval"] = time.perf_counter() - t
        t = time.perf_counter()
        code2, decided = _call(api, "POST", f"/approvals/{ticket['id']}/decision", tokens["supervisor"], {"decision": "approved", "comment": "Comparison protocol: synthetic task."})
        row["approve"] = time.perf_counter() - t
        if code != 200 or code2 != 200:
            raise RuntimeError(f"task {task['id']}: approval failed (HTTP {code}, {code2}: {((decided or {}).get('error') or {}).get('code')})")
        t = time.perf_counter()
        state = None
        while time.perf_counter() - t < 60:
            _, final = _call(api, "GET", f"/tickets/{ticket['id']}", tokens["engineer"])
            state = final.get("state")
            if state in ("SUBMITTED", "FAILED"):
                break
            time.sleep(0.1)
        row["worker_submission"] = time.perf_counter() - t
        if state != "SUBMITTED":
            raise RuntimeError(f"task {task['id']}: ticket ended {state}")
        rows.append(row)
    return rows


def run(api: str, password: str, login, outdir: Path, backend: dict, tasks_path: Path | None = None) -> dict:
    tasks = load_tasks(tasks_path)
    tokens = {r: login(api, "apex-industrial", "apex.example.test", r, password) for r in ("engineer", "supervisor")}
    automated = measure(api, tokens, tasks)
    observed = read_observed(COMPARISON_DIR / "observed-manual.csv")
    assumptions = read_assumptions(COMPARISON_DIR / "assumptions.json")
    report = build_report(automated, len(tasks), backend, observed, assumptions)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "comparison.json").write_text(json.dumps({"report": report, "raw_automated": automated}, indent=2), encoding="utf-8")
    (outdir / "comparison.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    return report
