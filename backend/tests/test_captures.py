"""Tests for capture and AI analysis endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.capture import CaptureFilters


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


async def test_list_captures_empty(client: AsyncClient):
    resp = await client.get("/api/v1/captures")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_start_capture_mock(client: AsyncClient):
    resp = await client.post("/api/v1/captures", json={
        "interface": "wlan0",
        "name": "test-capture",
        "filters": {"host": "192.168.4.10", "port": 443, "protocol": "tcp"},
        "max_packets": 100,
        "max_duration_secs": 10,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-capture"
    assert data["interface"] == "wlan0"
    assert data["id"]


async def test_get_capture(client: AsyncClient):
    # Start one first
    resp = await client.post("/api/v1/captures", json={
        "interface": "wlan0",
        "name": "get-test",
    })
    capture_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/captures/{capture_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == capture_id


async def test_get_capture_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/captures/nonexistent")
    assert resp.status_code == 404


async def test_analyze_capture_mock(client: AsyncClient):
    """Test that analyze endpoint starts background analysis, then results are available."""
    import asyncio

    # Start a capture
    resp = await client.post("/api/v1/captures", json={
        "interface": "wlan0",
        "name": "analysis-test",
    })
    capture_id = resp.json()["id"]

    # Trigger analysis — now returns immediately with "started"
    resp = await client.post(f"/api/v1/captures/{capture_id}/analyze", json={
        "provider": "anthropic",
        "prompt": "Analyze for issues",
        "focus": ["retransmissions"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("started", "already_running")
    assert data["capture_id"] == capture_id

    # Wait for background task to complete (mock is instant, but yield to event loop)
    for _ in range(20):
        await asyncio.sleep(0.1)
        resp = await client.get(f"/api/v1/captures/{capture_id}")
        info = resp.json()
        if info.get("analysis_status") == "done":
            break

    assert info["analysis_status"] == "done"
    assert info["has_analysis"] is True

    # Fetch actual analysis results
    resp = await client.get(f"/api/v1/captures/{capture_id}/analysis")
    assert resp.status_code == 200
    data = resp.json()
    assert data["capture_id"] == capture_id
    assert data["summary"]
    # V2 response uses 'findings' with evidence and confidence
    assert len(data["findings"]) > 0
    assert data["findings"][0]["severity"]
    assert data["findings"][0]["category"]
    assert data["findings"][0]["confidence"]
    assert len(data["findings"][0]["evidence"]) > 0
    assert data["health_badge"] in ("healthy", "degraded", "unhealthy", "insufficient")


async def test_get_analysis(client: AsyncClient):
    """Test that analysis results persist and can be retrieved after completion."""
    import asyncio

    # Start + analyze
    resp = await client.post("/api/v1/captures", json={"interface": "wlan0"})
    capture_id = resp.json()["id"]

    await client.post(f"/api/v1/captures/{capture_id}/analyze", json={})

    # Wait for background task
    for _ in range(20):
        await asyncio.sleep(0.1)
        info_resp = await client.get(f"/api/v1/captures/{capture_id}")
        if info_resp.json().get("analysis_status") == "done":
            break

    resp = await client.get(f"/api/v1/captures/{capture_id}/analysis")
    assert resp.status_code == 200
    assert resp.json()["capture_id"] == capture_id


async def test_delete_capture(client: AsyncClient):
    resp = await client.post("/api/v1/captures", json={"interface": "wlan0"})
    capture_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/captures/{capture_id}")
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/captures/{capture_id}")
    assert resp.status_code == 404


class TestCaptureFilters:
    def test_empty_bpf(self):
        f = CaptureFilters()
        assert f.to_bpf() == ""

    def test_host_only(self):
        f = CaptureFilters(host="192.168.4.10")
        assert f.to_bpf() == "host 192.168.4.10"

    def test_port_only(self):
        f = CaptureFilters(port=443)
        assert f.to_bpf() == "port 443"

    def test_protocol_and_host(self):
        f = CaptureFilters(protocol="tcp", host="10.0.0.1")
        assert f.to_bpf() == "tcp and host 10.0.0.1"

    def test_full_filter(self):
        f = CaptureFilters(protocol="tcp", host="10.0.0.1", port=443)
        bpf = f.to_bpf()
        assert "tcp" in bpf
        assert "host 10.0.0.1" in bpf
        assert "port 443" in bpf

    def test_inbound_direction(self):
        f = CaptureFilters(host="10.0.0.1", direction="inbound")
        assert f.to_bpf() == "src host 10.0.0.1"

    def test_outbound_direction(self):
        f = CaptureFilters(host="10.0.0.1", direction="outbound")
        assert f.to_bpf() == "dst host 10.0.0.1"

    def test_custom_bpf_overrides(self):
        f = CaptureFilters(
            host="10.0.0.1",
            port=80,
            custom_bpf="icmp or arp",
        )
        assert f.to_bpf() == "icmp or arp"
