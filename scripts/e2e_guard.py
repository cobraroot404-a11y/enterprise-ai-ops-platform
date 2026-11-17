"""Environment guard for the end-to-end stack: it must only ever touch its own isolated, local resources."""
import os

ALLOWED_DATABASES = {"eaop_e2e", "eaop_e2e_real"}
ALLOWED_DB_HOSTS = {"127.0.0.1", "localhost", "::1"}
ISOLATED_PORTS = {8210, 8211, 8212, 8213, 8214, 8215, 8220}


class UnsafeEnvironment(SystemExit):
    pass


def check(db_name: str, ports: dict[str, int], environ: dict | None = None) -> None:
    """Raise UnsafeEnvironment (a SystemExit with a message) unless this is a local, non-production, isolated setup."""
    env = os.environ if environ is None else environ
    if env.get("EAOP_ENV", "development").strip().lower() in ("production", "prod"):
        raise UnsafeEnvironment("refusing to run the e2e stack when EAOP_ENV=production (it uses fixed test-only credentials)")
    if db_name not in ALLOWED_DATABASES:
        raise UnsafeEnvironment(f"refusing to use database '{db_name}': the e2e stack may only use {sorted(ALLOWED_DATABASES)}")
    host = env.get("DB_HOST", "127.0.0.1")
    if host not in ALLOWED_DB_HOSTS:
        raise UnsafeEnvironment(f"refusing to run against a non-local database host '{host}'")
    stray = {name: port for name, port in ports.items() if port not in ISOLATED_PORTS}
    if stray:
        raise UnsafeEnvironment(f"ports outside the isolated e2e range: {stray}")
