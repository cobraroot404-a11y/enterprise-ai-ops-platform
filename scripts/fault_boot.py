"""Start the API or the worker with a CONTROLLED, SIMULATED embedding outage switch (for the live ingestion checkpoint only; never used by the normal demo or in production).

    python scripts/fault_boot.py api   --port 8000      (the same app and options as `scripts/dev.py api`)
    python scripts/fault_boot.py worker                  (the same worker as `workers/run_worker.py`)

While the file named by EAOP_FAULT_FILE exists, the deterministic embedder raises when asked to embed text (the same failure mode as an unloadable embedding model: the code under test
sees an exception from `embed`). Removing the file ends the "outage" at once in every process that was started this way. This is a test harness: it demonstrates the retry logic
against that failure mode, it does NOT demonstrate a real infrastructure outage. Refuses to run when EAOP_ENV is production."""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def install() -> None:
    if os.environ.get("EAOP_ENV", "development").lower() in ("production", "prod"):
        sys.exit("fault_boot: refusing to install a fault switch when EAOP_ENV=production")
    fault_file = os.environ.get("EAOP_FAULT_FILE")
    if not fault_file:
        sys.exit("fault_boot: EAOP_FAULT_FILE is required")
    from app.ai import embeddings

    real = embeddings.DeterministicEmbedder.embed

    def embed(self, texts):
        if Path(fault_file).exists():
            raise RuntimeError("simulated embedding outage (fault switch present)")
        return real(self, texts)

    embeddings.DeterministicEmbedder.embed = embed


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in ("api", "worker"):
        sys.exit(__doc__)
    install()
    if argv[0] == "worker":
        sys.argv = ["workers/run_worker.py"]
        runpy.run_path(str(ROOT / "workers" / "run_worker.py"), run_name="__main__")
        return
    import uvicorn
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8000
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=port, app_dir=str(ROOT / "backend"))


if __name__ == "__main__":
    main(sys.argv[1:])
