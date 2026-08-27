"""Project paths. All relative config paths resolve against the repo root."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
UI_DIR = ROOT / "ui"
DEFAULT_CONFIG = ROOT / "config.default.yaml"
USER_CONFIG = ROOT / "config.yaml"
ENV_FILE = ROOT / ".env"
MODELS_DIR = ROOT / "models"
DATA_DIR = ROOT / "data"


def resolve(path: str | Path, base: Path | None = None) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return (base or ROOT) / p
