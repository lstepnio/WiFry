"""Feature flags for controlling which features are enabled.

Allows disabling features that aren't ready for production while
keeping the code in the codebase. Flags are persisted to disk
and exposed via API so the frontend can hide disabled features.

Default states reflect what's RPi-ready vs what needs more testing.
Admins can override any flag via the Settings UI or API.
"""

import json
import logging
from pathlib import Path
from typing import Dict

from ..config import settings

logger = logging.getLogger(__name__)

FLAGS_PATH = Path("/var/lib/wifry/feature_flags.json") if not settings.mock_mode else Path("/tmp/wifry-feature-flags.json")

# Default feature flags — True = enabled, False = disabled
# Features marked False are not ready for production use
DEFAULTS: Dict[str, dict] = {
    # Core features — ready
    "impairments_network": {"enabled": True, "label": "Network Impairments", "description": "tc netem delay, jitter, loss, corruption, reorder, bandwidth", "category": "core"},
    "impairments_wifi": {"enabled": True, "label": "WiFi Impairments", "description": "Channel interference, TX power, band switch, deauth, DHCP disruption, broadcast storm, rate limit, periodic disconnect", "category": "core"},
    "impairments_profiles": {"enabled": True, "label": "Impairment Profiles", "description": "One-click presets for network + WiFi + DNS conditions", "category": "core"},
    "sessions": {"enabled": True, "label": "Test Sessions", "description": "Artifact correlation, support bundles, sharing", "category": "core"},
    "captures": {"enabled": True, "label": "Packet Captures", "description": "tshark packet capture with BPF filters", "category": "core"},
    "adb": {"enabled": True, "label": "ADB Device Control", "description": "Connect, shell, logcat, screenshot, bugreport for Android STBs", "category": "core"},

    # Analysis features — ready
    "ai_analysis": {"enabled": True, "label": "AI Capture Analysis", "description": "Anthropic Claude / OpenAI GPT analysis of packet captures", "category": "analysis"},
    "speed_test_iperf": {"enabled": True, "label": "iperf3 Speed Test", "description": "LAN throughput measurement through impairment path", "category": "tools"},
    "wifi_scanner": {"enabled": True, "label": "WiFi Scanner", "description": "2.4/5GHz channel utilization and neighbor survey", "category": "tools"},

    # Features with software deps satisfied by install.sh — enabled
    "dns_simulation": {"enabled": True, "label": "DNS Simulation", "description": "CoreDNS-based DNS impairments, NXDOMAIN injection, failover testing.", "category": "advanced",
        "disabled_reason": "Requires CoreDNS binary. Installed by install.sh. Check System > Dependencies to verify."},
    "streams": {"enabled": True, "label": "Stream Monitoring", "description": "HLS/DASH stream analysis via mitmproxy transparent proxy.", "category": "advanced",
        "disabled_reason": "Requires mitmproxy (installed by install.sh) AND the mitmproxy CA certificate installed on the STB. Without the CA cert, HTTPS streams can't be inspected."},
    "teleport": {"enabled": True, "label": "Teleport VPN", "description": "Geo-shift STB traffic through remote networks via VPN.", "category": "advanced",
        "disabled_reason": "WireGuard/OpenVPN tools installed. You still need a VPN config file from your network/secops team to create a Teleport profile."},
    "speed_test_ookla": {"enabled": True, "label": "Ookla Speedtest", "description": "Official Ookla Speedtest CLI for real internet speed measurement.", "category": "tools",
        "disabled_reason": "Requires the Ookla Speedtest CLI binary. Installed by install.sh."},
    "video_probe": {"enabled": True, "label": "Video Quality Probe", "description": "Analyze saved video segments for codec info, bitrate, and keyframe intervals.", "category": "advanced",
        "disabled_reason": "Requires ffmpeg/ffprobe. Installed by install.sh."},

    # Features needing physical hardware — disabled by default
    "hdmi_capture": {"enabled": False, "label": "HDMI Capture", "description": "Capture HDMI output from STBs for visual analysis.", "category": "advanced",
        "disabled_reason": "Requires an Elgato Cam Link 4K (or compatible UVC USB capture device) physically plugged into the RPi's USB port. v4l-utils is installed but no device detected."},

    # Sharing features — ready
    "sharing_tunnel": {"enabled": True, "label": "Cloudflare Tunnel", "description": "Share WiFry UI via temporary public URL", "category": "sharing", "disabled_reason": ""},
    "sharing_fileio": {"enabled": True, "label": "file.io Upload", "description": "One-click file sharing with expiring links", "category": "sharing", "disabled_reason": ""},
    "collaboration": {"enabled": True, "label": "Collaboration Mode", "description": "Real-time shadow/co-pilot mode for remote users via WebSocket sync.", "category": "sharing",
        "disabled_reason": "Experimental feature. Uses WebSockets for real-time sync between multiple users connected via Cloudflare Tunnel."},

    # Easter egg
    "gremlin": {"enabled": True, "label": "Network Chaos Mode", "description": "Konami code easter egg for non-deterministic chaos", "category": "fun"},
}

_flags: Dict[str, dict] = {}
_loaded = False


def _load() -> None:
    global _flags, _loaded
    if _loaded:
        return

    # Start with defaults
    _flags = {k: {**v} for k, v in DEFAULTS.items()}

    # Override with saved values
    if FLAGS_PATH.exists():
        try:
            saved = json.loads(FLAGS_PATH.read_text())
            for key, val in saved.items():
                if key in _flags and isinstance(val, dict):
                    _flags[key]["enabled"] = val.get("enabled", _flags[key]["enabled"])
        except (json.JSONDecodeError, OSError):
            pass

    _loaded = True


def _save() -> None:
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Only save overrides (not full defaults)
    overrides = {}
    for key, flag in _flags.items():
        if key in DEFAULTS and flag["enabled"] != DEFAULTS[key]["enabled"]:
            overrides[key] = {"enabled": flag["enabled"]}
    FLAGS_PATH.write_text(json.dumps(overrides, indent=2))


def get_all() -> Dict[str, dict]:
    """Get all feature flags with their current state."""
    _load()
    return _flags


def is_enabled(flag_name: str) -> bool:
    """Check if a specific feature is enabled."""
    _load()
    flag = _flags.get(flag_name)
    return flag["enabled"] if flag else False


def set_flag(flag_name: str, enabled: bool) -> Dict[str, dict]:
    """Enable or disable a feature flag."""
    _load()
    if flag_name not in _flags:
        raise ValueError(f"Unknown feature flag: {flag_name}")
    _flags[flag_name]["enabled"] = enabled
    _save()
    logger.info("Feature flag '%s' set to %s", flag_name, enabled)
    return _flags


def reset_defaults() -> Dict[str, dict]:
    """Reset all flags to defaults."""
    global _flags, _loaded
    _flags = {k: {**v} for k, v in DEFAULTS.items()}
    _loaded = True
    _save()
    logger.info("Feature flags reset to defaults")
    return _flags
