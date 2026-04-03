"""Integration tests for sharing and file.io endpoints."""

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


async def test_share_index(client: AsyncClient):
    resp = await client.get("/api/v1/share")
    assert resp.status_code == 200
    data = resp.json()
    assert "title" in data
    assert "categories" in data
    assert isinstance(data["categories"], dict)
    assert "tunnel" in data


async def test_fileio_history(client: AsyncClient):
    resp = await client.get("/api/v1/fileio/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
