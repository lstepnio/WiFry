"""Integration tests for impairment profile endpoints."""

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


# --- List & Get ---

async def test_list_profiles(client: AsyncClient):
    resp = await client.get("/api/v1/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert "profiles" in data
    profiles = data["profiles"]
    assert isinstance(profiles, list)
    # Built-in profiles should be present
    assert len(profiles) >= 12


async def test_list_profiles_has_builtin(client: AsyncClient):
    resp = await client.get("/api/v1/profiles")
    profiles = resp.json()["profiles"]
    builtin_names = [p["name"] for p in profiles if p.get("builtin")]
    assert len(builtin_names) > 0


async def test_get_single_profile(client: AsyncClient):
    # Get the list to find a valid name
    resp = await client.get("/api/v1/profiles")
    profiles = resp.json()["profiles"]
    assert len(profiles) > 0
    name = profiles[0]["name"]

    resp = await client.get(f"/api/v1/profiles/{name}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == name
    assert "config" in data


async def test_get_profile_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/profiles/nonexistent-profile-xyz")
    assert resp.status_code == 404


async def test_list_profiles_filter_by_category(client: AsyncClient):
    resp = await client.get("/api/v1/profiles", params={"category": "network"})
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    for p in profiles:
        assert p["category"] == "network"


# --- Create custom ---

async def test_create_custom_profile(client: AsyncClient):
    resp = await client.post("/api/v1/profiles", json={
        "name": "test-custom-profile",
        "description": "A test profile",
        "category": "network",
        "tags": ["test"],
        "config": {
            "delay": {"ms": 100, "jitter_ms": 20},
            "loss": {"pct": 5},
        },
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-custom-profile"
    assert data["description"] == "A test profile"

    # Cleanup
    await client.delete("/api/v1/profiles/test-custom-profile")


async def test_create_duplicate_profile(client: AsyncClient):
    # Create first
    await client.post("/api/v1/profiles", json={
        "name": "dup-test-profile",
        "description": "first",
        "config": {},
    })
    # Try duplicate
    resp = await client.post("/api/v1/profiles", json={
        "name": "dup-test-profile",
        "description": "second",
        "config": {},
    })
    assert resp.status_code == 409

    # Cleanup
    await client.delete("/api/v1/profiles/dup-test-profile")


# --- Update ---

async def test_update_custom_profile(client: AsyncClient):
    # Create
    await client.post("/api/v1/profiles", json={
        "name": "update-test-profile",
        "description": "original",
        "config": {},
    })

    # Update
    resp = await client.put("/api/v1/profiles/update-test-profile", json={
        "name": "update-test-profile",
        "description": "updated description",
        "config": {"delay": {"ms": 50}},
    })
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated description"

    # Cleanup
    await client.delete("/api/v1/profiles/update-test-profile")


async def test_update_builtin_profile_forbidden(client: AsyncClient):
    # Get a built-in profile name
    resp = await client.get("/api/v1/profiles")
    profiles = resp.json()["profiles"]
    builtin = next((p for p in profiles if p.get("builtin")), None)
    if builtin is None:
        pytest.skip("No built-in profiles found")

    resp = await client.put(f"/api/v1/profiles/{builtin['name']}", json={
        "name": builtin["name"],
        "description": "hacked",
        "config": {},
    })
    assert resp.status_code == 403


# --- Delete ---

async def test_delete_custom_profile(client: AsyncClient):
    # Create first
    await client.post("/api/v1/profiles", json={
        "name": "delete-me-profile",
        "description": "temporary",
        "config": {},
    })

    resp = await client.delete("/api/v1/profiles/delete-me-profile")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify gone
    resp = await client.get("/api/v1/profiles/delete-me-profile")
    assert resp.status_code == 404


async def test_delete_builtin_profile_forbidden(client: AsyncClient):
    resp = await client.get("/api/v1/profiles")
    profiles = resp.json()["profiles"]
    builtin = next((p for p in profiles if p.get("builtin")), None)
    if builtin is None:
        pytest.skip("No built-in profiles found")

    resp = await client.delete(f"/api/v1/profiles/{builtin['name']}")
    assert resp.status_code == 403


async def test_delete_nonexistent_profile(client: AsyncClient):
    resp = await client.delete("/api/v1/profiles/does-not-exist-xyz")
    assert resp.status_code == 404


# --- Apply ---

async def test_apply_profile(client: AsyncClient):
    resp = await client.get("/api/v1/profiles")
    profiles = resp.json()["profiles"]
    assert len(profiles) > 0
    name = profiles[0]["name"]

    resp = await client.post(f"/api/v1/profiles/{name}/apply", json={
        "interfaces": ["wlan0"],
        "apply_wifi": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["profile"] == name
    assert "interfaces" in data


async def test_apply_nonexistent_profile(client: AsyncClient):
    resp = await client.post("/api/v1/profiles/nonexistent-xyz/apply", json={
        "interfaces": ["wlan0"],
    })
    assert resp.status_code == 404
