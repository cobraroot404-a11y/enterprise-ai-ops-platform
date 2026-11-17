"""Apply Alembic migrations as the owner role. Run: python scripts/migrate.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = get_settings().url("owner")
    command.upgrade(cfg, "head")
    print("migrations applied")


if __name__ == "__main__":
    main()
