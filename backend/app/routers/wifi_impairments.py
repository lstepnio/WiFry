"""WiFi-layer impairments router."""

from fastapi import APIRouter

from ..models.wifi_impairment import (
    BandSwitchConfig,
    BroadcastStormConfig,
    ChannelInterferenceConfig,
    DeauthConfig,
    DhcpDisruptionConfig,
    PeriodicDisconnectConfig,
    RateLimitConfig,
    TxPowerConfig,
    WifiImpairmentConfig,
    WifiImpairmentState,
)
from ..services import wifi_impairment
from ..services import hw_capabilities

router = APIRouter(prefix="/api/v1/wifi-impairments", tags=["wifi-impairments"])


@router.get("", response_model=WifiImpairmentState)
async def get_state():
    """Get current WiFi impairment state."""
    return wifi_impairment.get_state()


@router.get("/capabilities")
async def get_capabilities():
    """Get WiFi hardware capabilities for feature gating."""
    caps = await hw_capabilities.detect_capabilities()
    return caps.to_dict()


@router.put("", response_model=WifiImpairmentState)
async def apply_all(config: WifiImpairmentConfig):
    """Apply full WiFi impairment config (replaces all). Auto-links to active session."""
    result = await wifi_impairment.apply(config)

    # Log to active session
    from ..services import session_manager
    sid = session_manager.get_active_session_id()
    if sid:
        active = result.active_impairments
        session_manager.log_impairment(
            sid,
            wifi_config=config.model_dump(exclude_none=True),
            label=f"WiFi impairments: {', '.join(active)}" if active else "WiFi impairments cleared",
        )
        if active:
            await session_manager.add_artifact(
                sid,
                session_manager.ArtifactType.IMPAIRMENT_LOG,
                name=f"WiFi impairments: {', '.join(active)}",
                data=config.model_dump(exclude_none=True),
                tags=["impairment", "wifi"],
            )

    return result


@router.delete("", response_model=WifiImpairmentState)
async def clear_all():
    """Clear all WiFi impairments."""
    return await wifi_impairment.clear()


# --- Individual impairment shortcuts ---

@router.put("/channel-interference", response_model=WifiImpairmentState)
async def set_channel_interference(config: ChannelInterferenceConfig):
    """Set channel interference simulation."""
    state = wifi_impairment.get_state()
    state.config.channel_interference = config
    return await wifi_impairment.apply(state.config)


@router.put("/tx-power", response_model=WifiImpairmentState)
async def set_tx_power(config: TxPowerConfig):
    """Set TX power reduction."""
    state = wifi_impairment.get_state()
    state.config.tx_power = config
    return await wifi_impairment.apply(state.config)


@router.put("/band-switch", response_model=WifiImpairmentState)
async def set_band_switch(config: BandSwitchConfig):
    """Trigger band/channel switch."""
    state = wifi_impairment.get_state()
    state.config.band_switch = config
    return await wifi_impairment.apply(state.config)


@router.put("/deauth", response_model=WifiImpairmentState)
async def set_deauth(config: DeauthConfig):
    """Send deauth to clients."""
    state = wifi_impairment.get_state()
    state.config.deauth = config
    return await wifi_impairment.apply(state.config)


@router.put("/dhcp-disruption", response_model=WifiImpairmentState)
async def set_dhcp_disruption(config: DhcpDisruptionConfig):
    """Set DHCP disruption mode."""
    state = wifi_impairment.get_state()
    state.config.dhcp_disruption = config
    return await wifi_impairment.apply(state.config)


@router.put("/broadcast-storm", response_model=WifiImpairmentState)
async def set_broadcast_storm(config: BroadcastStormConfig):
    """Start/stop broadcast storm."""
    state = wifi_impairment.get_state()
    state.config.broadcast_storm = config
    return await wifi_impairment.apply(state.config)


@router.put("/rate-limit", response_model=WifiImpairmentState)
async def set_rate_limit(config: RateLimitConfig):
    """Set WiFi rate limiting."""
    state = wifi_impairment.get_state()
    state.config.rate_limit = config
    return await wifi_impairment.apply(state.config)


@router.put("/periodic-disconnect", response_model=WifiImpairmentState)
async def set_periodic_disconnect(config: PeriodicDisconnectConfig):
    """Set periodic disconnect schedule."""
    state = wifi_impairment.get_state()
    state.config.periodic_disconnect = config
    return await wifi_impairment.apply(state.config)
