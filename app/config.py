"""Load config.default.yaml, optional config.yaml, then env overrides."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.paths import DEFAULT_CONFIG, ENV_FILE, USER_CONFIG, resolve


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_raspberry_pi() -> bool:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        text = cpuinfo.read_text(encoding="utf-8", errors="ignore").lower()
        if "raspberry pi" in text or "bcm27" in text:
            return True
    return Path("/sys/firmware/devicetree/base/model").is_file()


class Settings:
    def __init__(self, data: dict[str, Any]):
        self._data = data
        self.app = data.get("app", {})
        self.grok = data.get("grok", {})
        self.audio = data.get("audio", {})
        self.kiosk = data.get("kiosk", {})
        self.tools = data.get("tools", {})

    @property
    def dev_mode(self) -> bool:
        if _truthy(os.getenv("DEV_MODE")) or _truthy(os.getenv("GROK_BOT_DEV")):
            return True
        return bool(self.app.get("dev_mode"))

    @property
    def host(self) -> str:
        return os.getenv("GROK_BOT_HOST") or str(self.app.get("host", "127.0.0.1"))

    @property
    def port(self) -> int:
        raw = os.getenv("GROK_BOT_PORT")
        if raw:
            return int(raw)
        return int(self.app.get("port", 8080))

    @property
    def model(self) -> str:
        return os.getenv("GROK_MODEL") or str(self.grok.get("model", "grok-4.6"))

    @property
    def base_url(self) -> str:
        return os.getenv("XAI_BASE_URL") or str(self.grok.get("base_url", "https://api.x.ai/v1"))

    @property
    def api_key(self) -> str:
        return (os.getenv("XAI_API_KEY") or "").strip()

    @property
    def user_name(self) -> str:
        return str(self.app.get("user_name", "Teja"))

    @property
    def data_dir(self) -> Path:
        return resolve(self.app.get("data_dir", "data"))

    @property
    def music_dir(self) -> Path:
        return resolve(self.tools.get("music_dir", "data/music"))

    @property
    def screenshot_dir(self) -> Path:
        return resolve(self.tools.get("screenshot_dir", "data/screenshots"))

    @property
    def allowlist(self) -> list[dict[str, Any]]:
        return list(self.tools.get("allowlist") or [])

    def as_public_dict(self) -> dict[str, Any]:
        """Safe snapshot for /api/status — no secrets."""
        return {
            "name": self.app.get("name", "Grok Bot"),
            "user_name": self.user_name,
            "dev_mode": self.dev_mode,
            "model": self.model,
            "host": self.host,
            "port": self.port,
            "wake_word": (self.audio.get("wake_word") or {}).get("phrase", "hey grok"),
            "wake_enabled": bool((self.audio.get("wake_word") or {}).get("enabled", True)),
            "tap_to_talk": bool(self.audio.get("tap_to_talk", True)),
            "is_pi": is_raspberry_pi(),
        }


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv(ENV_FILE)
    if not DEFAULT_CONFIG.is_file():
        raise FileNotFoundError(f"Missing default config: {DEFAULT_CONFIG}")
    with DEFAULT_CONFIG.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    overlay_path = config_path or USER_CONFIG
    if overlay_path.is_file():
        with overlay_path.open(encoding="utf-8") as fh:
            overlay = yaml.safe_load(fh) or {}
        data = _deep_merge(data, overlay)
    return Settings(data)


# Convenience for `python -m app.devcheck` without spinning the server.
SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS
