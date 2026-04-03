"""Network configuration service.

Manages WiFi AP and Ethernet settings with safe defaults and lockout prevention.

Boot sequence:
  1. Apply fallback IP on eth0 (always — can't be disabled)
  2. Load saved config from disk (if exists and first_boot=False)
  3. If no saved config or first_boot=True, use safe defaults
  4. Apply WiFi AP config (hostapd + dnsmasq)
  5. Apply Ethernet config (DHCP or static)

The fallback IP (169.254.42.1) is a link-local address that's always
assigned as a secondary IP on eth0. Connect a laptop directly to the
RPi's ethernet port and navigate to http://169.254.42.1:8080 to access
the app even if everything else is misconfigured.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.network_config import (
    DEFAULTS,
    EthernetConfig,
    FallbackConfig,
    FullNetworkConfig,
    NetworkConfigProfile,
    WifiApConfig,
)
from ..utils.shell import run

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("/var/lib/wifry/network_config.json") if not settings.mock_mode else Path("/tmp/wifry-network-config.json")
PROFILES_DIR = Path("/var/lib/wifry/network-profiles") if not settings.mock_mode else Path("/tmp/wifry-network-profiles")

_current_config: Optional[FullNetworkConfig] = None
_profiles: Dict[str, NetworkConfigProfile] = {}


def _ensure_dirs() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def get_current_config() -> FullNetworkConfig:
    """Get the current network configuration."""
    global _current_config
    if _current_config is None:
        _current_config = _load_config()
    return _current_config


def is_first_boot() -> bool:
    """Check if this is the first boot (no custom config saved yet)."""
    return get_current_config().first_boot


async def apply_config(config: FullNetworkConfig) -> FullNetworkConfig:
    """Apply and save a new network configuration.

    This marks first_boot=False so the banner won't show again.
    """
    global _current_config

    config.first_boot = False
    _current_config = config
    _save_config(config)

    if not settings.mock_mode:
        await _apply_fallback(config.fallback)
        await _apply_wifi_ap(config.wifi_ap)
        await _apply_ethernet(config.ethernet)

    logger.info("Network config applied (SSID=%s, eth=%s)", config.wifi_ap.ssid, config.ethernet.mode)
    return config


async def apply_defaults() -> FullNetworkConfig:
    """Reset to safe defaults."""
    config = FullNetworkConfig()
    config.first_boot = False
    return await apply_config(config)


async def boot_apply() -> None:
    """Called on startup to apply the saved config (or defaults).

    Priority: boot profile > saved config > safe defaults.
    Fallback IP is always applied first regardless.
    """
    config = get_current_config()

    if not settings.mock_mode:
        # Always apply fallback first (lockout prevention)
        await _apply_fallback(config.fallback)

        # Check for a designated boot profile
        _load_profiles()
        boot_profile = next((p for p in _profiles.values() if p.is_boot_profile), None)

        if boot_profile:
            logger.info("Applying boot profile: %s", boot_profile.name)
            await _apply_wifi_ap(boot_profile.config.wifi_ap)
            await _apply_ethernet(boot_profile.config.ethernet)
        elif not config.first_boot:
            await _apply_wifi_ap(config.wifi_ap)
            await _apply_ethernet(config.ethernet)
        else:
            # First boot — use safe defaults
            defaults = FullNetworkConfig()
            await _apply_wifi_ap(defaults.wifi_ap)
            await _apply_ethernet(defaults.ethernet)

    logger.info("Boot network config applied (first_boot=%s)", config.first_boot)


# --- Config profiles ---

def save_profile(name: str, description: str = "") -> NetworkConfigProfile:
    """Save the current config as a named profile."""
    config = get_current_config()
    profile_id = uuid.uuid4().hex[:10]

    profile = NetworkConfigProfile(
        id=profile_id,
        name=name,
        description=description,
        config=config.model_copy(deep=True),
    )

    _profiles[profile_id] = profile
    _save_profile(profile)
    return profile


def list_profiles() -> List[NetworkConfigProfile]:
    _load_profiles()
    return list(_profiles.values())


def load_profile(profile_id: str) -> Optional[NetworkConfigProfile]:
    _load_profiles()
    return _profiles.get(profile_id)


def set_boot_profile(profile_id: str) -> NetworkConfigProfile:
    """Mark a profile to be loaded on boot. Clears any previous boot profile."""
    _load_profiles()
    for p in _profiles.values():
        if p.is_boot_profile:
            p.is_boot_profile = False
            _save_profile(p)

    profile = _profiles.get(profile_id)
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")
    profile.is_boot_profile = True
    _save_profile(profile)
    logger.info("Boot profile set: %s (%s)", profile.name, profile_id)
    return profile


def clear_boot_profile() -> None:
    """Clear boot profile — will use safe defaults on next boot."""
    _load_profiles()
    for p in _profiles.values():
        if p.is_boot_profile:
            p.is_boot_profile = False
            _save_profile(p)
    logger.info("Boot profile cleared — will use defaults")


def delete_profile(profile_id: str) -> None:
    _profiles.pop(profile_id, None)
    (PROFILES_DIR / f"{profile_id}.json").unlink(missing_ok=True)


async def apply_profile(profile_id: str) -> FullNetworkConfig:
    """Load and apply a saved profile."""
    profile = load_profile(profile_id)
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")
    return await apply_config(profile.config)


# --- Apply implementations ---

async def _apply_fallback(fallback: FallbackConfig) -> None:
    """Ensure fallback IP is always on eth0 as a secondary address."""
    if not fallback.enabled:
        return

    # Add as secondary IP (won't conflict with DHCP)
    await run(
        "ip", "addr", "add",
        f"{fallback.ip}/{fallback.netmask}",
        "dev", "eth0",
        "label", "eth0:fallback",
        sudo=True, check=False,  # OK if already exists
    )
    logger.info("Fallback IP %s applied on eth0:fallback", fallback.ip)


async def _apply_wifi_ap(ap: WifiApConfig) -> None:
    """Apply WiFi AP configuration via hostapd + dnsmasq."""
    from . import hostapd

    await hostapd.write_and_restart_hostapd(
        ssid=ap.ssid,
        password=ap.password,
        channel=ap.channel,
        band=ap.band,
        country_code=ap.country_code,
    )

    await hostapd.setup_ap_networking()
    await hostapd.write_and_restart_dnsmasq()

    logger.info("WiFi AP applied: SSID=%s, ch=%d, band=%s", ap.ssid, ap.channel, ap.band)


async def _apply_ethernet(eth: EthernetConfig) -> None:
    """Apply Ethernet configuration."""
    if eth.mode == "static" and eth.static_ip:
        # Set static IP
        await run("ip", "addr", "flush", "dev", "eth0", sudo=True, check=False)
        await run(
            "ip", "addr", "add",
            f"{eth.static_ip}/{eth.static_netmask}",
            "dev", "eth0",
            sudo=True, check=True,
        )
        if eth.static_gateway:
            await run(
                "ip", "route", "add", "default",
                "via", eth.static_gateway, "dev", "eth0",
                sudo=True, check=False,
            )
        if eth.static_dns:
            # Write resolv.conf
            await run(
                "sh", "-c",
                f'echo "nameserver {eth.static_dns}" > /etc/resolv.conf',
                sudo=True, check=False,
            )
        logger.info("Ethernet static: %s/%s gw=%s", eth.static_ip, eth.static_netmask, eth.static_gateway)
    else:
        # DHCP mode — ensure dhcpcd is running
        await run("systemctl", "restart", "dhcpcd", sudo=True, check=False)
        logger.info("Ethernet DHCP mode")


# --- Persistence ---

def _save_config(config: FullNetworkConfig) -> None:
    _ensure_dirs()
    CONFIG_PATH.write_text(config.model_dump_json(indent=2))


def _load_config() -> FullNetworkConfig:
    if CONFIG_PATH.exists():
        try:
            return FullNetworkConfig.model_validate_json(CONFIG_PATH.read_text())
        except Exception:
            pass
    return FullNetworkConfig()  # Safe defaults


def _save_profile(profile: NetworkConfigProfile) -> None:
    _ensure_dirs()
    (PROFILES_DIR / f"{profile.id}.json").write_text(profile.model_dump_json(indent=2))


def _load_profiles() -> None:
    _ensure_dirs()
    for f in PROFILES_DIR.glob("*.json"):
        pid = f.stem
        if pid not in _profiles:
            try:
                _profiles[pid] = NetworkConfigProfile.model_validate_json(f.read_text())
            except Exception:
                pass
