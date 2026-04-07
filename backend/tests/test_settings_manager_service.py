"""Service-level tests for durable operator settings."""

import importlib
import json

import pytest

from app.services import settings_manager


@pytest.fixture(autouse=True)
def reset_settings_module():
    settings_manager.SETTINGS_PATH.unlink(missing_ok=True)
    settings_manager._user_settings.clear()
    reloaded = importlib.reload(settings_manager)
    yield reloaded
    reloaded.SETTINGS_PATH.unlink(missing_ok=True)
    reloaded._user_settings.clear()
    importlib.reload(settings_manager)


def test_update_persists_and_masks_sensitive_values(reset_settings_module):
    result = reset_settings_module.update({
        "ai_provider": "openai",
        "anthropic_api_key": "sk-ant-test-12345678",
        "git_repo_url": "https://github.com/example/wifry.git",
        "ap_channel": 11,
    })

    saved = json.loads(reset_settings_module.SETTINGS_PATH.read_text())
    reloaded = importlib.reload(settings_manager)
    masked = reloaded.get_all()

    assert result["ai_provider"] == "openai"
    assert saved["anthropic_api_key"] == "sk-ant-test-12345678"
    assert saved["ap_channel"] == 11
    assert masked["anthropic_api_key_set"] is True
    assert masked["anthropic_api_key"].startswith("sk-a")
    assert masked["git_repo_url"] == "https://github.com/example/wifry.git"


@pytest.mark.anyio
async def test_change_password_requires_current_password_after_first_set(reset_settings_module):
    first = await reset_settings_module.change_password("", "first-pass")
    second = await reset_settings_module.change_password("wrong-pass", "new-pass")
    third = await reset_settings_module.change_password("first-pass", "final-pass")

    assert first["status"] == "ok"
    assert second["status"] == "error"
    assert third["status"] == "ok"


@pytest.mark.anyio
async def test_set_git_repo_updates_saved_url(reset_settings_module):
    result = await reset_settings_module.set_git_repo("https://github.com/example/release.git")
    saved = json.loads(reset_settings_module.SETTINGS_PATH.read_text())

    assert result["status"] == "ok"
    assert result["git_repo_url"] == "https://github.com/example/release.git"
    assert saved["git_repo_url"] == "https://github.com/example/release.git"
