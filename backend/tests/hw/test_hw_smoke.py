"""Tier 2: API Smoke Tests — quick checks that endpoints work on real hardware.

No WiFi client needed. Verifies the backend responds correctly in non-mock mode.
"""

import asyncio

import httpx
import pytest

from .hw_capabilities import WifiCapabilities


# --- Health & system info ---


@pytest.mark.hw_smoke
async def test_health_not_mock(api: httpx.AsyncClient):
    """Health endpoint must report mock_mode=false."""
    resp = await api.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["mock_mode"] is False


@pytest.mark.hw_smoke
async def test_system_info_real(api: httpx.AsyncClient):
    """System info must return real hardware data."""
    resp = await api.get("/api/v1/system/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] != ""
    assert "Linux" in data["os"]
    # RPi should report temperature
    assert data["temperature_c"] > 0, "Temperature not reported"
    assert data["memory_total_mb"] > 0


# --- Endpoint availability ---

API_ENDPOINTS = [
    "/api/v1/health",
    "/api/v1/system/info",
    "/api/v1/system/features",
    "/api/v1/system/settings",
    "/api/v1/system/dependencies",
    "/api/v1/impairments",
    "/api/v1/wifi-impairments",
    "/api/v1/profiles",
    "/api/v1/network/interfaces",
    "/api/v1/network/clients",
    "/api/v1/network/ap/status",
    "/api/v1/captures",
    "/api/v1/streams",
    "/api/v1/adb/devices",
    "/api/v1/sessions",
    "/api/v1/dns/status",
    "/api/v1/network-config/current",
]


@pytest.mark.hw_smoke
@pytest.mark.parametrize("endpoint", API_ENDPOINTS)
async def test_api_endpoint_responds(api: httpx.AsyncClient, endpoint: str):
    """API endpoint must return 200 (not 500)."""
    resp = await api.get(endpoint)
    assert resp.status_code == 200, (
        f"{endpoint} returned {resp.status_code}: {resp.text[:200]}"
    )


# --- Feature flags ---


@pytest.mark.hw_smoke
async def test_feature_flags_populated(api: httpx.AsyncClient):
    """Feature flags must return a non-empty dict."""
    resp = await api.get("/api/v1/system/features")
    assert resp.status_code == 200
    flags = resp.json()
    assert len(flags) > 0, "Feature flags dict is empty"


# --- Network config round-trip ---


@pytest.mark.hw_smoke
async def test_network_config_roundtrip(api: httpx.AsyncClient):
    """Read current config, re-apply it, verify it persists."""
    # Read current
    resp = await api.get("/api/v1/network-config/current")
    assert resp.status_code == 200
    config = resp.json()

    # Re-apply the same config
    resp = await api.put("/api/v1/network-config/apply", json=config)
    assert resp.status_code == 200

    # Read back
    resp = await api.get("/api/v1/network-config/current")
    assert resp.status_code == 200
    config2 = resp.json()
    assert config2["wifi_ap"]["ssid"] == config["wifi_ap"]["ssid"]


# --- tc netem impairment ---


@pytest.mark.hw_smoke
async def test_tc_netem_apply_clear(api: httpx.AsyncClient):
    """Apply a small tc netem delay on wlan0, verify active, then clear."""
    # Apply 10ms delay
    config = {
        "delay": {"ms": 10, "jitter_ms": 0, "correlation_pct": 0},
    }
    resp = await api.put("/api/v1/impairments/wlan0", json=config)
    assert resp.status_code == 200

    # Verify active
    resp = await api.get("/api/v1/impairments")
    assert resp.status_code == 200
    states = resp.json()
    wlan0 = next((s for s in states if s["interface"] == "wlan0"), None)
    assert wlan0 is not None
    assert wlan0["active"] is True

    # Clear
    resp = await api.delete("/api/v1/impairments/wlan0")
    assert resp.status_code == 200

    # Verify cleared
    resp = await api.get("/api/v1/impairments")
    states = resp.json()
    wlan0 = next((s for s in states if s["interface"] == "wlan0"), None)
    assert wlan0 is None or wlan0["active"] is False


# --- WiFi impairment ---


@pytest.mark.hw_smoke
async def test_wifi_impairment_apply_clear(
    api: httpx.AsyncClient, wifi_caps: WifiCapabilities
):
    """Apply a WiFi impairment (TX power if supported), then clear."""
    if not wifi_caps.tx_power_control:
        pytest.skip("TX power control not supported by driver")

    config = {
        "tx_power": {"enabled": True, "power_dbm": 15},
        "channel_interference": {"enabled": False},
        "band_switch": {"enabled": False},
        "deauth": {"enabled": False},
        "dhcp_disruption": {"enabled": False},
        "broadcast_storm": {"enabled": False},
        "rate_limit": {"enabled": False},
        "periodic_disconnect": {"enabled": False},
    }
    resp = await api.put("/api/v1/wifi-impairments", json=config)
    assert resp.status_code == 200
    data = resp.json()
    assert "tx_power" in data.get("active_impairments", [])

    # Clear
    resp = await api.delete("/api/v1/wifi-impairments")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data.get("active_impairments", [])) == 0


# --- Packet capture ---


@pytest.mark.hw_smoke
async def test_capture_on_eth0(api: httpx.AsyncClient):
    """Start a brief capture on eth0 (always has traffic), verify packets."""
    # Start capture on eth0
    resp = await api.post("/api/v1/captures", json={
        "interface": "eth0",
        "name": "hw-smoke-test",
        "max_packets": 50,
        "max_duration_secs": 5,
    })
    assert resp.status_code == 201
    capture_id = resp.json()["id"]

    # Wait for capture to complete
    for _ in range(10):
        await asyncio.sleep(1)
        resp = await api.get(f"/api/v1/captures/{capture_id}")
        if resp.json()["status"] != "running":
            break

    data = resp.json()
    assert data["status"] in ("completed", "stopped"), f"Capture status: {data['status']}"
    assert data["packet_count"] > 0, "No packets captured on eth0"

    # Cleanup
    await api.delete(f"/api/v1/captures/{capture_id}")


# --- DNS config ---


@pytest.mark.hw_smoke
async def test_dns_config_roundtrip(api: httpx.AsyncClient):
    """Read DNS config, verify structure."""
    resp = await api.get("/api/v1/dns/config")
    assert resp.status_code == 200
    config = resp.json()
    assert "enabled" in config
    assert "upstream" in config
    assert "impairments" in config


# --- Dependencies check ---


@pytest.mark.hw_smoke
async def test_dependencies_check(api: httpx.AsyncClient):
    """Dependencies endpoint must return real check results."""
    resp = await api.get("/api/v1/system/dependencies")
    assert resp.status_code == 200
    deps = resp.json()
    # tshark must be installed
    assert deps.get("tshark", {}).get("installed") is True, "tshark not installed"
