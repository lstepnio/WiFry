"""WiFi driver capability detection for hardware-aware test skipping.

Parses `iw phy info` to determine what the WiFi hardware supports,
so tests can auto-skip features the driver doesn't implement.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.utils.shell import run


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
    error: Optional[str] = None


_cached: Optional[WifiCapabilities] = None


async def detect_capabilities(interface: str = "wlan0") -> WifiCapabilities:
    """Detect WiFi driver capabilities by parsing iw output.

    Results are cached after first call.
    """
    global _cached
    if _cached is not None:
        return _cached

    caps = WifiCapabilities()

    # Find the phy for this interface
    result = await run("iw", "dev", interface, "info", sudo=True, check=False)
    if not result.success:
        caps.error = f"Interface {interface} not found"
        _cached = caps
        return caps

    phy_match = re.search(r"wiphy (\d+)", result.stdout)
    if phy_match:
        caps.phy = f"phy{phy_match.group(1)}"

    # Get full phy info
    if caps.phy:
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

        # Parse 2.4GHz channels
        in_band1 = False
        in_band2 = False
        for line in info.splitlines():
            if "Band 1:" in line:
                in_band1 = True
                in_band2 = False
            elif "Band 2:" in line:
                in_band1 = False
                in_band2 = True
            elif "Band " in line:
                in_band1 = False
                in_band2 = False

            chan_match = re.search(r"\* (\d+) MHz \[(\d+)\]", line)
            if chan_match and "(disabled)" not in line:
                freq = int(chan_match.group(1))
                chan = int(chan_match.group(2))
                if in_band1 and 2400 <= freq <= 2500:
                    caps.supported_channels_2g.append(chan)
                elif in_band2 and freq >= 5000:
                    caps.supported_channels_5g.append(chan)

            # Max TX power
            dbm_match = re.search(r"\((\d+\.?\d*) dBm\)", line)
            if dbm_match:
                power = int(float(dbm_match.group(1)))
                if power > caps.max_tx_power_dbm:
                    caps.max_tx_power_dbm = power

        # TX power control: try setting and reverting
        test_result = await run(
            "iw", "dev", interface, "set", "txpower", "fixed", "1000",
            sudo=True, check=False,
        )
        caps.tx_power_control = test_result.success
        if test_result.success:
            await run("iw", "dev", interface, "set", "txpower", "auto",
                      sudo=True, check=False)

        # RTS threshold: check if iw supports it
        # (Broadcom on RPi5 doesn't report RTS in phy info)
        caps.rts_threshold = "Device supports roaming" not in info  # Heuristic

        # Bitrate control: try setting and reverting
        test_result = await run(
            "iw", "dev", interface, "set", "bitrates", "legacy-2.4", "6", "12", "24",
            sudo=True, check=False,
        )
        caps.bitrate_control = test_result.success
        if test_result.success:
            await run("iw", "dev", interface, "set", "bitrates",
                      sudo=True, check=False)

        # Channel switching: check if hostapd_cli chan_switch works
        caps.channel_switching = "* AP" in info  # If AP mode works, CSA likely works

    _cached = caps
    return caps


def clear_cache() -> None:
    """Clear cached capabilities (for testing)."""
    global _cached
    _cached = None
