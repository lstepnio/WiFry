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
    """Get WiFi AP status."""
    from ..config import settings

    clients = await list_wifi_clients()
    return {
        "ssid": settings.ap_ssid,
        "channel": settings.ap_channel,
        "band": settings.ap_band,
        "interface": settings.ap_interface or "wlan0",
        "client_count": len(clients),
        "active": True,  # TODO: check hostapd status
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
