"""Network interface discovery and status."""

import json
import logging
import re
from dataclasses import dataclass

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)


@dataclass
class InterfaceInfo:
    name: str
    mac: str
    ipv4: str
    state: str  # "UP" or "DOWN"
    type: str  # "ethernet", "wireless", "bridge", "loopback"
    speed: str  # e.g. "1000Mb/s" or ""


@dataclass
class WifiClient:
    mac: str
    ip: str
    hostname: str
    signal_dbm: int
    connected_time: str


async def list_interfaces() -> list[InterfaceInfo]:
    """List all network interfaces with their status."""
    if settings.mock_mode:
        return _mock_interfaces()

    result = await run("ip", "-j", "addr", "show", check=False)
    if not result.success:
        return []

    try:
        ifaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    interfaces = []
    for iface in ifaces:
        name = iface.get("ifname", "")
        if name == "lo":
            continue

        state = "UP" if "UP" in iface.get("flags", []) else "DOWN"
        mac = iface.get("address", "")

        ipv4 = ""
        for addr_info in iface.get("addr_info", []):
            if addr_info.get("family") == "inet":
                ipv4 = addr_info.get("local", "")
                break

        iface_type = _detect_type(name)

        interfaces.append(InterfaceInfo(
            name=name,
            mac=mac,
            ipv4=ipv4,
            state=state,
            type=iface_type,
            speed="",
        ))

    return interfaces


def _detect_type(name: str) -> str:
    """Detect interface type from name."""
    if name.startswith("wl"):
        return "wireless"
    if name.startswith("br"):
        return "bridge"
    if name.startswith("eth") or name.startswith("en"):
        return "ethernet"
    return "unknown"


async def get_managed_interfaces() -> list[str]:
    """Get the list of interfaces WiFry manages for impairment."""
    if settings.ap_interface:
        managed = [settings.ap_interface]
    else:
        ifaces = await list_interfaces()
        managed = [i.name for i in ifaces if i.type == "wireless"]

    managed.extend(settings.bridge_interfaces)
    return managed


async def list_wifi_clients() -> list[WifiClient]:
    """List devices connected to the WiFi AP."""
    if settings.mock_mode:
        return _mock_wifi_clients()

    # Parse hostapd connected stations
    iface = settings.ap_interface or "wlan0"
    result = await run("hostapd_cli", "-i", iface, "all_sta", sudo=True, check=False)
    if not result.success:
        return []

    clients: list[WifiClient] = []
    current_mac = ""

    for line in result.stdout.splitlines():
        mac_match = re.match(r"^([0-9a-fA-F:]{17})$", line.strip())
        if mac_match:
            current_mac = mac_match.group(1)
            continue

        if "=" in line and current_mac:
            key, _, val = line.partition("=")
            if key.strip() == "signal":
                # Look up IP from ARP
                ip = await _mac_to_ip(current_mac)
                hostname = await _ip_to_hostname(ip) if ip else ""
                clients.append(WifiClient(
                    mac=current_mac,
                    ip=ip,
                    hostname=hostname,
                    signal_dbm=int(val.strip()) if val.strip().lstrip("-").isdigit() else 0,
                    connected_time="",
                ))
                current_mac = ""

    return clients


async def _mac_to_ip(mac: str) -> str:
    """Look up IP address from MAC via ARP table."""
    result = await run("ip", "-j", "neigh", "show", check=False)
    if not result.success:
        return ""
    try:
        entries = json.loads(result.stdout)
        for entry in entries:
            if entry.get("lladdr", "").lower() == mac.lower():
                return entry.get("dst", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


async def _ip_to_hostname(ip: str) -> str:
    """Reverse DNS lookup for a client IP."""
    result = await run("getent", "hosts", ip, check=False)
    if result.success and result.stdout:
        parts = result.stdout.split()
        return parts[1] if len(parts) > 1 else ""
    return ""


def _mock_interfaces() -> list[InterfaceInfo]:
    return [
        InterfaceInfo("wlan0", "b8:27:eb:aa:bb:cc", "192.168.4.1", "UP", "wireless", ""),
        InterfaceInfo("eth0", "b8:27:eb:dd:ee:ff", "192.168.1.100", "UP", "ethernet", "1000Mb/s"),
    ]


def _mock_wifi_clients() -> list[WifiClient]:
    return [
        WifiClient("aa:bb:cc:dd:ee:01", "192.168.4.10", "stb-living-room", -45, "01:23:45"),
        WifiClient("aa:bb:cc:dd:ee:02", "192.168.4.11", "stb-bedroom", -62, "00:45:12"),
    ]
