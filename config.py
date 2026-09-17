import os
import sys
from pathlib import Path

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def get_database_uri() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            data_dir = Path(os.environ.get("APPDATA", Path.home())) / "Foco"
        else:
            data_dir = Path.home() / ".local" / "share" / "Foco"

        data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{data_dir / 'focus.db'}"

    instance_dir = os.path.join(BASE_DIR, "instance")
    os.makedirs(instance_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(instance_dir, 'focus.db')}"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-troque-em-producao")
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    FOCUS_DEBUG_TOOLS = os.environ.get("FOCUS_DEBUG_TOOLS", "1") == "1"

