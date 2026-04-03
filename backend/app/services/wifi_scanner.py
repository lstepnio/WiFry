"""WiFi environment scanner.

Scans 2.4GHz and 5GHz channels for neighboring networks using
iw/iwlist to show channel utilization, signal strength, and interference.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)


@dataclass
class WifiNetwork:
    """A detected WiFi network."""

    ssid: str
    bssid: str
    channel: int
    frequency_mhz: int
    signal_dbm: int
    security: str  # "WPA2", "WPA3", "Open", etc.
    band: str  # "2.4GHz" or "5GHz"
    width: str = ""  # "20MHz", "40MHz", "80MHz"


@dataclass
class ChannelInfo:
    """Aggregated info for a single channel."""

    channel: int
    frequency_mhz: int
    band: str
    network_count: int = 0
    strongest_signal_dbm: int = -100
    networks: List[str] = field(default_factory=list)  # SSIDs


@dataclass
class ScanResult:
    """Complete scan result."""

    networks: List[WifiNetwork] = field(default_factory=list)
    channels_2g: List[ChannelInfo] = field(default_factory=list)
    channels_5g: List[ChannelInfo] = field(default_factory=list)
    scan_interface: str = ""
    our_channel: int = 0
    our_band: str = ""


# Standard channel → frequency mappings
CHANNELS_2G = {1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437,
               7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472}
CHANNELS_5G = {36: 5180, 40: 5200, 44: 5220, 48: 5240, 52: 5260, 56: 5280,
               60: 5300, 64: 5320, 100: 5500, 104: 5520, 108: 5540, 112: 5560,
               116: 5580, 120: 5600, 124: 5620, 128: 5640, 132: 5660, 136: 5680,
               140: 5700, 144: 5720, 149: 5745, 153: 5765, 157: 5785, 161: 5805, 165: 5825}


def _freq_to_band(freq_mhz: int) -> str:
    return "2.4GHz" if freq_mhz < 3000 else "5GHz"


def _freq_to_channel(freq_mhz: int) -> int:
    all_channels = {**{v: k for k, v in CHANNELS_2G.items()}, **{v: k for k, v in CHANNELS_5G.items()}}
    return all_channels.get(freq_mhz, 0)


async def scan(interface: str = "") -> ScanResult:
    """Perform a WiFi environment scan."""
    iface = interface or settings.ap_interface or "wlan0"

    if settings.mock_mode:
        return _mock_scan(iface)

    result = ScanResult(scan_interface=iface)

    # Try iw scan first (preferred)
    scan_output = await _iw_scan(iface)
    if scan_output:
        result.networks = _parse_iw_scan(scan_output)
    else:
        # Fallback to iwlist
        scan_output = await _iwlist_scan(iface)
        if scan_output:
            result.networks = _parse_iwlist_scan(scan_output)

    # Get our current channel
    our_info = await _get_current_channel(iface)
    result.our_channel = our_info.get("channel", 0)
    result.our_band = our_info.get("band", "")

    # Aggregate channel info
    result.channels_2g = _aggregate_channels(result.networks, "2.4GHz", CHANNELS_2G)
    result.channels_5g = _aggregate_channels(result.networks, "5GHz", CHANNELS_5G)

    return result


async def _iw_scan(iface: str) -> str:
    """Run iw scan."""
    res = await run("iw", "dev", iface, "scan", sudo=True, check=False, timeout=30)
    return res.stdout if res.success else ""


async def _iwlist_scan(iface: str) -> str:
    """Fallback: iwlist scan."""
    res = await run("iwlist", iface, "scan", sudo=True, check=False, timeout=30)
    return res.stdout if res.success else ""


async def _get_current_channel(iface: str) -> dict:
    """Get the current channel of our AP interface."""
    res = await run("iw", "dev", iface, "info", check=False)
    if not res.success:
        return {}
    channel = 0
    freq = 0
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("channel"):
            m = re.search(r"channel\s+(\d+)", line)
            if m:
                channel = int(m.group(1))
        elif "freq" in line.lower():
            m = re.search(r"(\d{4,5})", line)
            if m:
                freq = int(m.group(1))
    band = _freq_to_band(freq) if freq else ""
    return {"channel": channel, "band": band}


def _parse_iw_scan(output: str) -> List[WifiNetwork]:
    """Parse 'iw dev <iface> scan' output."""
    networks = []
    current: Dict = {}

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("BSS "):
            if current.get("bssid"):
                networks.append(_build_network(current))
            bssid_match = re.match(r"BSS\s+([0-9a-f:]+)", line)
            current = {"bssid": bssid_match.group(1) if bssid_match else ""}

        elif line.startswith("SSID:"):
            current["ssid"] = line.split(":", 1)[1].strip()

        elif line.startswith("freq:"):
            current["freq"] = int(line.split(":")[1].strip())

        elif line.startswith("signal:"):
            m = re.search(r"(-?\d+\.?\d*)", line)
            if m:
                current["signal"] = int(float(m.group(1)))

        elif "WPA" in line or "RSN" in line:
            current["security"] = "WPA2" if "RSN" in line else "WPA"

        elif "channel width:" in line.lower():
            m = re.search(r"(\d+)\s*MHz", line)
            if m:
                current["width"] = f"{m.group(1)}MHz"

    if current.get("bssid"):
        networks.append(_build_network(current))

    return networks


def _parse_iwlist_scan(output: str) -> List[WifiNetwork]:
    """Parse 'iwlist <iface> scan' output."""
    networks = []
    current: Dict = {}

    for line in output.splitlines():
        line = line.strip()

        if "Cell " in line and "Address:" in line:
            if current.get("bssid"):
                networks.append(_build_network(current))
            m = re.search(r"Address:\s*([0-9A-Fa-f:]+)", line)
            current = {"bssid": m.group(1) if m else ""}

        elif "ESSID:" in line:
            m = re.search(r'ESSID:"(.+?)"', line)
            current["ssid"] = m.group(1) if m else ""

        elif "Frequency:" in line:
            m = re.search(r"Frequency:(\d+\.?\d*)\s*GHz", line)
            if m:
                current["freq"] = int(float(m.group(1)) * 1000)

        elif "Signal level" in line:
            m = re.search(r"Signal level[=:]?\s*(-?\d+)", line)
            if m:
                current["signal"] = int(m.group(1))

        elif "Encryption key:on" in line:
            current.setdefault("security", "WPA2")

    if current.get("bssid"):
        networks.append(_build_network(current))

    return networks


def _build_network(data: Dict) -> WifiNetwork:
    freq = data.get("freq", 0)
    return WifiNetwork(
        ssid=data.get("ssid", ""),
        bssid=data.get("bssid", ""),
        channel=_freq_to_channel(freq),
        frequency_mhz=freq,
        signal_dbm=data.get("signal", -100),
        security=data.get("security", "Open"),
        band=_freq_to_band(freq),
        width=data.get("width", ""),
    )


def _aggregate_channels(
    networks: List[WifiNetwork], band: str, channel_map: dict
) -> List[ChannelInfo]:
    """Build per-channel aggregation."""
    channels: Dict[int, ChannelInfo] = {}
    for ch, freq in channel_map.items():
        channels[ch] = ChannelInfo(channel=ch, frequency_mhz=freq, band=band)

    for net in networks:
        if net.band != band or net.channel not in channels:
            continue
        ci = channels[net.channel]
        ci.network_count += 1
        ci.networks.append(net.ssid or "(hidden)")
        if net.signal_dbm > ci.strongest_signal_dbm:
            ci.strongest_signal_dbm = net.signal_dbm

    return sorted(channels.values(), key=lambda c: c.channel)


def _mock_scan(iface: str) -> ScanResult:
    networks = [
        WifiNetwork("WiFry", "b8:27:eb:aa:bb:cc", 6, 2437, -25, "WPA2", "2.4GHz", "20MHz"),
        WifiNetwork("HomeNet-5G", "aa:bb:cc:11:22:33", 36, 5180, -45, "WPA2", "5GHz", "80MHz"),
        WifiNetwork("Neighbors_WiFi", "dd:ee:ff:44:55:66", 6, 2437, -62, "WPA2", "2.4GHz", "40MHz"),
        WifiNetwork("NETGEAR-2G", "11:22:33:aa:bb:cc", 1, 2412, -70, "WPA2", "2.4GHz", "20MHz"),
        WifiNetwork("xfinity", "22:33:44:bb:cc:dd", 11, 2462, -55, "WPA2", "2.4GHz", "40MHz"),
        WifiNetwork("ATT-5G-Home", "33:44:55:cc:dd:ee", 44, 5220, -68, "WPA3", "5GHz", "80MHz"),
        WifiNetwork("LinksysSetup", "44:55:66:dd:ee:ff", 3, 2422, -78, "Open", "2.4GHz", "20MHz"),
        WifiNetwork("OfficeNet", "55:66:77:ee:ff:00", 149, 5745, -52, "WPA2", "5GHz", "40MHz"),
        WifiNetwork("", "66:77:88:ff:00:11", 6, 2437, -80, "WPA2", "2.4GHz", "20MHz"),
        WifiNetwork("IoT_Network", "77:88:99:00:11:22", 1, 2412, -72, "WPA2", "2.4GHz", "20MHz"),
    ]

    result = ScanResult(
        networks=networks,
        scan_interface=iface,
        our_channel=6,
        our_band="2.4GHz",
    )
    result.channels_2g = _aggregate_channels(networks, "2.4GHz", CHANNELS_2G)
    result.channels_5g = _aggregate_channels(networks, "5GHz", CHANNELS_5G)
    return result
