#!/usr/bin/env python
"""Build and run the containerised stack (docker-compose.app.yml) in its OWN compose project, prove it works end to end, record what was built and downloaded, and remove only what it created.

    python scripts/container_smoke.py [--keep] [--ollama]

Steps: record images and disk before; build the UI (`npm run build`, host); `docker compose build` (this is where base images are pulled and dependencies installed: timed and recorded);
start db, migrate, seed, API, worker, mocks and UI; onboard Meridian through the public API inside the API container; run the Apex and Meridian workflow checks (scripts/demo_smoke.py)
from the host against the published API port; check the UI and its /api proxy; write a report to evaluation/container-smoke/<run id>/; `docker compose down -v` for the selected project.
`--ollama` adds docker-compose.ollama.yml: the API container then uses the Ollama server already running on the HOST (no download; deterministic embeddings) and the run also proves a
grounded answer produced by that model. It never touches the development database or any other project's containers, images or volumes. Secrets are read from .env at run time and never printed or baked into an image."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
COMPOSE = ["docker", "compose", "-f", "docker-compose.app.yml"]
API_PORT, UI_PORT = 18000, 18080
PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "eaop-app")
IMAGE_TAG = os.environ.get("EAOP_APP_IMAGE_TAG", "local")
IMAGES = (f"eaop-app-backend:{IMAGE_TAG}", f"eaop-app-ui:{IMAGE_TAG}")


def sh(cmd, check=True, timeout=1800, **kw):
    res = subprocess.run(cmd, cwd=kw.pop("cwd", ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)
    if check and res.returncode:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed ({res.returncode}): {(res.stdout + res.stderr)[-800:]}")
    return res


def env_value(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{name} is not set in .env")


def get(url: str, timeout=10) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - local URL
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def image_sizes() -> dict:
    out = sh(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}|{{.Size}}"]).stdout.splitlines()
    return dict(line.split("|", 1) for line in out if line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="leave the stack running afterwards (stop with: docker compose -f docker-compose.app.yml down -v)")
    ap.add_argument("--ollama", action="store_true", help="use the host's running Ollama as the API container's language model (needs Ollama and the model already installed)")
    args = ap.parse_args()
    if args.ollama:
        COMPOSE[:] = COMPOSE + ["-f", "docker-compose.ollama.yml"]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = ROOT / "evaluation" / "container-smoke" / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    report = {"run_id": run_id, "steps": [], "ok": False, "profile": "ollama" if args.ollama else "deterministic"}

    def step(name, fn):
        started = time.time()
        try:
            detail = fn()
            report["steps"].append({"step": name, "ok": True, "seconds": round(time.time() - started, 1), "detail": detail or ""})
            print(f"ok   {name} ({time.time() - started:.1f}s)", flush=True)
            return detail
        except Exception as exc:  # noqa: BLE001 - recorded, then the run stops after cleanup
            report["steps"].append({"step": name, "ok": False, "seconds": round(time.time() - started, 1), "detail": str(exc)[:900]})
            print(f"FAIL {name}: {str(exc)[:300]}", flush=True)
            raise

    try:
        before = image_sizes()
        disk_before = json.loads(sh(["docker", "system", "df", "--format", "{{json .}}"]).stdout.splitlines()[0])
        report["images_before"] = sorted(before)
        report["disk_before"] = disk_before
        step("build the web UI on the host (npm run build: typecheck and production bundle)", lambda: sh(["npm", "run", "build"], cwd=ROOT / "frontend", shell=True).stdout[-200:].strip())
        step("docker compose build (pulls base images, installs dependencies)", lambda: sh(COMPOSE + ["build"]).stderr[-300:].strip())
        after = image_sizes()
        report["images_new"] = sorted(set(after) - set(before))
        report["built_image_sizes"] = {k: after.get(k) for k in IMAGES}
        report["disk_after_build"] = json.loads(sh(["docker", "system", "df", "--format", "{{json .}}"]).stdout.splitlines()[0])
        if args.ollama:
            def host_ollama():
                body = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5).read())  # noqa: S310 - local URL
                names = [m["name"] for m in body.get("models", [])]
                if "qwen2.5:1.5b" not in names:
                    raise RuntimeError(f"the model qwen2.5:1.5b is not installed on the host (found {names}); nothing is downloaded by this script")
                return f"host Ollama running with {len(names)} model(s) installed, including qwen2.5:1.5b"
            step("check that Ollama and the model are already running on the host", host_ollama)
        step("start db, migrate, seed Apex, API, worker, mocks and UI", lambda: sh(COMPOSE + ["up", "-d"]).stderr[-200:].strip())

        def wait_api():
            deadline = time.time() + 240
            while time.time() < deadline:
                if get(f"http://127.0.0.1:{API_PORT}/api/v1/health") == 200:
                    return f"GET /api/v1/health 200 on 127.0.0.1:{API_PORT}"
                time.sleep(3)
            raise RuntimeError("the API did not become healthy in 240 s: " + sh(COMPOSE + ["logs", "--tail", "40", "api", "migrate", "seed"], check=False).stdout[-700:])
        step("wait for the API (container health)", wait_api)
        step("onboard Meridian through the public API (inside the API container)", lambda: sh(COMPOSE + ["exec", "-T", "api", "python", "scripts/onboard_tenant.py", "onboarding/meridian.json", "--api", "http://127.0.0.1:8000"]).stdout[-200:].strip())
        import demo_smoke
        password = env_value("SEED_PASSWORD")
        workflows = step("Apex and Meridian workflow checks against the containerised API", lambda: demo_smoke.run_workflows(f"http://127.0.0.1:{API_PORT}/api/v1", password))
        report["workflow_checks"] = {slug: len(items) for slug, items in workflows["tenants"].items()}
        if args.ollama:
            def ollama_answer():
                api = f"http://127.0.0.1:{API_PORT}/api/v1"
                health = demo_smoke.call(api, "GET", "/health")[1]
                if health.get("llm_backend") != "ollama":
                    raise RuntimeError(f"the API reports llm_backend={health.get('llm_backend')}, expected ollama")
                token = demo_smoke.login(api, "apex-industrial", "apex.example.test", "engineer", password)
                status, body = demo_smoke.call(api, "POST", "/ai/ask", token, {"question": "What should I check when pump P-101 shows abnormal vibration?"}, timeout=240)
                if status != 200 or "ollama" not in str(body.get("llm_backend")):
                    raise RuntimeError(f"/ai/ask returned HTTP {status}, llm_backend={body.get('llm_backend') if isinstance(body, dict) else body}")
                return f"HTTP 200, llm_backend={body['llm_backend']}, grounded={body.get('grounded')}, citations={len(body.get('citations') or [])}"
            report["ollama_answer"] = step("a question answered by the host's Ollama from inside the container stack", ollama_answer)
        step("web UI container serves the app and proxies /api", lambda: (get(f"http://127.0.0.1:{UI_PORT}/") == 200 and get(f"http://127.0.0.1:{UI_PORT}/api/v1/health") == 200) or (_ for _ in ()).throw(RuntimeError("UI or proxy not answering 200")))
        report["running"] = sh(COMPOSE + ["ps", "--format", "{{.Service}}={{.State}}"], check=False).stdout.split()
        report["ok"] = True
    except Exception:  # noqa: BLE001
        report["logs_tail"] = sh(COMPOSE + ["logs", "--tail", "25"], check=False).stdout[-1500:]
    finally:
        if not args.keep:
            down = sh(COMPOSE + ["down", "-v", "--remove-orphans"], check=False)
            report["cleanup"] = {"compose_down_exit": down.returncode, "scope": f"project {PROJECT} only (its containers, network and volume)"}
            report["images_kept"] = list(IMAGES)
            if down.returncode:
                report["ok"] = False
        (outdir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        lines = [f"# Container smoke {run_id}: {'PASSED' if report['ok'] else 'FAILED'}", "", "| Step | Result | Seconds | Detail |", "|---|---|---|---|"]
        lines += [f"| {s['step']} | {'ok' if s['ok'] else 'FAILED'} | {s['seconds']} | {str(s['detail']).replace(chr(10), ' ')[:160]} |" for s in report["steps"]]
        lines += ["", f"New images: {report.get('images_new')}; built image sizes: {report.get('built_image_sizes')}", f"Docker disk (images) before: {report.get('disk_before', {}).get('Size')}, after build: {report.get('disk_after_build', {}).get('Size')}",
                  f"Workflow checks per tenant: {report.get('workflow_checks')}", f"Cleanup: {report.get('cleanup')}", ""]
        (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        print(f"report: {outdir / 'report.md'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
