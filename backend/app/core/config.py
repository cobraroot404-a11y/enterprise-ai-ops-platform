"""Application settings read from environment (and a local .env file for development)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Pinned embedding model revision (commit hash on the Hugging Face Hub) validated in Phase 3.
MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def load_dotenv(path: Path | None = None) -> None:
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_name: str
    db_host: str
    db_port: int
    owner_user: str
    owner_password: str
    app_db_password: str
    worker_db_password: str
    jwt_secret: str
    jwt_expire_minutes: int
    llm_backend: str
    embedding_backend: str
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"
    ollama_timeout: float = 240.0
    model_cache_dir: str = str(ROOT / "data" / "models")
    max_upload_bytes: int = 10 * 1024 * 1024
    max_json_bytes: int = 1024 * 1024
    evaluation_dir: str = str(ROOT / "evaluation")
    max_concurrent_ingest: int = 2
    max_concurrent_llm: int = 2  # a CPU-only local model: more parallel calls only slow everyone down
    busy_wait_seconds: float = 2.0
    api_rate_per_second: float = 20.0  # per tenant, per expensive operation (ask, extract, upload); shared across processes
    api_rate_burst: int = 100
    metrics_flush_seconds: float = 10.0

    def url(self, role: str) -> str:
        user, password = {
            "owner": (self.owner_user, self.owner_password),
            "app": ("eaop_app", self.app_db_password),
            "worker": ("eaop_worker", self.worker_db_password),
        }[role]
        return f"postgresql+psycopg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"


def get_settings(db_name: str | None = None) -> Settings:
    env = os.environ
    return Settings(
        db_name=db_name or env.get("POSTGRES_DB", "eaop"),
        db_host=env.get("DB_HOST", "127.0.0.1"),
        db_port=int(env.get("POSTGRES_PORT", "5432")),
        owner_user=env.get("POSTGRES_USER", "eaop"),
        owner_password=env.get("POSTGRES_PASSWORD", ""),
        app_db_password=env.get("APP_DB_PASSWORD", ""),
        worker_db_password=env.get("WORKER_DB_PASSWORD", ""),
        jwt_secret=env.get("JWT_SECRET", ""),
        jwt_expire_minutes=int(env.get("JWT_EXPIRE_MINUTES", "30")),
        llm_backend=env.get("LLM_BACKEND", "deterministic"),
        embedding_backend=env.get("EMBEDDING_BACKEND", "deterministic"),
        ollama_base_url=env.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").replace("localhost", "127.0.0.1"),
        ollama_model=env.get("OLLAMA_MODEL") or "qwen2.5:1.5b",
        ollama_timeout=float(env.get("OLLAMA_TIMEOUT", "240")),
        model_cache_dir=env.get("MODEL_CACHE_DIR", str(ROOT / "data" / "models")),
        max_upload_bytes=int(env.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        max_json_bytes=int(env.get("MAX_JSON_BYTES", str(1024 * 1024))),
        evaluation_dir=env.get("EVALUATION_DIR", str(ROOT / "evaluation")),
        max_concurrent_ingest=int(env.get("MAX_CONCURRENT_INGEST", "2")),
        max_concurrent_llm=int(env.get("MAX_CONCURRENT_LLM", "2")),
        busy_wait_seconds=float(env.get("BUSY_WAIT_SECONDS", "2")),
        api_rate_per_second=float(env.get("API_RATE_PER_SECOND", "20")),
        api_rate_burst=int(env.get("API_RATE_BURST", "100")),
        metrics_flush_seconds=float(env.get("METRICS_FLUSH_SECONDS", "10")),
    )
