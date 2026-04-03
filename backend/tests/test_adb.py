"""Integration tests for ADB endpoints (mock mode)."""

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


# --- Device management ---

async def test_list_devices(client: AsyncClient):
    resp = await client.get("/api/v1/adb/devices")
    assert resp.status_code == 200
    devices = resp.json()
    assert isinstance(devices, list)
    # Mock mode returns at least one device
    if devices:
        dev = devices[0]
        assert "serial" in dev
        assert "state" in dev


async def test_connect_device(client: AsyncClient):
    resp = await client.post("/api/v1/adb/connect", json={
        "ip": "192.168.4.10",
        "port": 5555,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "serial" in data
    assert "state" in data


async def test_connect_device_default_port(client: AsyncClient):
    resp = await client.post("/api/v1/adb/connect", json={
        "ip": "10.0.0.50",
    })
    assert resp.status_code == 200
    assert "serial" in resp.json()


# --- Shell ---

async def test_run_shell_command(client: AsyncClient):
    resp = await client.post("/api/v1/adb/shell", json={
        "serial": "192.168.4.10:5555",
        "command": "getprop ro.product.model",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "stdout" in data
    assert "exit_code" in data
    assert data["serial"] == "192.168.4.10:5555"
    assert data["command"] == "getprop ro.product.model"


async def test_run_shell_command_with_timeout(client: AsyncClient):
    resp = await client.post("/api/v1/adb/shell", json={
        "serial": "192.168.4.10:5555",
        "command": "ls /sdcard",
        "timeout": 10,
    })
    assert resp.status_code == 200


# --- Key events ---

async def test_send_key_event(client: AsyncClient):
    resp = await client.post("/api/v1/adb/key", json={
        "serial": "192.168.4.10:5555",
        "keycode": "KEYCODE_HOME",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["keycode"] == "KEYCODE_HOME"


async def test_get_keycodes(client: AsyncClient):
    resp = await client.get("/api/v1/adb/keycodes")
    assert resp.status_code == 200
    keycodes = resp.json()
    assert isinstance(keycodes, dict)
    assert "home" in keycodes
    assert "back" in keycodes
    assert "enter" in keycodes
    assert keycodes["home"] == "KEYCODE_HOME"


# --- Logcat ---

async def test_start_logcat(client: AsyncClient):
    resp = await client.post("/api/v1/adb/logcat/start", params={
        "serial": "192.168.4.10:5555",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "serial" in data


async def test_list_logcat_sessions(client: AsyncClient):
    resp = await client.get("/api/v1/adb/logcat")
    assert resp.status_code == 200
    sessions = resp.json()
    assert isinstance(sessions, list)


# --- Screenshots & Bugreports ---

async def test_screencap(client: AsyncClient):
    resp = await client.post("/api/v1/adb/screencap/192.168.4.10:5555")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "path" in data
    assert "filename" in data


async def test_bugreport(client: AsyncClient):
    resp = await client.post("/api/v1/adb/bugreport/192.168.4.10:5555")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "path" in data
    assert "filename" in data
