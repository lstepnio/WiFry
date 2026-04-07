"""Service-level tests for release-critical network configuration flows."""

import importlib
import shutil

import pytest

from app.models.network_config import FullNetworkConfig
from app.services import network_config


def _cleanup_paths() -> None:
    network_config.CONFIG_PATH.unlink(missing_ok=True)
    shutil.rmtree(network_config.PROFILES_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_network_config_module():
    _cleanup_paths()
    reloaded = importlib.reload(network_config)
    yield reloaded
    _cleanup_paths()
    importlib.reload(network_config)


def test_current_config_defaults_are_safe(reset_network_config_module):
    config = reset_network_config_module.get_current_config()

    assert config.first_boot is True
    assert config.wifi_ap.ssid
    assert config.fallback.enabled is True


@pytest.mark.anyio
async def test_apply_config_persists_across_reload(reset_network_config_module):
    config = FullNetworkConfig()
    config.wifi_ap.ssid = "Release-Lab"
    config.wifi_ap.channel = 11
    config.ethernet.mode = "static"
    config.ethernet.static_ip = "192.168.50.2"
    config.ethernet.static_netmask = "255.255.255.0"
    config.ethernet.static_gateway = "192.168.50.1"

    await reset_network_config_module.apply_config(config)

    reloaded = importlib.reload(network_config)
    persisted = reloaded.get_current_config()

    assert persisted.first_boot is False
    assert persisted.wifi_ap.ssid == "Release-Lab"
    assert persisted.wifi_ap.channel == 11
    assert persisted.ethernet.mode == "static"
    assert persisted.ethernet.static_ip == "192.168.50.2"


@pytest.mark.anyio
async def test_profile_lifecycle_restores_saved_config(reset_network_config_module):
    baseline = FullNetworkConfig()
    baseline.wifi_ap.ssid = "Verification-Net"
    await reset_network_config_module.apply_config(baseline)

    profile = reset_network_config_module.save_profile(
        "Verification Profile",
        description="Used for release verification",
    )
    boot_profile = reset_network_config_module.set_boot_profile(profile.id)

    assert boot_profile.is_boot_profile is True
    assert any(p.id == profile.id for p in reset_network_config_module.list_profiles())

    changed = FullNetworkConfig()
    changed.wifi_ap.ssid = "Temporary-Net"
    await reset_network_config_module.apply_config(changed)

    restored = await reset_network_config_module.apply_profile(profile.id)
    assert restored.wifi_ap.ssid == "Verification-Net"

    reset_network_config_module.clear_boot_profile()
    assert reset_network_config_module.load_profile(profile.id).is_boot_profile is False

    reset_network_config_module.delete_profile(profile.id)
    assert reset_network_config_module.load_profile(profile.id) is None
