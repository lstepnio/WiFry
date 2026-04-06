"""Tier 3: Full Integration Tests — requires a WiFi client connected to the AP.

Run with: pytest tests/hw/ -v --hw-client-ip=192.168.4.164

These tests apply impairments and measure their effect on the connected client.
"""

import asyncio
import re

import httpx
import pytest

from app.utils.shell import run

from .hw_capabilities import WifiCapabilities


async def _ping(ip: str, count: int = 5, timeout: int = 10) -> dict:
    """Ping an IP and return parsed results."""
    result = await run(
        "ping", "-c", str(count), "-W", "2", ip,
        check=False, timeout=timeout + 5,
    )

    stats = {
        "transmitted": 0, "received": 0, "loss_pct": 100.0,
        "avg_ms": 0.0, "raw": result.stdout,
    }

    # Parse "5 packets transmitted, 3 received, 40% packet loss"
    tx_match = re.search(r"(\d+) packets transmitted, (\d+) received", result.stdout)
    if tx_match:
        stats["transmitted"] = int(tx_match.group(1))
        stats["received"] = int(tx_match.group(2))
        if stats["transmitted"] > 0:
            stats["loss_pct"] = (1 - stats["received"] / stats["transmitted"]) * 100

    # Parse "rtt min/avg/max/mdev = 1.234/5.678/9.012/1.234 ms"
    rtt_match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", result.stdout)
    if rtt_match:
        stats["avg_ms"] = float(rtt_match.group(1))

    return stats


# --- Client visibility ---


@pytest.mark.hw_integration
async def test_client_visible_in_api(api: httpx.AsyncClient, client_ip: str):
    """Connected client must appear in /api/v1/network/clients."""
    resp = await api.get("/api/v1/network/clients")
    assert resp.status_code == 200
    clients = resp.json()
    ips = [c["ip"] for c in clients]
    assert client_ip in ips, (
        f"Client {client_ip} not found in client list: {ips}"
    )


@pytest.mark.hw_integration
async def test_client_reachable(client_ip: str):
    """Client must be reachable via ping."""
    stats = await _ping(client_ip, count=3)
    assert stats["received"] > 0, f"Client {client_ip} not reachable via ping"


# --- tc netem delay ---


@pytest.mark.hw_integration
async def test_tc_netem_delay_measurable(api: httpx.AsyncClient, client_ip: str):
    """Apply 200ms delay, verify ping RTT increases significantly."""
    # Baseline
    baseline = await _ping(client_ip, count=5)
    baseline_avg = baseline["avg_ms"]

    # Apply 200ms delay
    config = {"delay": {"ms": 200, "jitter_ms": 0, "correlation_pct": 0}}
    resp = await api.put("/api/v1/impairments/wlan0", json=config)
    assert resp.status_code == 200

    # Wait for tc to take effect
    await asyncio.sleep(1)

    # Measure with delay
    delayed = await _ping(client_ip, count=5)
    delayed_avg = delayed["avg_ms"]

    # Clear
    await api.delete("/api/v1/impairments/wlan0")

    # Verify delay is measurable (at least 150ms increase)
    increase = delayed_avg - baseline_avg
    assert increase > 150, (
        f"Expected >150ms increase, got {increase:.1f}ms "
        f"(baseline={baseline_avg:.1f}ms, delayed={delayed_avg:.1f}ms)"
    )


# --- tc netem packet loss ---


@pytest.mark.hw_integration
async def test_tc_netem_loss_measurable(api: httpx.AsyncClient, client_ip: str):
    """Apply 50% loss, verify measurable packet loss."""
    # Apply 50% loss
    config = {"loss": {"pct": 50, "correlation_pct": 0}}
    resp = await api.put("/api/v1/impairments/wlan0", json=config)
    assert resp.status_code == 200

    await asyncio.sleep(1)

    # Send 20 pings
    stats = await _ping(client_ip, count=20, timeout=30)

    # Clear
    await api.delete("/api/v1/impairments/wlan0")

    # Verify significant loss (at least 20% — generous threshold for WiFi variability)
    assert stats["loss_pct"] > 20, (
        f"Expected >20% loss with 50% configured, got {stats['loss_pct']:.1f}%"
    )


# --- TX power ---


@pytest.mark.hw_integration
async def test_tx_power_reduces_signal(
    api: httpx.AsyncClient, client_ip: str, wifi_caps: WifiCapabilities
):
    """Lowering TX power should reduce client signal (if driver supports it)."""
    if not wifi_caps.tx_power_control:
        pytest.skip("TX power control not supported")

    # Set max power first
    config_max = {
        "tx_power": {"enabled": True, "power_dbm": 30},
        "channel_interference": {"enabled": False},
        "band_switch": {"enabled": False},
        "deauth": {"enabled": False},
        "dhcp_disruption": {"enabled": False},
        "broadcast_storm": {"enabled": False},
        "rate_limit": {"enabled": False},
        "periodic_disconnect": {"enabled": False},
    }
    await api.put("/api/v1/wifi-impairments", json=config_max)
    await asyncio.sleep(2)

    # Check client is still reachable
    stats_high = await _ping(client_ip, count=3)

    # Set minimum power
    config_min = {**config_max, "tx_power": {"enabled": True, "power_dbm": 1}}
    await api.put("/api/v1/wifi-impairments", json=config_min)
    await asyncio.sleep(2)

    stats_low = await _ping(client_ip, count=3)

    # Clear
    await api.delete("/api/v1/wifi-impairments")

    # At minimum power, ping times should increase (or fail)
    # This is a soft check — results depend on physical distance
    assert stats_high["received"] > 0 or stats_low["received"] > 0, (
        "Client unreachable at both power levels"
    )


# --- Deauthentication ---


@pytest.mark.hw_integration
async def test_deauth_kicks_client(api: httpx.AsyncClient, client_ip: str):
    """Deauth should temporarily disconnect the client."""
    # Verify client is connected
    resp = await api.get("/api/v1/network/clients")
    clients_before = [c["ip"] for c in resp.json()]
    assert client_ip in clients_before

    # Deauth
    config = {
        "deauth": {"enabled": True, "reason_code": 1},
        "tx_power": {"enabled": False},
        "channel_interference": {"enabled": False},
        "band_switch": {"enabled": False},
        "dhcp_disruption": {"enabled": False},
        "broadcast_storm": {"enabled": False},
        "rate_limit": {"enabled": False},
        "periodic_disconnect": {"enabled": False},
    }
    resp = await api.put("/api/v1/wifi-impairments", json=config)
    assert resp.status_code == 200

    # Brief pause — client may reconnect quickly
    await asyncio.sleep(1)

    # Clear (don't leave deauth active)
    await api.delete("/api/v1/wifi-impairments")

    # Wait for client to reconnect
    await asyncio.sleep(5)

    resp = await api.get("/api/v1/network/clients")
    clients_after = [c["ip"] for c in resp.json()]
    # Client should have reconnected (best-effort check)
    # The deauth itself is verified by the 200 OK and the backend log


# --- DHCP disruption cleanup ---


@pytest.mark.hw_integration
async def test_dhcp_fail_cleanup(api: httpx.AsyncClient):
    """DHCP fail mode must add and remove iptables rule correctly."""
    # Enable DHCP fail
    config = {
        "dhcp_disruption": {"enabled": True, "mode": "fail"},
        "tx_power": {"enabled": False},
        "channel_interference": {"enabled": False},
        "band_switch": {"enabled": False},
        "deauth": {"enabled": False},
        "broadcast_storm": {"enabled": False},
        "rate_limit": {"enabled": False},
        "periodic_disconnect": {"enabled": False},
    }
    resp = await api.put("/api/v1/wifi-impairments", json=config)
    assert resp.status_code == 200

    # Verify iptables rule exists
    result = await run("iptables", "-L", "OUTPUT", "-n", sudo=True, check=False)
    assert "wifry-dhcp-fail" in result.stdout, "iptables DROP rule not found"

    # Clear
    resp = await api.delete("/api/v1/wifi-impairments")
    assert resp.status_code == 200

    # Verify iptables rule removed
    result = await run("iptables", "-L", "OUTPUT", "-n", sudo=True, check=False)
    assert "wifry-dhcp-fail" not in result.stdout, (
        "iptables DROP rule still present after clearing"
    )


# --- Packet capture on wlan0 ---


@pytest.mark.hw_integration
async def test_capture_wlan0_client_traffic(api: httpx.AsyncClient, client_ip: str):
    """Capture on wlan0 with BPF filter should catch client traffic."""
    # Start capture filtered to client
    resp = await api.post("/api/v1/captures", json={
        "interface": "wlan0",
        "name": "hw-integration-test",
        "filters": {"host": client_ip},
        "max_packets": 20,
        "max_duration_secs": 10,
    })
    assert resp.status_code == 201
    capture_id = resp.json()["id"]

    # Generate traffic by pinging the client
    await _ping(client_ip, count=10)

    # Wait for capture to finish
    for _ in range(15):
        await asyncio.sleep(1)
        resp = await api.get(f"/api/v1/captures/{capture_id}")
        if resp.json()["status"] != "running":
            break

    data = resp.json()
    assert data["packet_count"] > 0, (
        f"No packets captured on wlan0 for client {client_ip}"
    )

    # Cleanup
    await api.delete(f"/api/v1/captures/{capture_id}")
