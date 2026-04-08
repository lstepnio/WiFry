"""Feature flags for controlling which features are enabled.

Flags define the product surface that should be visible by default.
Supported workflows stay on; opt-in or environment-dependent tools can
remain in the codebase while being hidden from the primary UI.

Flags are persisted to disk and exposed via API so the frontend can
make conservative visibility decisions even during startup.
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
    "sessions": {"enabled": True, "label": "Test Sessions", "description": "Primary workflow for artifact correlation, support bundles, and supported sharing", "category": "core"},
    "captures": {"enabled": True, "label": "Packet Captures", "description": "tshark packet capture with BPF filters", "category": "core"},
    "adb": {"enabled": False, "label": "ADB Device Control", "description": "Connect, shell, logcat, screenshot, bugreport for Android STBs", "category": "core",
        "disabled_reason": "Enable when an Android STB is connected via ADB over network."},

    # Analysis features — ready
    "ai_analysis": {"enabled": True, "label": "AI Capture Analysis", "description": "Anthropic Claude / OpenAI GPT analysis of packet captures", "category": "analysis"},
    "speed_test_iperf": {"enabled": True, "label": "iperf3 Speed Test", "description": "LAN throughput measurement through impairment path", "category": "tools"},
    "wifi_scanner": {"enabled": True, "label": "WiFi Scanner", "description": "2.4/5GHz channel utilization and neighbor survey", "category": "tools"},

    # Features with software deps satisfied by install.sh — enabled
    "dns_simulation": {"enabled": True, "label": "DNS Simulation", "description": "CoreDNS-based DNS impairments, NXDOMAIN injection, failover testing.", "category": "advanced",
        "disabled_reason": "Requires CoreDNS binary. Installed by install.sh. Check System > Dependencies to verify."},
    "streams": {"enabled": False, "label": "Stream Monitoring", "description": "HLS/DASH stream analysis via mitmproxy transparent proxy.", "category": "advanced",
        "disabled_reason": "Requires mitmproxy AND the mitmproxy CA certificate installed on the STB. Enable when ready to intercept HTTPS streams."},
    "teleport": {"enabled": False, "label": "Teleport VPN", "description": "Geo-shift STB traffic through remote networks via VPN.", "category": "advanced",
        "disabled_reason": "Requires a VPN config file from your network/secops team. Enable when ready to create a Teleport profile."},
    "speed_test_ookla": {"enabled": True, "label": "Ookla Speedtest", "description": "Official Ookla Speedtest CLI for real internet speed measurement.", "category": "tools",
        "disabled_reason": "Requires the Ookla Speedtest CLI binary. Installed by install.sh."},
    "video_probe": {"enabled": False, "label": "Video Quality Probe", "description": "Analyze saved video segments for codec info, bitrate, and keyframe intervals.", "category": "advanced",
        "disabled_reason": "Enable when analyzing HLS/DASH streams or local media segments."},

    # Features needing physical hardware — disabled by default
    "hdmi_capture": {"enabled": False, "label": "HDMI Capture", "description": "Capture HDMI output from STBs for visual analysis.", "category": "advanced",
        "disabled_reason": "Requires an Elgato Cam Link 4K (or compatible UVC USB capture device) physically plugged into the RPi's USB port. v4l-utils is installed but no device detected."},

    # EXPERIMENTAL_VIDEO_CAPTURE — Experimental live HDMI video stream
    "experimental_video_capture": {"enabled": False, "label": "Live Video Stream (Experimental)", "description": "MJPEG live stream from a UVC HDMI capture device. Experimental — may be removed.", "category": "experimental",
        "disabled_reason": "Experimental. Requires Elgato Cam Link 4K (or compatible UVC device) and opencv-python."},

    # Sharing features — supported path stays session-centric; live access is opt-in
    "sharing_tunnel": {"enabled": False, "label": "Live Remote Access", "description": "Expose the WiFry UI through a temporary public URL for live troubleshooting.", "category": "sharing",
        "disabled_reason": "Experimental surface. Off by default. Use Session bundles for standard evidence sharing."},
    "sharing_fileio": {"enabled": True, "label": "Session Bundle Sharing", "description": "Generate expiring support-bundle links from Session details.", "category": "sharing", "disabled_reason": ""},
    "collaboration": {"enabled": False, "label": "Live Collaboration", "description": "Real-time co-pilot navigation sync for remote users connected through the tunnel.", "category": "sharing",
        "disabled_reason": "Experimental surface. Requires Live Remote Access and working WebSocket connectivity."},

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
