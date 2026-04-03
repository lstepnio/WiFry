"""Integration tests for session lifecycle endpoints."""

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


async def _create_session(client: AsyncClient, name: str = "Test Session") -> dict:
    """Helper to create a session and return its JSON."""
    resp = await client.post("/api/v1/sessions", json={
        "name": name,
        "description": "Automated test session",
        "tags": ["test", "automated"],
    })
    assert resp.status_code == 201
    return resp.json()


# --- CRUD ---

async def test_create_session(client: AsyncClient):
    data = await _create_session(client)
    assert data["name"] == "Test Session"
    assert data["description"] == "Automated test session"
    assert data["status"] == "active"
    assert data["id"]
    assert "test" in data["tags"]


async def test_list_sessions(client: AsyncClient):
    await _create_session(client, "List-A")
    await _create_session(client, "List-B")
    resp = await client.get("/api/v1/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert isinstance(sessions, list)
    names = [s["name"] for s in sessions]
    assert "List-A" in names
    assert "List-B" in names


async def test_get_session_detail(client: AsyncClient):
    created = await _create_session(client, "Detail")
    sid = created["id"]
    resp = await client.get(f"/api/v1/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid
    assert resp.json()["name"] == "Detail"


async def test_get_session_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/sessions/nonexistent-id")
    assert resp.status_code == 404


# --- Active session ---

async def test_get_active_session_default(client: AsyncClient):
    resp = await client.get("/api/v1/sessions/active")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_session_id" in data


async def test_set_active_session(client: AsyncClient):
    created = await _create_session(client, "Activate-Me")
    sid = created["id"]
    resp = await client.post(f"/api/v1/sessions/{sid}/activate")
    assert resp.status_code == 200
    assert resp.json()["active_session_id"] == sid

    # Verify it's now active
    resp = await client.get("/api/v1/sessions/active")
    assert resp.json()["active_session_id"] == sid


async def test_set_active_session_not_found(client: AsyncClient):
    resp = await client.post("/api/v1/sessions/nonexistent/activate")
    assert resp.status_code == 404


# --- Complete ---

async def test_complete_session(client: AsyncClient):
    created = await _create_session(client, "Complete-Me")
    sid = created["id"]
    resp = await client.post(f"/api/v1/sessions/{sid}/complete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


async def test_complete_session_not_found(client: AsyncClient):
    resp = await client.post("/api/v1/sessions/nonexistent/complete")
    assert resp.status_code == 404


# --- Notes & Tags ---

async def test_update_notes(client: AsyncClient):
    created = await _create_session(client, "Notes-Test")
    sid = created["id"]
    resp = await client.put(f"/api/v1/sessions/{sid}/notes", json={
        "notes": "Updated notes here",
    })
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated notes here"


async def test_update_notes_not_found(client: AsyncClient):
    resp = await client.put("/api/v1/sessions/nonexistent/notes", json={
        "notes": "fail",
    })
    assert resp.status_code == 404


async def test_update_tags(client: AsyncClient):
    created = await _create_session(client, "Tags-Test")
    sid = created["id"]
    resp = await client.put(f"/api/v1/sessions/{sid}/tags", json={
        "tags": ["wifi", "regression", "5ghz"],
    })
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["wifi", "regression", "5ghz"]


async def test_update_tags_not_found(client: AsyncClient):
    resp = await client.put("/api/v1/sessions/nonexistent/tags", json={
        "tags": ["fail"],
    })
    assert resp.status_code == 404


# --- Artifacts ---

async def test_add_and_list_artifacts(client: AsyncClient):
    created = await _create_session(client, "Artifact-Test")
    sid = created["id"]

    # Add artifact
    resp = await client.post(f"/api/v1/sessions/{sid}/artifacts", json={
        "type": "note",
        "name": "Test note",
        "description": "A test annotation",
        "tags": ["test"],
        "data": {"key": "value"},
    })
    assert resp.status_code == 201
    artifact = resp.json()
    assert artifact["name"] == "Test note"
    assert artifact["type"] == "note"
    assert artifact["session_id"] == sid

    # List artifacts
    resp = await client.get(f"/api/v1/sessions/{sid}/artifacts")
    assert resp.status_code == 200
    artifacts = resp.json()
    assert isinstance(artifacts, list)
    assert any(a["name"] == "Test note" for a in artifacts)


async def test_add_artifact_invalid_type(client: AsyncClient):
    created = await _create_session(client, "BadArtifact")
    sid = created["id"]
    resp = await client.post(f"/api/v1/sessions/{sid}/artifacts", json={
        "type": "invalid_type_xyz",
        "name": "Bad",
    })
    assert resp.status_code == 400


# --- Delete ---

async def test_delete_session(client: AsyncClient):
    created = await _create_session(client, "Delete-Me")
    sid = created["id"]
    resp = await client.delete(f"/api/v1/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Should be gone
    resp = await client.get(f"/api/v1/sessions/{sid}")
    assert resp.status_code == 404


async def test_discard_session(client: AsyncClient):
    created = await _create_session(client, "Discard-Me")
    sid = created["id"]
    resp = await client.post(f"/api/v1/sessions/{sid}/discard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "discard" in data.get("message", "").lower() or data["status"] == "ok"

    # Should be gone
    resp = await client.get(f"/api/v1/sessions/{sid}")
    assert resp.status_code == 404
