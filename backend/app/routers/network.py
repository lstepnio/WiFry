"""Network router — interface listing, AP status, mode switching."""

from dataclasses import asdict

from fastapi import APIRouter

from ..services.network import list_interfaces, list_wifi_clients

router = APIRouter(prefix="/api/v1/network", tags=["network"])


@router.get("/interfaces")
async def get_interfaces():
    """List all network interfaces with status."""
    interfaces = await list_interfaces()
    return [asdict(i) for i in interfaces]


@router.get("/clients")
async def get_clients():
    """List connected WiFi clients."""
    clients = await list_wifi_clients()
    return [asdict(c) for c in clients]


@router.get("/ap/status")
async def get_ap_status():
    """Get WiFi AP status from live hostapd/iw state."""
    import re
    from ..config import settings
    from ..utils.shell import run

    iface = settings.ap_interface or "wlan0"
    clients = await list_wifi_clients()

    # Read live state from iw
    ssid = settings.ap_ssid
    channel = settings.ap_channel
    band = settings.ap_band
    active = False

    if not settings.mock_mode:
        result = await run("iw", "dev", iface, "info", sudo=True, check=False)
        if result.success:
            # Parse SSID
            ssid_match = re.search(r"ssid (.+)", result.stdout)
            if ssid_match:
                ssid = ssid_match.group(1).strip()

            # Parse channel and frequency
            chan_match = re.search(r"channel (\d+) \((\d+) MHz\)", result.stdout)
            if chan_match:
                channel = int(chan_match.group(1))
                freq = int(chan_match.group(2))
                band = "5GHz" if freq >= 5000 else "2.4GHz"

            active = "type AP" in result.stdout

        # Also check systemd
        status = await run("systemctl", "is-active", "hostapd", check=False)
        if status.stdout.strip() != "active":
            active = False

    return {
        "ssid": ssid,
        "channel": channel,
        "band": band,
        "interface": iface,
        "client_count": len(clients),
        "active": active,
    }


@router.get("/mode")
async def get_mode():
    """Get current network mode."""
    from ..config import settings

    has_ap = bool(settings.ap_interface)
    has_bridge = bool(settings.bridge_interfaces)

    if has_ap and has_bridge:
        mode = "ap+bridge"
    elif has_bridge:
        mode = "bridge"
    else:
        mode = "ap"

    return {"mode": mode}
