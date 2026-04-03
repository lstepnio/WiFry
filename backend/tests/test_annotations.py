"""Integration tests for annotation endpoints."""

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


async def test_create_annotation(client: AsyncClient):
    resp = await client.post("/api/v1/annotations", json={
        "target_type": "capture",
        "target_id": "cap-001",
        "note": "Saw packet loss spike during playback",
        "tags": ["packet-loss", "playback"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["note"] == "Saw packet loss spike during playback"
    assert data["target_type"] == "capture"
    assert data["target_id"] == "cap-001"


async def test_list_annotations(client: AsyncClient):
    # Create a couple
    await client.post("/api/v1/annotations", json={
        "target_type": "stream",
        "target_id": "stream-001",
        "note": "Bitrate dropped to 720p",
        "tags": ["bitrate"],
    })
    await client.post("/api/v1/annotations", json={
        "target_type": "stream",
        "target_id": "stream-001",
        "note": "Recovered to 1080p",
        "tags": ["bitrate", "recovery"],
    })

    resp = await client.get("/api/v1/annotations")
    assert resp.status_code == 200
    annotations = resp.json()
    assert isinstance(annotations, list)
    assert len(annotations) >= 2


async def test_list_annotations_filter_by_type(client: AsyncClient):
    await client.post("/api/v1/annotations", json={
        "target_type": "device",
        "target_id": "dev-001",
        "note": "Device rebooted",
    })
    resp = await client.get("/api/v1/annotations", params={"target_type": "device"})
    assert resp.status_code == 200
    annotations = resp.json()
    for ann in annotations:
        assert ann["target_type"] == "device"


async def test_list_annotations_filter_by_tag(client: AsyncClient):
    await client.post("/api/v1/annotations", json={
        "target_type": "general",
        "target_id": "test",
        "note": "Tagged annotation",
        "tags": ["unique-tag-xyz"],
    })
    resp = await client.get("/api/v1/annotations", params={"tag": "unique-tag-xyz"})
    assert resp.status_code == 200
    annotations = resp.json()
    assert len(annotations) >= 1
    for ann in annotations:
        assert "unique-tag-xyz" in ann["tags"]


async def test_delete_annotation(client: AsyncClient):
    # Create one
    resp = await client.post("/api/v1/annotations", json={
        "target_type": "capture",
        "target_id": "cap-del",
        "note": "To be deleted",
    })
    ann_id = resp.json()["id"]

    # Delete it
    resp = await client.delete(f"/api/v1/annotations/{ann_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_create_annotation_general(client: AsyncClient):
    resp = await client.post("/api/v1/annotations", json={
        "target_type": "general",
        "target_id": "session-1",
        "note": "General observation about test environment",
        "tags": ["environment", "observation"],
    })
    assert resp.status_code == 201
    assert resp.json()["target_type"] == "general"
