"""Integration tests for FastAPI endpoints."""

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


async def test_health(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_get_impairments(client: AsyncClient):
    resp = await client.get("/api/v1/impairments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_interfaces(client: AsyncClient):
    resp = await client.get("/api/v1/network/interfaces")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_clients(client: AsyncClient):
    resp = await client.get("/api/v1/network/clients")
    assert resp.status_code == 200


async def test_get_system_info(client: AsyncClient):
    resp = await client.get("/api/v1/system/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data


async def test_list_profiles(client: AsyncClient):
    resp = await client.get("/api/v1/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert "profiles" in data


async def test_ap_status(client: AsyncClient):
    resp = await client.get("/api/v1/network/ap/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "ssid" in data
