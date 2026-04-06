"""WiFi driver capability detection.

Probes the WiFi hardware to determine what features are supported,
so the UI can disable unsupported impairment types with explanations.

Runs once at startup and caches results.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)


@dataclass
class WifiCapabilities:
    """What the WiFi hardware/driver supports."""

    phy: str = ""
    driver: str = ""
    ap_mode: bool = False
    band_5ghz: bool = False
    tx_power_control: bool = False
    rts_threshold: bool = False
    bitrate_control: bool = False
    channel_switching: bool = False
    supported_channels_2g: List[int] = field(default_factory=list)
    supported_channels_5g: List[int] = field(default_factory=list)
    max_tx_power_dbm: int = 0
    hping3_available: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to a dict suitable for JSON serialization."""
        return {
            "phy": self.phy,
            "driver": self.driver,
            "ap_mode": self.ap_mode,
            "band_5ghz": self.band_5ghz,
            "tx_power_control": self.tx_power_control,
            "rts_threshold": self.rts_threshold,
            "bitrate_control": self.bitrate_control,
            "channel_switching": self.channel_switching,
            "supported_channels_2g": self.supported_channels_2g,
            "supported_channels_5g": self.supported_channels_5g,
            "max_tx_power_dbm": self.max_tx_power_dbm,
            "hping3_available": self.hping3_available,
            "error": self.error,
            # Feature availability with reasons
            "features": self._feature_map(),
        }

    def _feature_map(self) -> dict:
        """Map each WiFi impairment feature to supported/reason."""
        return {
            "channel_interference": {
                "supported": self.rts_threshold,
                "reason": "" if self.rts_threshold else "WiFi driver does not support RTS threshold control",
            },
            "tx_power": {
                "supported": self.tx_power_control,
                "reason": "" if self.tx_power_control else "WiFi driver does not support TX power control",
            },
            "band_switch": {
                "supported": self.channel_switching,
                "reason": "" if self.channel_switching else "WiFi driver does not support channel switching in AP mode",
            },
            "band_5ghz": {
                "supported": self.band_5ghz and len(self.supported_channels_5g) > 0,
                "reason": "" if (self.band_5ghz and len(self.supported_channels_5g) > 0)
                    else "WiFi hardware does not support 5GHz",
            },
            "deauth": {
                "supported": self.ap_mode,
                "reason": "" if self.ap_mode else "AP mode not supported",
            },
            "dhcp_disruption": {
                "supported": True,
                "reason": "",
            },
            "broadcast_storm": {
                "supported": self.hping3_available,
                "reason": "" if self.hping3_available else "hping3 not installed (apt install hping3)",
            },
            "rate_limit": {
                "supported": self.bitrate_control,
                "reason": "" if self.bitrate_control else "WiFi driver does not support bitrate control",
            },
            "periodic_disconnect": {
                "supported": self.ap_mode,
                "reason": "" if self.ap_mode else "AP mode not supported",
            },
        }


_cached: Optional[WifiCapabilities] = None


async def detect_capabilities(interface: str = "") -> WifiCapabilities:
    """Detect WiFi driver capabilities by probing iw and testing commands.

    Results are cached after first call.
    """
    global _cached
    if _cached is not None:
        return _cached

    iface = interface or settings.ap_interface or "wlan0"

    if settings.mock_mode:
        # In mock mode, report everything as supported
        caps = WifiCapabilities(
            ap_mode=True, band_5ghz=True, tx_power_control=True,
            rts_threshold=True, bitrate_control=True, channel_switching=True,
            supported_channels_2g=[1, 6, 11], supported_channels_5g=[36, 40, 44, 48],
            max_tx_power_dbm=31, hping3_available=True,
        )
        _cached = caps
        return caps

    caps = WifiCapabilities()

    # Check hping3
    hping_result = await run("which", "hping3", check=False)
    caps.hping3_available = hping_result.success

    # Find the phy for this interface
    result = await run("iw", "dev", iface, "info", sudo=True, check=False)
    if not result.success:
        caps.error = f"Interface {iface} not found"
        _cached = caps
        logger.warning("WiFi capability detection failed: %s", caps.error)
        return caps

    phy_match = re.search(r"wiphy (\d+)", result.stdout)
    if phy_match:
        caps.phy = f"phy{phy_match.group(1)}"

    # Get driver info
    driver_result = await run("readlink", f"/sys/class/net/{iface}/device/driver", check=False)
    if driver_result.success:
        caps.driver = driver_result.stdout.strip().split("/")[-1]

    # Get full phy info
    if not caps.phy:
        caps.error = "Could not determine phy"
        _cached = caps
        return caps

    result = await run("iw", "phy", caps.phy, "info", sudo=True, check=False)
    if not result.success:
        caps.error = f"Could not read phy info for {caps.phy}"
        _cached = caps
        return caps

    info = result.stdout

    # AP mode support
    caps.ap_mode = "* AP" in info

    # Band 2 (5GHz) support
    caps.band_5ghz = "Band 2:" in info

    # Parse channels and TX power
    in_band1 = False
    in_band2 = False
    for line in info.splitlines():
        if "Band 1:" in line:
            in_band1, in_band2 = True, False
        elif "Band 2:" in line:
            in_band1, in_band2 = False, True
        elif re.match(r"\s*Band \d+:", line):
            in_band1, in_band2 = False, False

        chan_match = re.search(r"\* (\d+) MHz \[(\d+)\]", line)
        if chan_match and "(disabled)" not in line and "(no IR)" not in line:
            freq = int(chan_match.group(1))
            chan = int(chan_match.group(2))
            if in_band1 and 2400 <= freq <= 2500:
                caps.supported_channels_2g.append(chan)
            elif in_band2 and freq >= 5000:
                caps.supported_channels_5g.append(chan)

        dbm_match = re.search(r"\((\d+\.?\d*) dBm\)", line)
        if dbm_match:
            power = int(float(dbm_match.group(1)))
            if power > caps.max_tx_power_dbm:
                caps.max_tx_power_dbm = power

    # --- Probe actual capabilities by testing commands ---

    # TX power control
    test = await run("iw", "dev", iface, "set", "txpower", "fixed", "1000",
                     sudo=True, check=False)
    caps.tx_power_control = test.success
    if test.success:
        await run("iw", "dev", iface, "set", "txpower", "auto",
                  sudo=True, check=False)

    # RTS threshold (most Broadcom drivers don't support this)
    test = await run("iw", "phy", caps.phy, "set", "rts", "500",
                     sudo=True, check=False)
    caps.rts_threshold = test.success
    if test.success:
        await run("iw", "phy", caps.phy, "set", "rts", "off",
                  sudo=True, check=False)

    # Bitrate control
    test = await run("iw", "dev", iface, "set", "bitrates", "legacy-2.4", "6", "12", "24",
                     sudo=True, check=False)
    caps.bitrate_control = test.success
    if test.success:
        await run("iw", "dev", iface, "set", "bitrates",
                  sudo=True, check=False)

    # Channel switching (use hostapd_cli to test — only works if hostapd is running)
    test = await run("hostapd_cli", "-i", iface, "status",
                     sudo=True, check=False)
    caps.channel_switching = test.success  # If hostapd_cli works, CSA should work

    _cached = caps
    logger.info(
        "WiFi capabilities detected: ap=%s, 5ghz=%s, tx_power=%s, rts=%s, bitrate=%s, csa=%s, hping3=%s",
        caps.ap_mode, caps.band_5ghz, caps.tx_power_control,
        caps.rts_threshold, caps.bitrate_control, caps.channel_switching,
        caps.hping3_available,
    )
    return caps


def get_cached() -> Optional[WifiCapabilities]:
    """Get cached capabilities (None if not yet detected)."""
    return _cached


def clear_cache() -> None:
    """Clear cached capabilities (for testing)."""
    global _cached
    _cached = None
