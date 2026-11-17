"""Real-CLI failure scenarios for scripts/demo.py (Batch 6): missing .env, invalid JSON setting, PostgreSQL unavailable, occupied port, missing Ollama model,
launcher killed mid-startup then `down`, repeated `up`, `status` and a double `down`.

    python scripts/demo_negative_checks.py

Needs PostgreSQL; the real-AI scenario starts and stops Ollama. Works on temporary copies of .env, prints return codes and launcher output only, and writes
evaluation/demo-runs/negative-scenarios-batch7.json (override with NEG_OUT)."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="demo-neg-"))
results = []


def env_copy(name, edit):
    lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip()
        new = edit(k, line)
        if new is not None:
            out.append(new)
    p = TMP / name
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return str(p)


def demo(*args, timeout=300):
    r = subprocess.run([PY, "scripts/demo.py", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def demo_dbs():
    sys.path.insert(0, str(ROOT / "scripts"))
    import demo as d
    env = d.load_env_file(ROOT / ".env")
    with d._admin(env) as c:
        return [r[0] for r in c.exec_driver_sql("SELECT datname FROM pg_database WHERE left(datname, 9) = 'eaop_demo'")]


def state_exists():
    return (ROOT / ".demo" / "state.json").exists()


def record(name, ok, detail):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + " :: " + detail.replace("\n", " | ")[:330], flush=True)


# 1 missing env file
rc, out = demo("preflight", "--env-file", str(TMP / "nope.env"))
record("missing environment file", rc == 2 and "copy .env.example" in out, f"rc={rc} {out.strip()[:200]}")

# 2 invalid JSON
bad = env_copy("badjson.env", lambda k, line: "EGRESS_DEV_MOCKS={apex-industrial:[http://127.0.0.1:8101]}" if k == "EGRESS_DEV_MOCKS" else line)
rc, out = demo("up", "--env-file", bad)
record("invalid JSON configuration", rc == 1 and "EGRESS_DEV_MOCKS is not a valid JSON object" in out and not state_exists() and not demo_dbs(), f"rc={rc} dbs={demo_dbs()} state={state_exists()}")

# 3 PostgreSQL unavailable
nopg = env_copy("nopg.env", lambda k, line: "POSTGRES_PORT=1" if k == "POSTGRES_PORT" else line)
rc, out = demo("up", "--env-file", nopg)
record("PostgreSQL unavailable", rc == 1 and "cannot connect to PostgreSQL" in out and not state_exists(), f"rc={rc} {out.strip()[-220:]}")

# 4 required port occupied by an unrelated program
holder = subprocess.Popen([PY, "-c", "import socket,time;s=socket.socket();s.bind(('127.0.0.1',8103));s.listen(1);time.sleep(120)"])
time.sleep(1)
rc, out = demo("up")
alive = holder.poll() is None
holder.kill()
record("required port already occupied", rc == 1 and "fleet:8103" in out and alive and not state_exists() and not demo_dbs(), f"rc={rc} holder_untouched={alive} dbs={demo_dbs()}")

# 5 missing local Ollama model (real-AI mode): Ollama is started by the run, the model is absent, the run cleans up and stops what it started
sys.path.insert(0, str(ROOT / "scripts"))
import ollama_ctl  # noqa: E402
was_up = ollama_ctl.is_up()
nomodel = env_copy("nomodel.env", lambda k, line: "OLLAMA_MODEL=no-such-model:1b" if k == "OLLAMA_MODEL" else line)
if not os.environ.get("OLLAMA_MODEL") and "OLLAMA_MODEL" not in (ROOT / ".env").read_text(encoding="utf-8"):
    nomodel = env_copy("nomodel.env", lambda k, line: line)
    with open(nomodel, "a", encoding="utf-8") as f:
        f.write("OLLAMA_MODEL=no-such-model:1b\n")
rc, out = demo("up", "--ai", "real", "--env-file", nomodel, timeout=400)
record("missing local Ollama model", rc == 1 and "ollama pull no-such-model:1b" in out and not state_exists() and not demo_dbs() and (was_up or not ollama_ctl.is_up()), f"rc={rc} ollama_running_after={ollama_ctl.is_up()} was_up={was_up}")

# 6 launcher killed mid-startup, then `down` recovers
p = subprocess.Popen([PY, "scripts/demo.py", "up"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.time() + 60
st = None
while time.time() < deadline:
    if state_exists():
        st = json.loads((ROOT / ".demo" / "state.json").read_text(encoding="utf-8"))
        if st.get("db_created") and len(st.get("processes", [])) >= 3:
            break
    time.sleep(0.3)
subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
time.sleep(1)
left_before = [x["name"] for x in json.loads((ROOT / ".demo" / "state.json").read_text(encoding="utf-8")).get("processes", [])] if state_exists() else []
rc_stale, out_stale = demo("up")
stale_refused = rc_stale != 0 and "no longer running" in out_stale and "demo.py down" in out_stale
rc, out = demo("down")
record("interrupted startup (launcher killed): stale state refused by `up`, recovered by `down`", rc == 0 and stale_refused and not state_exists() and not demo_dbs(), f"recorded_before_down={left_before} stale_up_refused={stale_refused} down_rc={rc} dbs={demo_dbs()}")

# 7 repeated invocation, interactive mode, status, down, down again
rc1, out1 = demo("up")
ok1 = rc1 == 0 and "READY" in out1
rc2, out2 = demo("up")
refused = rc2 != 0 and "demo.py down" in out2
rc3, out3 = demo("status")
api = None
try:
    api = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=3).status
except Exception as exc:  # noqa: BLE001
    api = str(exc)
ui = None
try:
    ui = urllib.request.urlopen("http://127.0.0.1:5173/", timeout=3).status
except Exception as exc:  # noqa: BLE001
    ui = str(exc)
still_running = "running" in out3 and out3.count("not running") == 0
rc4, out4 = demo("down")
rc5, out5 = demo("down")
record("interactive up, repeated up refused, status, down, down again",
       ok1 and refused and still_running and api == 200 and ui == 200 and rc4 == 0 and rc5 == 0 and "nothing to stop" in out5 and not demo_dbs() and not any(socket.socket().connect_ex(("127.0.0.1", port)) == 0 for port in (8000, 8101, 5173)),
       f"up={rc1} second_up_rc={rc2} refused={refused} api={api} ui={ui} down={rc4} down2={rc5} dbs={demo_dbs()}")
# 8 two launchers started at the same moment: exactly one owns the run
pa = subprocess.Popen([PY, "scripts/demo.py", "up"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
pb = subprocess.Popen([PY, "scripts/demo.py", "up"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
oa, ob = pa.communicate(timeout=300)[0], pb.communicate(timeout=300)[0]
codes = sorted([pa.returncode, pb.returncode])
one_state = state_exists()
dbs_during = demo_dbs()
rc_down, _ = demo("down")
record("two launchers started concurrently: exactly one wins", codes[0] == 0 and codes[1] != 0 and one_state and len(dbs_during) == 1 and rc_down == 0 and not demo_dbs() and not state_exists(),
       f"exit_codes={codes} databases_while_running={len(dbs_during)} down={rc_down} dbs_after={demo_dbs()}")

# 9 shutdown interrupted half way, then resumed by a second `down`
rc_up, _ = demo("up")
total = len(json.loads((ROOT / ".demo" / "state.json").read_text(encoding="utf-8"))["processes"]) if state_exists() else 0
d = subprocess.Popen([PY, "scripts/demo.py", "down"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
partial = None
deadline = time.time() + 60
while time.time() < deadline and d.poll() is None:
    try:
        n = len(json.loads((ROOT / ".demo" / "state.json").read_text(encoding="utf-8"))["processes"])
    except (OSError, ValueError):
        n = None
    if n is not None and 0 < n < total:
        partial = n
        break
    time.sleep(0.2)
if d.poll() is None:
    subprocess.run(["taskkill", "/PID", str(d.pid), "/T", "/F"], capture_output=True)
time.sleep(1)
still = json.loads((ROOT / ".demo" / "state.json").read_text(encoding="utf-8")) if state_exists() else None
interrupted_midway = partial is not None and still is not None and 0 < len(still["processes"]) < total
rc_resume, out_resume = demo("down")
record("shutdown interrupted half way, then resumed by the next down", rc_up == 0 and interrupted_midway and rc_resume == 0 and not state_exists() and not demo_dbs(),
       f"processes_total={total} remaining_after_interrupt={None if still is None else len(still['processes'])} resumed_rc={rc_resume} dbs={demo_dbs()}")
print("SUMMARY", sum(1 for r in results if r[1]), "of", len(results), "passed")
(Path(os.environ.get("NEG_OUT", str(ROOT / "evaluation" / "demo-runs" / "negative-scenarios-batch7.json")))).write_text(json.dumps([{"scenario": n, "passed": o, "detail": d} for n, o, d in results], indent=1), encoding="utf-8")
