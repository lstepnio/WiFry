"""Regression tests for durable vs ephemeral runtime state."""

import importlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.capture import CaptureFilters, CaptureInfo, CaptureStatus
from app.models.session import ArtifactType, CreateSessionRequest
from app.services import capture, collaboration, runtime_state, session_manager, storage, tunnel


def _clear_path(path: str) -> None:
    target = Path(path)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def reset_runtime_state():
    for path in (
        "/tmp/wifry-captures",
        "/tmp/wifry-sessions",
        "/tmp/wifry-runtime-state",
    ):
        _clear_path(path)

    importlib.reload(storage)
    importlib.reload(runtime_state)
    importlib.reload(session_manager)
    importlib.reload(collaboration)
    importlib.reload(tunnel)
    importlib.reload(capture)

    yield

    for path in (
        "/tmp/wifry-captures",
        "/tmp/wifry-sessions",
        "/tmp/wifry-runtime-state",
    ):
        _clear_path(path)


@pytest.mark.anyio
async def test_active_session_pointer_survives_restart_for_auto_linking():
    created = await session_manager.create_session(CreateSessionRequest(name="Restart Session"))

    reloaded = importlib.reload(session_manager)
    artifact = await reloaded.auto_add_artifact(
        ArtifactType.NOTE,
        "Restart note",
        data={"source": "post-restart"},
    )

    assert reloaded.get_active_session_id() == created.id
    assert artifact is not None
    assert artifact.session_id == created.id


@pytest.mark.anyio
async def test_collaboration_mode_persists_but_live_state_does_not():
    collaboration.set_mode("download")
    await collaboration.broadcast_state_update("Applied remote-access state")

    reloaded = importlib.reload(collaboration)
    status = reloaded.get_status()

    assert status["mode"] == "download"
    assert status["user_count"] == 0
    assert status["shared_state"]["last_action"] is None
    assert status["shared_state"]["nav"] is None


@pytest.mark.anyio
async def test_tunnel_status_resets_after_restart():
    started = await tunnel.start_tunnel()
    assert started["active"] is True

    reloaded = importlib.reload(tunnel)
    status = reloaded.get_status()

    assert status["active"] is False
    assert status["url"] is None
    assert status["started_at"] is None


def test_stale_running_capture_is_reconciled_after_restart():
    captures_dir = storage.ensure_data_path("captures")
    capture_id = "restartcap01"
    metadata_path = captures_dir / f"{capture_id}.json"
    pcap_path = captures_dir / f"{capture_id}.pcap"
    pcap_path.write_bytes(b"")

    info = CaptureInfo(
        id=capture_id,
        name="Interrupted capture",
        interface="wlan0",
        status=CaptureStatus.RUNNING,
        filters=CaptureFilters(),
        started_at=datetime.now(timezone.utc).isoformat(),
        pcap_path=str(pcap_path),
    )
    metadata_path.write_text(info.model_dump_json(indent=2))

    reloaded = importlib.reload(capture)
    reconciled = reloaded.get_capture(capture_id)

    assert reconciled is not None
    assert reconciled.status == CaptureStatus.ERROR
    assert reconciled.stopped_at is not None
    assert reconciled.error is not None
    assert "restart" in reconciled.error.lower() or "interrupted" in reconciled.error.lower()
