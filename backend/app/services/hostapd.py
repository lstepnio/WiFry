"""hostapd and dnsmasq configuration generation and control."""

import logging
from pathlib import Path
from string import Template

from ..config import settings
from ..utils.shell import run, sudo_write

logger = logging.getLogger(__name__)

HOSTAPD_CONF = Path("/etc/hostapd/hostapd.conf")
DNSMASQ_CONF = Path("/etc/dnsmasq.d/wifry.conf")
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "setup"

# Default network settings for the AP
AP_IP = "192.168.4.1"
AP_NETMASK = "255.255.255.0"
DHCP_RANGE_START = "192.168.4.10"
DHCP_RANGE_END = "192.168.4.200"


def generate_hostapd_conf(
    interface: str = "",
    ssid: str = "",
    password: str = "",
    channel: int = 0,
    band: str = "",
    country_code: str = "US",
) -> str:
    """Generate hostapd.conf content from the template."""
    iface = interface or settings.ap_interface or "wlan0"
    ssid = ssid or settings.ap_ssid
    password = password or settings.ap_password
    channel = channel or settings.ap_channel
    band = band or settings.ap_band

    # Determine hw_mode and 802.11 capabilities based on band
    if band == "5GHz":
        hw_mode = "a"
        ieee80211n = "ieee80211n=1"
        ieee80211ac = "ieee80211ac=1"
        ieee80211ax = "ieee80211ax=1"
        # Force a valid 5GHz channel (2.4GHz channels 1-14 are invalid for hw_mode=a)
        if channel < 32:
            channel = 36
    else:
        hw_mode = "g"
        ieee80211n = "ieee80211n=1"
        ieee80211ac = ""
        ieee80211ax = "ieee80211ax=1"
        # Force a valid 2.4GHz channel (5GHz channels are invalid for hw_mode=g)
        if channel == 0 or channel > 14:
            channel = 6

    template_path = TEMPLATE_DIR / "hostapd.conf.template"
    template = Template(template_path.read_text())

    return template.substitute(
        AP_INTERFACE=iface,
        AP_SSID=ssid,
        AP_PASSWORD=password,
        AP_CHANNEL=str(channel),
        HW_MODE=hw_mode,
        IEEE80211N_LINE=ieee80211n,
        IEEE80211AC_LINE=ieee80211ac,
        IEEE80211AX_LINE=ieee80211ax,
        COUNTRY_CODE=country_code,
    )


def generate_dnsmasq_conf(
    interface: str = "",
    dns_server: str = "8.8.8.8",
) -> str:
    """Generate dnsmasq.conf content from the template."""
    iface = interface or settings.ap_interface or "wlan0"

    template_path = TEMPLATE_DIR / "dnsmasq.conf.template"
    template = Template(template_path.read_text())

    return template.substitute(
        AP_INTERFACE=iface,
        AP_IP=AP_IP,
        DHCP_RANGE_START=DHCP_RANGE_START,
        DHCP_RANGE_END=DHCP_RANGE_END,
        DNS_SERVER=dns_server,
    )


async def write_and_restart_hostapd(**kwargs: str | int) -> None:
    """Write hostapd config and restart the service.

    If the new config fails (e.g., 5GHz not supported), automatically
    rolls back to 2.4GHz safe defaults so the AP stays reachable.
    """
    if settings.mock_mode:
        logger.info("Mock: would write hostapd.conf and restart")
        return

    # Save current config for rollback
    backup = HOSTAPD_CONF.read_text() if HOSTAPD_CONF.exists() else None

    conf = generate_hostapd_conf(**kwargs)
    await run("mkdir", "-p", str(HOSTAPD_CONF.parent), sudo=True, check=False)
    await sudo_write(str(HOSTAPD_CONF), conf)
    logger.info("Wrote %s", HOSTAPD_CONF)

    # Set regulatory domain before restart (5GHz needs this applied first)
    country = kwargs.get("country_code", "US")
    await run("rfkill", "unblock", "wlan", sudo=True, check=False)
    await run("iw", "reg", "set", country, sudo=True, check=False)

    # systemd override also runs rfkill+iw+sleep, but seed it here too
    import asyncio
    await asyncio.sleep(1)

    result = await run("systemctl", "restart", "hostapd", sudo=True, check=False, timeout=15)
    if result.success:
        logger.info("Restarted hostapd")
    else:
        logger.error("hostapd failed to start: %s", result.stderr)
        # Rollback to previous working config
        if backup:
            logger.warning("Rolling back hostapd config to previous working state")
            await sudo_write(str(HOSTAPD_CONF), backup)
            await run("systemctl", "restart", "hostapd", sudo=True, check=False)
        raise RuntimeError(
            f"hostapd failed to start with new config: {result.stderr}. "
            "Rolled back to previous working config."
        )


async def write_and_restart_dnsmasq(**kwargs: str) -> None:
    """Write dnsmasq config and restart the service."""
    if settings.mock_mode:
        logger.info("Mock: would write dnsmasq.conf and restart")
        return

    conf = generate_dnsmasq_conf(**kwargs)
    await run("mkdir", "-p", str(DNSMASQ_CONF.parent), sudo=True, check=False)
    await sudo_write(str(DNSMASQ_CONF), conf)
    logger.info("Wrote %s", DNSMASQ_CONF)

    await run("systemctl", "restart", "dnsmasq", sudo=True, check=True)
    logger.info("Restarted dnsmasq")


async def setup_ap_networking(interface: str = "") -> None:
    """Configure static IP and NAT for the AP interface.

    Sets up:
    1. Static IP on the AP interface
    2. IP forwarding
    3. iptables NAT masquerade from AP to upstream
    """
    iface = interface or settings.ap_interface or "wlan0"
    upstream = settings.upstream_interface or "eth0"

    if settings.mock_mode:
        logger.info("Mock: would configure AP networking on %s -> %s", iface, upstream)
        return

    # Assign static IP to AP interface
    await run("ip", "addr", "flush", "dev", iface, sudo=True, check=False)
    await run(
        "ip", "addr", "add", f"{AP_IP}/{AP_NETMASK}", "dev", iface,
        sudo=True, check=True,
    )
    await run("ip", "link", "set", iface, "up", sudo=True, check=True)

    # Enable IP forwarding
    await run(
        "sysctl", "-w", "net.ipv4.ip_forward=1",
        sudo=True, check=True,
    )

    # NAT masquerade (non-fatal — iptables may not be installed on first boot)
    nat_result = await run(
        "iptables", "-t", "nat", "-A", "POSTROUTING",
        "-o", upstream, "-j", "MASQUERADE",
        sudo=True, check=False,
    )
    if not nat_result.success:
        logger.warning("iptables NAT failed (iptables may not be installed): %s", nat_result.stderr)
    else:
        await run(
            "iptables", "-A", "FORWARD",
            "-i", iface, "-o", upstream,
            "-m", "state", "--state", "RELATED,ESTABLISHED",
            "-j", "ACCEPT",
            sudo=True, check=False,
        )
        await run(
            "iptables", "-A", "FORWARD",
            "-i", upstream, "-o", iface,
            "-j", "ACCEPT",
            sudo=True, check=False,
        )

    logger.info("AP networking configured: %s (%s) -> %s", iface, AP_IP, upstream)


async def get_hostapd_status() -> dict:
    """Check if hostapd is running and get its status."""
    if settings.mock_mode:
        return {"active": True, "status": "active (mock)"}

    result = await run("systemctl", "is-active", "hostapd", check=False)
    active = result.stdout.strip() == "active"

    return {"active": active, "status": result.stdout.strip()}
