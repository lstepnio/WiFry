"""Extended system endpoint tests: settings, storage, updates, logs, gremlin."""

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


# --- Settings ---

async def test_get_settings(client: AsyncClient):
    resp = await client.get("/api/v1/system/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "mock_mode" in data
    assert data["mock_mode"] is True
    assert "ai_provider" in data
    assert "ap_ssid" in data


async def test_update_settings(client: AsyncClient):
    resp = await client.put("/api/v1/system/settings", json={
        "ai_provider": "openai",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# --- Reboot (mock mode) ---

async def test_reboot_mock(client: AsyncClient):
    resp = await client.post("/api/v1/system/reboot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "mock"
    assert "mock" in data["message"].lower()


# --- Storage ---

async def test_storage_status(client: AsyncClient):
    resp = await client.get("/api/v1/system/storage/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


async def test_storage_usage(client: AsyncClient):
    resp = await client.get("/api/v1/system/storage/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


async def test_storage_detect_devices(client: AsyncClient):
    resp = await client.get("/api/v1/system/storage/devices")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Mock mode returns one device
    if data:
        device = data[0]
        assert "device" in device
        assert "size_bytes" in device


# --- Update check ---

async def test_update_check(client: AsyncClient):
    resp = await client.get("/api/v1/system/update/check")
    assert resp.status_code == 200
    data = resp.json()
    # Mock mode returns update info
    assert "current_commit" in data
    assert "current_branch" in data
    assert "update_available" in data


# --- Logs ---

async def test_get_logs(client: AsyncClient):
    resp = await client.get("/api/v1/system/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data
    assert "total" in data
    assert isinstance(data["lines"], list)
    assert data["total"] > 0


async def test_get_logs_with_lines_param(client: AsyncClient):
    resp = await client.get("/api/v1/system/logs", params={"lines": 50})
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data


async def test_get_logs_with_level_filter(client: AsyncClient):
    resp = await client.get("/api/v1/system/logs", params={"level": "error"})
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data


# --- Gremlin endpoints ---

async def test_gremlin_activate(client: AsyncClient):
    resp = await client.post("/api/v1/gremlin/activate", params={"intensity": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert data["intensity"] == 3
    assert data["intensity_label"] == "Severe"
    assert "details" in data

    # Cleanup
    await client.post("/api/v1/gremlin/deactivate")


async def test_gremlin_status(client: AsyncClient):
    resp = await client.get("/api/v1/gremlin/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "intensity" in data
    assert "intensity_label" in data
    assert "message" in data


async def test_gremlin_deactivate(client: AsyncClient):
    # Activate first
    await client.post("/api/v1/gremlin/activate", params={"intensity": 1})

    resp = await client.post("/api/v1/gremlin/deactivate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is False


async def test_gremlin_activate_default_intensity(client: AsyncClient):
    resp = await client.post("/api/v1/gremlin/activate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert data["intensity"] == 2  # default

    # Cleanup
    await client.post("/api/v1/gremlin/deactivate")


async def test_gremlin_activate_deactivate_cycle(client: AsyncClient):
    # Full cycle
    resp = await client.post("/api/v1/gremlin/activate", params={"intensity": 4})
    assert resp.json()["active"] is True
    assert resp.json()["intensity"] == 4

    resp = await client.get("/api/v1/gremlin/status")
    assert resp.json()["active"] is True

    resp = await client.post("/api/v1/gremlin/deactivate")
    assert resp.json()["active"] is False

    resp = await client.get("/api/v1/gremlin/status")
    assert resp.json()["active"] is False


# --- System info (extended checks) ---

async def test_system_info_fields(client: AsyncClient):
    resp = await client.get("/api/v1/system/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert "platform" in data
    assert "os" in data
    assert "temperature_c" in data
    assert "memory_total_mb" in data
    assert "memory_used_mb" in data
    assert "memory_available_mb" in data
    assert "uptime" in data
    # Validate types
    assert isinstance(data["temperature_c"], (int, float))
    assert isinstance(data["memory_total_mb"], int)
