"""WiFi-layer impairment service.

Controls WiFi-specific impairments that go beyond tc netem:
channel interference, TX power, band switching, deauth,
DHCP disruption, broadcast storms, rate limiting, periodic disconnects.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.wifi_impairment import (
    WifiImpairmentConfig,
    WifiImpairmentState,
)
from ..utils.shell import run, sudo_write

logger = logging.getLogger(__name__)

_state = WifiImpairmentState()
_disconnect_task: Optional[asyncio.Task] = None
_storm_task: Optional[asyncio.Task] = None
_band_bounce_task: Optional[asyncio.Task] = None
_channel_hop_task: Optional[asyncio.Task] = None


def _iface() -> str:
    return settings.ap_interface or "wlan0"


async def apply(config: WifiImpairmentConfig) -> WifiImpairmentState:
    """Apply WiFi impairment configuration."""
    # Clear existing impairments first
    await clear()

    active: List[str] = []

    if config.channel_interference.enabled:
        await _apply_channel_interference(config.channel_interference)
        active.append("channel_interference")

    if config.tx_power.enabled:
        await _apply_tx_power(config.tx_power)
        active.append("tx_power")

    if config.band_switch.enabled:
        await _apply_band_switch(config.band_switch)
        active.append("band_switch")

    if config.band_switch.bounce_enabled:
        _start_band_bounce(config.band_switch)
        active.append("band_bounce")

    if config.band_switch.channel_hop_enabled:
        _start_channel_hop(config.band_switch)
        active.append("channel_hop")

    if config.deauth.enabled:
        await _apply_deauth(config.deauth)
        active.append("deauth")

    if config.dhcp_disruption.enabled:
        await _apply_dhcp_disruption(config.dhcp_disruption)
        active.append("dhcp_disruption")

    if config.broadcast_storm.enabled:
        await _start_broadcast_storm(config.broadcast_storm)
        active.append("broadcast_storm")

    if config.rate_limit.enabled:
        await _apply_rate_limit(config.rate_limit)
        active.append("rate_limit")

    if config.periodic_disconnect.enabled:
        _start_periodic_disconnect(config.periodic_disconnect)
        active.append("periodic_disconnect")

    _state.config = config
    _state.active_impairments = active

    logger.info("WiFi impairments applied: %s", active)
    return _state


async def clear() -> WifiImpairmentState:
    """Remove all WiFi impairments and restore defaults."""
    global _disconnect_task, _storm_task, _band_bounce_task, _channel_hop_task

    iface = _iface()

    # Stop all background tasks
    for task_ref in [_disconnect_task, _storm_task, _band_bounce_task, _channel_hop_task]:
        if task_ref and not task_ref.done():
            task_ref.cancel()
            try:
                await task_ref
            except asyncio.CancelledError:
                pass

    _disconnect_task = None
    _storm_task = None
    _band_bounce_task = None
    _channel_hop_task = None

    if not settings.mock_mode:
        # Restore TX power
        await run("iw", "dev", iface, "set", "txpower", "auto", sudo=True, check=False)

        # Restore rate limits
        await run("iw", "dev", iface, "set", "bitrates", sudo=True, check=False)

        # Restore beacon interval (requires hostapd restart with default config)
        # We don't restart hostapd here to avoid disruption; it'll be restored on next config apply

    _state.config = WifiImpairmentConfig()
    _state.active_impairments = []
    _state.storm_active = False

    logger.info("WiFi impairments cleared")
    return _state


def get_state() -> WifiImpairmentState:
    return _state


# --- Individual impairment implementations ---

async def _apply_channel_interference(config) -> None:
    """Adjust beacon interval and RTS threshold to simulate congestion."""
    iface = _iface()

    if settings.mock_mode:
        logger.info("Mock: channel interference (beacon=%dms, rts=%d)", config.beacon_interval_ms, config.rts_threshold)
        return

    # RTS threshold: lower value forces RTS/CTS handshake for smaller frames,
    # increasing overhead and simulating a congested medium
    await run(
        "iw", "dev", iface, "set", "rts", str(config.rts_threshold),
        sudo=True, check=False,
    )

    # Beacon interval change requires hostapd config update + restart
    # We modify the running config via hostapd_cli
    await run(
        "hostapd_cli", "-i", iface,
        "set", "beacon_int", str(config.beacon_interval_ms),
        sudo=True, check=False,
    )

    logger.info("Channel interference: beacon=%dms, rts=%d", config.beacon_interval_ms, config.rts_threshold)


async def _apply_tx_power(config) -> None:
    """Reduce AP transmit power to simulate edge-of-coverage."""
    iface = _iface()

    if settings.mock_mode:
        logger.info("Mock: TX power set to %d dBm", config.power_dbm)
        return

    # iw uses mBm (milliBel-milliwatts), so multiply by 100
    mbm = config.power_dbm * 100
    await run(
        "iw", "dev", iface, "set", "txpower", "fixed", str(mbm),
        sudo=True, check=False,
    )

    logger.info("TX power set to %d dBm (%d mBm)", config.power_dbm, mbm)


async def _apply_band_switch(config) -> None:
    """Switch the AP to a different band/channel."""
    iface = _iface()

    if settings.mock_mode:
        logger.info("Mock: band switch to %s ch %d", config.target_band, config.target_channel)
        return

    channel = config.target_channel
    if channel == 0:
        channel = 6 if config.target_band == "2.4GHz" else 36

    # Channel switch via hostapd_cli (performs CSA - Channel Switch Announcement)
    await run(
        "hostapd_cli", "-i", iface,
        "chan_switch", "5", str(channel),  # 5 beacon count before switch
        sudo=True, check=False,
    )

    logger.info("Band switch: %s channel %d", config.target_band, channel)


async def _apply_deauth(config) -> None:
    """Send deauthentication frame to a client (or all)."""
    iface = _iface()

    if settings.mock_mode:
        logger.info("Mock: deauth mac=%s reason=%d", config.target_mac or "all", config.reason_code)
        return

    if config.target_mac:
        await run(
            "hostapd_cli", "-i", iface,
            "deauthenticate", config.target_mac,
            "reason=" + str(config.reason_code),
            sudo=True, check=False,
        )
    else:
        # Deauth all clients by disabling/enabling the interface briefly
        result = await run("hostapd_cli", "-i", iface, "all_sta", sudo=True, check=False)
        if result.success:
            import re
            macs = re.findall(r"([0-9a-fA-F:]{17})", result.stdout)
            for mac in macs:
                await run(
                    "hostapd_cli", "-i", iface,
                    "deauthenticate", mac,
                    "reason=" + str(config.reason_code),
                    sudo=True, check=False,
                )

    _state.disconnect_count += 1
    logger.info("Deauth sent: mac=%s reason=%d", config.target_mac or "all", config.reason_code)


async def _apply_dhcp_disruption(config) -> None:
    """Modify dnsmasq behavior to disrupt DHCP.

    Uses safe file writes instead of shell interpolation to prevent injection.
    """
    if settings.mock_mode:
        logger.info("Mock: DHCP disruption mode=%s", config.mode)
        return

    conf_path = Path("/etc/dnsmasq.d/wifry-impairment.conf")

    if config.mode == "delay":
        # Validate delay is an integer (defense in depth — Pydantic already validates)
        delay = int(config.delay_secs)
        await sudo_write(str(conf_path), f"dhcp-reply-delay={delay}\n")
        await run("systemctl", "restart", "dnsmasq", sudo=True, check=False)

    elif config.mode == "fail":
        await run(
            "iptables", "-A", "OUTPUT",
            "-p", "udp", "--sport", "67",
            "-j", "DROP",
            "-m", "comment", "--comment", "wifry-dhcp-fail",
            sudo=True, check=False,
        )

    elif config.mode == "change_ip":
        await sudo_write(str(conf_path), "dhcp-range=192.168.4.201,192.168.4.250,255.255.255.0,30s\n")
        await run("systemctl", "restart", "dnsmasq", sudo=True, check=False)

    logger.info("DHCP disruption: mode=%s", config.mode)


async def _start_broadcast_storm(config) -> None:
    """Start injecting broadcast packets to consume airtime."""
    global _storm_task

    _state.storm_active = True

    if settings.mock_mode:
        logger.info("Mock: broadcast storm %d pps, %d bytes", config.packets_per_sec, config.packet_size_bytes)
        return

    _storm_task = asyncio.create_task(_broadcast_storm_loop(config))


async def _broadcast_storm_loop(config) -> None:
    """Background task that sends broadcast packets."""
    iface = _iface()
    interval = 1.0 / config.packets_per_sec
    payload_size = config.packet_size_bytes

    try:
        while _state.storm_active:
            # Use hping3 or nping for broadcast injection
            await run(
                "hping3", "--udp",
                "-p", "9999",
                "--destport", "9999",
                "-d", str(payload_size),
                "--flood",
                "--count", str(min(config.packets_per_sec, 100)),
                "-I", iface,
                "255.255.255.255",
                sudo=True, check=False, timeout=5,
            )
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        _state.storm_active = False


async def _apply_rate_limit(config) -> None:
    """Force lower WiFi PHY rates."""
    iface = _iface()

    if settings.mock_mode:
        logger.info("Mock: rate limit legacy=%s ht_mcs=%d vht_mcs=%d",
                     config.legacy_rate_mbps, config.ht_mcs, config.vht_mcs)
        return

    cmd = ["iw", "dev", iface, "set", "bitrates"]

    # Legacy rates
    if config.legacy_rate_mbps < 54:
        # Build list of allowed legacy rates up to the limit
        all_legacy = [1, 2, 5.5, 6, 9, 11, 12, 18, 24, 36, 48, 54]
        allowed = [str(r) for r in all_legacy if r <= config.legacy_rate_mbps]
        if allowed:
            cmd.extend(["legacy-2.4", *allowed])

    # HT (802.11n) MCS limit
    if config.ht_mcs >= 0:
        mcs_list = [str(m) for m in range(config.ht_mcs + 1)]
        cmd.extend(["ht-mcs-2.4", *mcs_list])

    # VHT (802.11ac) MCS limit
    if config.vht_mcs >= 0:
        mcs_list = [str(m) for m in range(config.vht_mcs + 1)]
        cmd.extend(["vht-mcs-5", *mcs_list])

    await run(*cmd, sudo=True, check=False)
    logger.info("Rate limit applied: legacy<=%.1f, ht_mcs<=%d, vht_mcs<=%d",
                config.legacy_rate_mbps, config.ht_mcs, config.vht_mcs)


def _start_periodic_disconnect(config) -> None:
    """Start the periodic disconnect loop."""
    global _disconnect_task
    _disconnect_task = asyncio.create_task(_periodic_disconnect_loop(config))


async def _periodic_disconnect_loop(config) -> None:
    """Background task that periodically disconnects clients."""
    from ..models.wifi_impairment import DeauthConfig

    try:
        while True:
            await asyncio.sleep(config.interval_secs)

            logger.warning("Periodic disconnect triggered (interval=%ds, duration=%ds)",
                           config.interval_secs, config.disconnect_duration_secs)

            # Deauth
            deauth_cfg = DeauthConfig(
                enabled=True,
                target_mac=config.target_mac,
                reason_code=3,
            )
            await _apply_deauth(deauth_cfg)

            # Wait for disconnect duration
            await asyncio.sleep(config.disconnect_duration_secs)

            # Clients will automatically reassociate after the disconnect duration
            logger.info("Periodic disconnect complete, clients can reassociate")

    except asyncio.CancelledError:
        pass


# --- Band bounce (2.4GHz <-> 5GHz cycling) ---

def _start_band_bounce(config) -> None:
    """Start periodic band bouncing between 2.4GHz and 5GHz."""
    global _band_bounce_task
    _band_bounce_task = asyncio.create_task(_band_bounce_loop(config))


async def _band_bounce_loop(config) -> None:
    """Background task that cycles between two bands/channels."""
    iface = _iface()
    on_a = True

    try:
        while True:
            if on_a:
                band, channel = config.bounce_band_a, config.bounce_channel_a
            else:
                band, channel = config.bounce_band_b, config.bounce_channel_b

            channel = channel or (6 if band == "2.4GHz" else 36)

            logger.warning("Band bounce: switching to %s ch %d", band, channel)

            if not settings.mock_mode:
                # Channel Switch Announcement (CSA) — gives clients 5 beacons to prepare
                await run(
                    "hostapd_cli", "-i", iface,
                    "chan_switch", "5", str(channel),
                    sudo=True, check=False,
                )

            on_a = not on_a
            await asyncio.sleep(config.bounce_interval_secs)

    except asyncio.CancelledError:
        pass


# --- Channel hopping (within same band) ---

def _start_channel_hop(config) -> None:
    """Start periodic channel hopping within the current band."""
    global _channel_hop_task
    _channel_hop_task = asyncio.create_task(_channel_hop_loop(config))


async def _channel_hop_loop(config) -> None:
    """Background task that cycles through a list of channels."""
    iface = _iface()

    channels = [int(c.strip()) for c in config.channel_hop_list.split(",") if c.strip().isdigit()]
    if not channels:
        channels = [1, 6, 11]  # Default 2.4GHz non-overlapping

    idx = 0

    try:
        while True:
            channel = channels[idx % len(channels)]

            logger.warning("Channel hop: switching to ch %d", channel)

            if not settings.mock_mode:
                await run(
                    "hostapd_cli", "-i", iface,
                    "chan_switch", "3", str(channel),
                    sudo=True, check=False,
                )

            idx += 1
            await asyncio.sleep(config.channel_hop_interval_secs)

    except asyncio.CancelledError:
        pass


# --- Cleanup helpers ---

async def _cleanup_dhcp_disruption() -> None:
    """Remove DHCP disruption rules."""
    if settings.mock_mode:
        return

    # Remove impairment config (restart, not reload — dnsmasq needs full restart for config changes)
    await run("rm", "-f", "/etc/dnsmasq.d/wifry-impairment.conf", sudo=True, check=False)
    await run("systemctl", "restart", "dnsmasq", sudo=True, check=False)

    # Remove iptables DHCP block if present
    await run(
        "iptables", "-D", "OUTPUT",
        "-p", "udp", "--sport", "67",
        "-j", "DROP",
        "-m", "comment", "--comment", "wifry-dhcp-fail",
        sudo=True, check=False,
    )
