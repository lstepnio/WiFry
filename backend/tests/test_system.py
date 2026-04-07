"""Integration tests for system, network config, wifi scan, speedtest, tunnel, and collab endpoints."""

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


# --- System info ---

async def test_system_info(client: AsyncClient):
    resp = await client.get("/api/v1/system/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert "platform" in data
    assert "os" in data
    # Mock mode provides temperature and memory
    assert "temperature_c" in data
    assert "memory_total_mb" in data


async def test_system_settings(client: AsyncClient):
    resp = await client.get("/api/v1/system/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "mock_mode" in data
    assert data["mock_mode"] is True


async def test_feature_flags_default_surface(client: AsyncClient):
    resp = await client.get("/api/v1/system/features")
    assert resp.status_code == 200
    flags = resp.json()
    assert flags["sessions"]["enabled"] is True
    assert flags["sharing_fileio"]["enabled"] is True
    assert flags["sharing_tunnel"]["enabled"] is False
    assert flags["collaboration"]["enabled"] is False


# --- Network config ---

async def test_network_config_current(client: AsyncClient):
    resp = await client.get("/api/v1/network-config/current")
    assert resp.status_code == 200
    data = resp.json()
    # Should return a FullNetworkConfig
    assert isinstance(data, dict)


async def test_network_config_first_boot(client: AsyncClient):
    resp = await client.get("/api/v1/network-config/first-boot")
    assert resp.status_code == 200
    data = resp.json()
    assert "first_boot" in data
    assert isinstance(data["first_boot"], bool)


# --- WiFi scan ---

async def test_wifi_scan(client: AsyncClient):
    resp = await client.get("/api/v1/wifi/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert "networks" in data
    assert "network_count" in data
    assert isinstance(data["networks"], list)
    assert "scan_interface" in data


# --- Speed test ---

async def test_speedtest_run(client: AsyncClient):
    resp = await client.post("/api/v1/speedtest/run")
    assert resp.status_code == 200
    data = resp.json()
    # Mock mode returns speed test results
    assert isinstance(data, dict)


# --- Tunnel ---

async def test_tunnel_status(client: AsyncClient):
    resp = await client.get("/api/v1/tunnel/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# --- Collaboration ---

async def test_collab_status(client: AsyncClient):
    resp = await client.get("/api/v1/collab/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# --- System logs (mock mode) ---

async def test_system_logs(client: AsyncClient):
    resp = await client.get("/api/v1/system/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data
    assert "total" in data
    assert isinstance(data["lines"], list)


# --- Storage ---

async def test_storage_status(client: AsyncClient):
    resp = await client.get("/api/v1/system/storage/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
