"""Persistent settings manager.

Stores user-configurable settings (AI keys, repo URL, etc.)
in a JSON file that persists across restarts.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path("/var/lib/wifry/settings.json") if not settings.mock_mode else Path("/tmp/wifry-settings.json")

_user_settings: dict = {}


def _load() -> dict:
    global _user_settings
    if SETTINGS_PATH.exists():
        try:
            _user_settings = json.loads(SETTINGS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            _user_settings = {}
    return _user_settings


def _save() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(_user_settings, indent=2))


def get_all() -> dict:
    """Get all user settings (masks sensitive values)."""
    s = _load()
    return {
        "anthropic_api_key": _mask(s.get("anthropic_api_key", "")),
        "anthropic_api_key_set": bool(s.get("anthropic_api_key")),
        "openai_api_key": _mask(s.get("openai_api_key", "")),
        "openai_api_key_set": bool(s.get("openai_api_key")),
        "ai_provider": s.get("ai_provider", "anthropic"),
        "git_repo_url": s.get("git_repo_url", ""),
        "web_password_set": bool(s.get("web_password")),
        "ap_ssid": s.get("ap_ssid", settings.ap_ssid),
        "ap_password": _mask(s.get("ap_password", settings.ap_password)),
        "ap_channel": s.get("ap_channel", settings.ap_channel),
        "ap_band": s.get("ap_band", settings.ap_band),
    }


def update(updates: dict) -> dict:
    """Update settings. Only provided fields are changed."""
    s = _load()

    for key in ["anthropic_api_key", "openai_api_key", "ai_provider",
                 "git_repo_url", "ap_ssid", "ap_password", "ap_channel", "ap_band"]:
        if key in updates and updates[key] is not None:
            # Don't overwrite with masked values
            if isinstance(updates[key], str) and updates[key].startswith("****"):
                continue
            s[key] = updates[key]

    # Apply to runtime config
    if "anthropic_api_key" in s:
        settings.anthropic_api_key = s["anthropic_api_key"]
    if "openai_api_key" in s:
        settings.openai_api_key = s["openai_api_key"]
    if "ai_provider" in s:
        settings.ai_provider = s["ai_provider"]

    _user_settings.update(s)
    _save()

    logger.info("Settings updated: %s", [k for k in updates if k in s])
    return get_all()


async def change_password(current: str, new_password: str) -> dict:
    """Change the web UI password."""
    s = _load()
    stored = s.get("web_password", "")

    # If no password set yet, allow setting without current
    if stored and stored != current:
        return {"status": "error", "message": "Current password is incorrect"}

    s["web_password"] = new_password
    _user_settings.update(s)
    _save()

    logger.info("Web password changed")
    return {"status": "ok", "message": "Password updated"}


async def set_git_repo(url: str) -> dict:
    """Set the git remote URL for updates."""
    s = _load()
    s["git_repo_url"] = url
    _user_settings.update(s)
    _save()

    if not settings.mock_mode and url:
        await run("git", "-C", "/opt/wifry", "remote", "set-url", "origin", url, check=False)

    return {"status": "ok", "git_repo_url": url}


async def force_update() -> dict:
    """Force git pull and rebuild regardless of current state."""
    from . import updater
    return await updater.pull_update()


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "****" if value else ""
    return value[:4] + "****" + value[-4:]


# Load on import
_load()
