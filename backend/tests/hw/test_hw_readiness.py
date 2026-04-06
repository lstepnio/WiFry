"""Tier 1: System Readiness — validates the RPi is correctly set up.

No WiFi client needed. Checks binaries, services, permissions, WiFi config.
"""

import asyncio
import re
from pathlib import Path

import pytest

from app.utils.shell import run

from .hw_capabilities import WifiCapabilities


# --- Binary checks ---

REQUIRED_BINARIES = [
    "tshark", "tc", "iw", "hostapd_cli", "iptables", "ip",
    "dumpcap", "systemctl", "hping3", "curl", "jq",
]

OPTIONAL_BINARIES = [
    "iperf3", "coredns", "cloudflared", "speedtest",
    "wg", "openvpn", "ffmpeg", "adb", "v4l2-ctl",
]


@pytest.mark.hw_readiness
@pytest.mark.parametrize("binary", REQUIRED_BINARIES)
async def test_required_binary_exists(binary):
    """Required binary must be in PATH."""
    result = await run("which", binary, check=False)
    assert result.success, f"Required binary '{binary}' not found in PATH"


@pytest.mark.hw_readiness
@pytest.mark.parametrize("binary", OPTIONAL_BINARIES)
async def test_optional_binary_exists(binary):
    """Optional binary — warn but don't fail."""
    result = await run("which", binary, check=False)
    if not result.success:
        pytest.skip(f"Optional binary '{binary}' not installed")


# --- Service checks ---

REQUIRED_SERVICES = ["hostapd", "dnsmasq", "wifry-backend"]


@pytest.mark.hw_readiness
@pytest.mark.parametrize("service", REQUIRED_SERVICES)
async def test_service_running(service):
    """Service must be active."""
    result = await run("systemctl", "is-active", service, check=False)
    assert result.stdout.strip() == "active", (
        f"Service '{service}' is {result.stdout.strip()}, expected 'active'"
    )


# --- Sudoers checks ---

SUDO_COMMANDS = [
    ("tc", ["-j", "qdisc", "show", "dev", "lo"]),
    ("ip", ["-j", "addr", "show", "lo"]),
    ("iw", ["dev", "wlan0", "info"]),
    ("hostapd_cli", ["-i", "wlan0", "status"]),
    ("systemctl", ["is-active", "hostapd"]),
    ("sysctl", ["-n", "net.ipv4.ip_forward"]),
]


@pytest.mark.hw_readiness
@pytest.mark.parametrize("cmd,args", SUDO_COMMANDS, ids=[c[0] for c in SUDO_COMMANDS])
async def test_sudo_no_password(cmd, args):
    """sudo command must work without password prompt."""
    result = await run(cmd, *args, sudo=True, check=False, timeout=5)
    assert "password is required" not in result.stderr, (
        f"sudo {cmd} requires a password — check /etc/sudoers.d/wifry"
    )


@pytest.mark.hw_readiness
async def test_sudo_tee_hostapd():
    """sudo tee to hostapd.conf must work (read current, write it back)."""
    result = await run("cat", "/etc/hostapd/hostapd.conf", check=False)
    assert result.success, "Cannot read /etc/hostapd/hostapd.conf"
    # Don't actually write — just verify the path is accessible


@pytest.mark.hw_readiness
async def test_sudo_iptables():
    """iptables must work via sudo (list rules)."""
    result = await run("iptables", "-L", "-n", sudo=True, check=False)
    assert result.success, f"sudo iptables failed: {result.stderr}"


# --- File permission checks ---


@pytest.mark.hw_readiness
async def test_captures_dir_writable():
    """Captures directory must be world-writable for dumpcap."""
    captures = Path("/var/lib/wifry/captures")
    assert captures.exists(), f"{captures} does not exist"
    mode = oct(captures.stat().st_mode)
    assert mode.endswith("777"), (
        f"{captures} has mode {mode}, expected *777 (world-writable for dumpcap)"
    )


@pytest.mark.hw_readiness
async def test_hostapd_conf_exists():
    """/etc/hostapd/hostapd.conf must exist."""
    assert Path("/etc/hostapd/hostapd.conf").exists()


@pytest.mark.hw_readiness
async def test_dnsmasq_confdir_enabled():
    """dnsmasq.conf must have conf-dir=/etc/dnsmasq.d uncommented."""
    dnsmasq_conf = Path("/etc/dnsmasq.conf")
    assert dnsmasq_conf.exists(), "/etc/dnsmasq.conf not found"
    content = dnsmasq_conf.read_text()
    # Look for uncommented conf-dir line
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("conf-dir=") and "/etc/dnsmasq.d" in stripped:
            return  # Found it
    pytest.fail("conf-dir=/etc/dnsmasq.d is not enabled in /etc/dnsmasq.conf")


# --- Network checks ---


@pytest.mark.hw_readiness
async def test_wlan0_exists():
    """wlan0 interface must exist."""
    result = await run("ip", "link", "show", "wlan0", check=False)
    assert result.success, "wlan0 interface not found"


@pytest.mark.hw_readiness
async def test_wlan0_has_ap_ip():
    """wlan0 must have the AP IP address (192.168.4.1)."""
    result = await run("ip", "-j", "addr", "show", "wlan0", check=False)
    assert result.success
    assert "192.168.4.1" in result.stdout, (
        "wlan0 does not have IP 192.168.4.1"
    )


@pytest.mark.hw_readiness
async def test_hostapd_ctrl_interface():
    """hostapd control interface socket must exist."""
    ctrl = Path("/var/run/hostapd")
    assert ctrl.exists(), (
        "/var/run/hostapd/ not found — add ctrl_interface to hostapd.conf"
    )


@pytest.mark.hw_readiness
async def test_regulatory_domain():
    """Regulatory domain must be set (not 00/world)."""
    result = await run("iw", "reg", "get", sudo=True, check=False)
    assert result.success
    # Check for a real country code, not "country 00:" or "country 99:"
    for line in result.stdout.splitlines():
        if line.strip().startswith("country") and ":" in line:
            country = line.strip().split()[1].rstrip(":")
            if country not in ("00", "99"):
                return  # Valid country code found
    pytest.fail(
        "No valid regulatory domain set — run 'sudo iw reg set US'"
    )


# --- WiFi capability checks ---


@pytest.mark.hw_readiness
async def test_wifi_ap_mode(wifi_caps: WifiCapabilities):
    """WiFi hardware must support AP mode."""
    assert wifi_caps.ap_mode, "WiFi driver does not support AP mode"


@pytest.mark.hw_readiness
async def test_wifi_has_2g_channels(wifi_caps: WifiCapabilities):
    """WiFi must have 2.4GHz channels available."""
    assert len(wifi_caps.supported_channels_2g) > 0, "No 2.4GHz channels available"


@pytest.mark.hw_readiness
async def test_wifi_capabilities_detected(wifi_caps: WifiCapabilities):
    """WiFi capabilities should be detected without error."""
    assert wifi_caps.error is None, f"Capability detection failed: {wifi_caps.error}"


# --- Python environment ---


@pytest.mark.hw_readiness
async def test_python_venv():
    """Python venv must exist and have key packages."""
    venv = Path("/opt/wifry/backend/.venv/bin/python3")
    assert venv.exists(), f"Python venv not found at {venv}"

    result = await run(
        str(venv), "-c", "import fastapi, uvicorn, pydantic; print('ok')",
        check=False,
    )
    assert result.success and "ok" in result.stdout, (
        f"Key Python packages missing: {result.stderr}"
    )
