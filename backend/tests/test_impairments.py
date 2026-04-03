"""Integration tests for impairment and wifi-impairment endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# --- Network impairments (tc netem) ---

async def test_list_impairments(client: AsyncClient):
    resp = await client.get("/api/v1/impairments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_apply_impairment(client: AsyncClient):
    resp = await client.put("/api/v1/impairments/wlan0", json={
        "delay": {"ms": 100, "jitter_ms": 10},
        "loss": {"pct": 5.0},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["interface"] == "wlan0"


async def test_get_single_impairment(client: AsyncClient):
    resp = await client.get("/api/v1/impairments/wlan0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["interface"] == "wlan0"
    assert "active" in data
    assert "config" in data


async def test_clear_impairment(client: AsyncClient):
    # Apply first
    await client.put("/api/v1/impairments/wlan0", json={
        "delay": {"ms": 50},
    })
    # Clear
    resp = await client.delete("/api/v1/impairments/wlan0")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["interface"] == "wlan0"


async def test_clear_all_impairments(client: AsyncClient):
    resp = await client.delete("/api/v1/impairments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "interfaces" in data


async def test_apply_impairment_with_rate(client: AsyncClient):
    resp = await client.put("/api/v1/impairments/wlan0", json={
        "rate": {"kbit": 1000, "burst": "32kbit"},
    })
    assert resp.status_code == 200


async def test_apply_impairment_with_all_params(client: AsyncClient):
    resp = await client.put("/api/v1/impairments/wlan0", json={
        "delay": {"ms": 200, "jitter_ms": 50, "correlation_pct": 25},
        "loss": {"pct": 10, "correlation_pct": 50},
        "corrupt": {"pct": 1},
        "duplicate": {"pct": 2},
        "reorder": {"pct": 5, "correlation_pct": 50},
        "rate": {"kbit": 5000},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["interface"] == "wlan0"


async def test_apply_empty_impairment(client: AsyncClient):
    resp = await client.put("/api/v1/impairments/wlan0", json={})
    assert resp.status_code == 200


# --- WiFi-layer impairments ---

async def test_get_wifi_impairment_state(client: AsyncClient):
    resp = await client.get("/api/v1/wifi-impairments")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data
    assert "active_impairments" in data
    assert isinstance(data["active_impairments"], list)


async def test_apply_wifi_impairments(client: AsyncClient):
    resp = await client.put("/api/v1/wifi-impairments", json={
        "channel_interference": {"enabled": True, "beacon_interval_ms": 200},
        "tx_power": {"enabled": True, "power_dbm": 10},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data
    assert "active_impairments" in data


async def test_clear_wifi_impairments(client: AsyncClient):
    resp = await client.delete("/api/v1/wifi-impairments")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data
    assert isinstance(data["active_impairments"], list)


async def test_apply_deauth_impairment(client: AsyncClient):
    resp = await client.put("/api/v1/wifi-impairments/deauth", json={
        "enabled": True,
        "target_mac": "",
        "reason_code": 3,
    })
    assert resp.status_code == 200


async def test_apply_tx_power_impairment(client: AsyncClient):
    resp = await client.put("/api/v1/wifi-impairments/tx-power", json={
        "enabled": True,
        "power_dbm": 5,
    })
    assert resp.status_code == 200


async def test_apply_periodic_disconnect(client: AsyncClient):
    resp = await client.put("/api/v1/wifi-impairments/periodic-disconnect", json={
        "enabled": True,
        "interval_secs": 60,
        "disconnect_duration_secs": 3,
    })
    assert resp.status_code == 200
