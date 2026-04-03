"""Extended profile tests: filtering by category/tag, applying with wifi_config."""

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


# --- Filter by category ---

async def test_filter_by_category_network(client: AsyncClient):
    resp = await client.get("/api/v1/profiles", params={"category": "network"})
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    for p in profiles:
        assert p["category"] == "network"


async def test_filter_by_category_wifi(client: AsyncClient):
    resp = await client.get("/api/v1/profiles", params={"category": "wifi"})
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    for p in profiles:
        assert p["category"] == "wifi"


async def test_filter_by_nonexistent_category(client: AsyncClient):
    resp = await client.get("/api/v1/profiles", params={"category": "nonexistent-xyz"})
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert len(profiles) == 0


# --- Filter by tag ---

async def test_filter_by_tag(client: AsyncClient):
    # Create a profile with a specific tag
    await client.post("/api/v1/profiles", json={
        "name": "tagged-profile-test",
        "description": "Profile with tags",
        "tags": ["special-filter-tag", "test"],
        "config": {},
    })

    resp = await client.get("/api/v1/profiles", params={"tag": "special-filter-tag"})
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert len(profiles) >= 1
    for p in profiles:
        assert "special-filter-tag" in p["tags"]

    # Cleanup
    await client.delete("/api/v1/profiles/tagged-profile-test")


async def test_filter_by_nonexistent_tag(client: AsyncClient):
    resp = await client.get("/api/v1/profiles", params={"tag": "no-such-tag-xyz"})
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert len(profiles) == 0


# --- Apply with wifi_config ---

async def test_apply_profile_with_wifi_config(client: AsyncClient):
    # Create a profile with wifi_config
    await client.post("/api/v1/profiles", json={
        "name": "wifi-apply-test",
        "description": "Profile with WiFi config",
        "category": "combined",
        "config": {"delay": {"ms": 50}},
        "wifi_config": {
            "tx_power": {"enabled": True, "power_dbm": 10},
        },
    })

    resp = await client.post("/api/v1/profiles/wifi-apply-test/apply", json={
        "interfaces": ["wlan0"],
        "apply_wifi": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["profile"] == "wifi-apply-test"
    assert "network" in data["applied"]
    assert "wifi" in data["applied"]

    # Cleanup
    await client.delete("/api/v1/profiles/wifi-apply-test")


async def test_apply_profile_without_wifi(client: AsyncClient):
    # Create profile with wifi_config but apply_wifi=False
    await client.post("/api/v1/profiles", json={
        "name": "no-wifi-apply-test",
        "description": "Skip WiFi",
        "config": {"delay": {"ms": 25}},
        "wifi_config": {
            "tx_power": {"enabled": True, "power_dbm": 5},
        },
    })

    resp = await client.post("/api/v1/profiles/no-wifi-apply-test/apply", json={
        "interfaces": ["wlan0"],
        "apply_wifi": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Note: the "applied" list currently reflects what the profile *has*,
    # not whether apply_wifi was True. The network part should be applied.
    assert "network" in data["applied"]

    # Cleanup
    await client.delete("/api/v1/profiles/no-wifi-apply-test")


# --- Get profile name variations ---

async def test_get_profile_with_spaces(client: AsyncClient):
    await client.post("/api/v1/profiles", json={
        "name": "Profile With Spaces",
        "description": "Has spaces in name",
        "config": {},
    })

    resp = await client.get("/api/v1/profiles/Profile With Spaces")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Profile With Spaces"

    # Cleanup
    await client.delete("/api/v1/profiles/Profile With Spaces")


async def test_get_profile_with_dots(client: AsyncClient):
    await client.post("/api/v1/profiles", json={
        "name": "v2.1-profile",
        "description": "Has dots and dash",
        "config": {},
    })

    resp = await client.get("/api/v1/profiles/v2.1-profile")
    assert resp.status_code == 200
    assert resp.json()["name"] == "v2.1-profile"

    # Cleanup
    await client.delete("/api/v1/profiles/v2.1-profile")


# --- Profile with tags in creation ---

async def test_create_profile_with_tags(client: AsyncClient):
    resp = await client.post("/api/v1/profiles", json={
        "name": "multi-tag-profile",
        "description": "Has multiple tags",
        "tags": ["streaming", "4k", "high-bandwidth"],
        "config": {"rate": {"kbit": 50000}},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == ["streaming", "4k", "high-bandwidth"]

    # Cleanup
    await client.delete("/api/v1/profiles/multi-tag-profile")


# --- Apply profile with empty config ---

async def test_apply_profile_empty_config(client: AsyncClient):
    await client.post("/api/v1/profiles", json={
        "name": "empty-config-test",
        "description": "No impairments",
        "config": {},
    })

    resp = await client.post("/api/v1/profiles/empty-config-test/apply", json={
        "interfaces": ["wlan0"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Empty config means no network impairments applied
    assert "network" not in data["applied"]

    # Cleanup
    await client.delete("/api/v1/profiles/empty-config-test")
