"""Integration tests for stream monitoring and proxy endpoints."""

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


# --- Stream monitoring ---

async def test_list_streams(client: AsyncClient):
    resp = await client.get("/api/v1/streams")
    assert resp.status_code == 200
    streams = resp.json()
    assert isinstance(streams, list)
    # Mock mode returns mock sessions
    if streams:
        s = streams[0]
        assert "id" in s
        assert "stream_type" in s
        assert "active" in s


async def test_get_stream_detail(client: AsyncClient):
    # In mock mode, any session_id returns mock detail
    resp = await client.get("/api/v1/streams/mock-session-1")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "stream_type" in data
    assert "variants" in data
    assert "segments" in data


# --- Internal stream event ---

async def test_receive_stream_event(client: AsyncClient):
    resp = await client.post("/api/v1/internal/stream-event", json={
        "event_type": "segment",
        "client_ip": "192.168.4.10",
        "url": "https://cdn.example.com/video/seg-001.ts",
        "content_type": "video/mp2t",
        "status_code": 200,
        "request_time_secs": 0.35,
        "response_size_bytes": 524288,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "session_id" in data


async def test_receive_manifest_event(client: AsyncClient):
    resp = await client.post("/api/v1/internal/stream-event", json={
        "event_type": "manifest",
        "client_ip": "192.168.4.10",
        "url": "https://cdn.example.com/video/master.m3u8",
        "content_type": "application/vnd.apple.mpegurl",
        "status_code": 200,
        "request_time_secs": 0.05,
        "response_size_bytes": 1024,
        "body": "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=5000000\nvideo.m3u8",
    })
    assert resp.status_code == 200


async def test_receive_error_event(client: AsyncClient):
    resp = await client.post("/api/v1/internal/stream-event", json={
        "event_type": "error",
        "client_ip": "192.168.4.10",
        "url": "https://cdn.example.com/video/seg-999.ts",
        "status_code": 404,
        "request_time_secs": 0.1,
        "response_size_bytes": 0,
    })
    assert resp.status_code == 200


# --- Proxy status ---

async def test_proxy_status(client: AsyncClient):
    resp = await client.get("/api/v1/proxy/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "running" in data
    assert "port" in data
    assert isinstance(data["enabled"], bool)
    assert isinstance(data["port"], int)
