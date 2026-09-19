"""Runtime configuration. Everything is resolved lazily from the environment."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _PACKAGE_DIR.parent


def load_dotenv() -> list[Path]:
    """Load KEY=VALUE pairs from .env files without overriding real env vars.

    Looked up in order: current directory, project root, package directory.
    A bare line holding just an Anthropic key (sk-ant-...) is accepted as
    ANTHROPIC_API_KEY so a pasted key still works.
    """
    loaded: list[Path] = []
    candidates = [Path.cwd() / ".env", _PROJECT_DIR / ".env", _PACKAGE_DIR / ".env"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
            elif line.startswith("sk-ant-"):
                key, value = "ANTHROPIC_API_KEY", line
            else:
                continue
            if key and value and key not in os.environ:
                os.environ[key] = value
        loaded.append(path)
    return loaded


load_dotenv()


def home() -> Path:
    """Data directory. Override with JOBHUNT_HOME."""
    raw = os.environ.get("JOBHUNT_HOME")
    path = Path(raw) if raw else Path(__file__).resolve().parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return home() / "jobhunt.db"


def out_dir() -> Path:
    path = home() / "out"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model() -> str:
    return os.environ.get("JOBHUNT_MODEL", DEFAULT_MODEL)
