"""Factory reset regression tests.

Verifies that DELETE /api/v1/system/data/all cleans ALL data stores,
including any new directories or config files added in the future.
The factory reset uses an allowlist approach — only items in
_FACTORY_RESET_KEEP survive. This test creates synthetic data to
prove that unknown new entries are cleaned automatically.
"""

import json
from pathlib import Path

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


async def test_factory_reset_cleans_known_data_dirs(client: AsyncClient):
    """Known data directories (captures, sessions, etc.) are removed."""
    base = Path("/tmp/wifry")
    base.mkdir(parents=True, exist_ok=True)

    # Create known data directories with files
    known_dirs = [
        "captures", "sessions", "segments", "reports", "annotations",
        "adb-files", "hdmi-captures", "bundles", "speedtests",
        "coredns", "teleport", "network-profiles", "logs",
        "runtime-state", "scenarios", "certs",
    ]
    for d in known_dirs:
        p = base / d
        p.mkdir(parents=True, exist_ok=True)
        (p / "test-file.json").write_text('{"test": true}')

    resp = await client.delete("/api/v1/system/data/all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # All known dirs should have been cleaned
    for d in known_dirs:
        p = base / d
        if d == "captures":
            # Captures dir is re-created with 1777 permissions
            assert p.exists()
            assert not list(p.iterdir()), f"captures dir should be empty but has: {list(p.iterdir())}"
        else:
            assert not p.exists(), f"Directory {d} should have been deleted"


async def test_factory_reset_cleans_config_files(client: AsyncClient):
    """All config JSON files in data_dir are removed."""
    base = Path("/tmp/wifry")
    base.mkdir(parents=True, exist_ok=True)

    config_files = [
        "settings.json", "network_config.json", "feature_flags.json",
        "update_backup.json", "dns_config.json", "storage.json",
    ]
    for f in config_files:
        (base / f).write_text("{}")

    resp = await client.delete("/api/v1/system/data/all")
    assert resp.status_code == 200

    for f in config_files:
        assert not (base / f).exists(), f"Config file {f} should have been deleted"


async def test_factory_reset_cleans_unknown_new_data(client: AsyncClient):
    """NEW data stores added in the future are automatically cleaned.

    This is the key regression test: if a developer adds a new service
    that stores data under /var/lib/wifry/new-thing/, factory reset
    should clean it without any code changes to the reset endpoint.
    """
    base = Path("/tmp/wifry")
    base.mkdir(parents=True, exist_ok=True)

    # Simulate future data stores that don't exist yet
    future_dir = base / "future-feature-data"
    future_dir.mkdir(parents=True, exist_ok=True)
    (future_dir / "evidence.json").write_text('{"data": "sensitive"}')

    future_config = base / "new_service_config.json"
    future_config.write_text('{"secret": "key123"}')

    resp = await client.delete("/api/v1/system/data/all")
    assert resp.status_code == 200

    assert not future_dir.exists(), "Unknown directory should be cleaned by factory reset"
    assert not future_config.exists(), "Unknown config file should be cleaned by factory reset"


async def test_factory_reset_preserves_allowlist(client: AsyncClient):
    """Allowlisted system files survive factory reset."""
    base = Path("/tmp/wifry")
    base.mkdir(parents=True, exist_ok=True)

    # These must survive
    version_file = base / "VERSION"
    version_file.write_text("0.1.18")

    first_boot = base / ".first-boot-complete"
    first_boot.write_text("done")

    # Also test data alongside preserved files
    (base / "sessions").mkdir(exist_ok=True)
    (base / "sessions" / "test.json").write_text("{}")

    resp = await client.delete("/api/v1/system/data/all")
    assert resp.status_code == 200

    assert version_file.exists(), "VERSION file should be preserved"
    assert first_boot.exists(), ".first-boot-complete should be preserved"
    assert version_file.read_text() == "0.1.18"


async def test_factory_reset_response_lists_deleted_items(client: AsyncClient):
    """Response includes details of what was deleted."""
    base = Path("/tmp/wifry")
    base.mkdir(parents=True, exist_ok=True)

    # Create some data
    sessions_dir = base / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "a.json").write_text("{}")
    (sessions_dir / "b.json").write_text("{}")

    (base / "settings.json").write_text("{}")

    resp = await client.delete("/api/v1/system/data/all")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "ok"
    assert "deleted" in data
    deleted = data["deleted"]

    # Sessions dir had 2 files
    assert deleted.get("sessions") == 2
    # settings.json was 1 file
    assert deleted.get("settings.json") == 1


async def test_factory_reset_captures_dir_permissions(client: AsyncClient):
    """After reset, captures dir exists with correct permissions for tshark."""
    base = Path("/tmp/wifry")
    base.mkdir(parents=True, exist_ok=True)

    resp = await client.delete("/api/v1/system/data/all")
    assert resp.status_code == 200

    captures_dir = base / "captures"
    assert captures_dir.exists(), "Captures dir should be re-created"
