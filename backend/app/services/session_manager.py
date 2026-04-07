"""Test session manager.

Manages the lifecycle of test sessions — creation, artifact linking,
impairment logging, and querying. Sessions correlate all artifacts
generated during a testing activity. Session records and the current
auto-link target persist across backend restarts.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.session import (
    ActiveSessionState,
    Artifact,
    ArtifactType,
    CreateSessionRequest,
    DeviceInfo,
    ImpairmentSnapshot,
    SessionStatus,
    SessionSummary,
    TestSession,
)
from . import runtime_state, storage

logger = logging.getLogger(__name__)

_sessions: Dict[str, TestSession] = {}
_artifacts: Dict[str, Artifact] = {}

_active_session_id: Optional[str] = None
_active_session_loaded = False
_lock = asyncio.Lock()
_ACTIVE_SESSION_STATE_KEY = "active-session"


def _ensure_dir() -> Path:
    return storage.ensure_data_path("sessions")


def _save_session(session: TestSession) -> None:
    path = _ensure_dir() / f"{session.id}.json"
    path.write_text(session.model_dump_json(indent=2))


def _save_artifact(artifact: Artifact) -> None:
    d = _ensure_dir() / "artifacts"
    d.mkdir(exist_ok=True)
    path = d / f"{artifact.id}.json"
    path.write_text(artifact.model_dump_json(indent=2))


def _load_all() -> None:
    d = _ensure_dir()
    for f in d.glob("*.json"):
        if f.stem not in _sessions:
            try:
                _sessions[f.stem] = TestSession.model_validate_json(f.read_text())
            except Exception:
                pass

    art_dir = d / "artifacts"
    if art_dir.exists():
        for f in art_dir.glob("*.json"):
            if f.stem not in _artifacts:
                try:
                    _artifacts[f.stem] = Artifact.model_validate_json(f.read_text())
                except Exception:
                    pass


def _load_active_session_state() -> None:
    global _active_session_id, _active_session_loaded

    if _active_session_loaded:
        return

    _active_session_loaded = True
    state = runtime_state.load_model(_ACTIVE_SESSION_STATE_KEY, ActiveSessionState)
    if not state or not state.active_session_id:
        return

    _load_all()
    if state.active_session_id in _sessions:
        _active_session_id = state.active_session_id
        return

    runtime_state.clear(_ACTIVE_SESSION_STATE_KEY)


def _persist_active_session_state(session_id: Optional[str]) -> None:
    global _active_session_id, _active_session_loaded

    _active_session_id = session_id
    _active_session_loaded = True

    if session_id:
        runtime_state.save_model(
            _ACTIVE_SESSION_STATE_KEY,
            ActiveSessionState(active_session_id=session_id),
        )
    else:
        runtime_state.clear(_ACTIVE_SESSION_STATE_KEY)


# --- Session lifecycle ---

async def create_session(req: CreateSessionRequest) -> TestSession:
    """Create a new test session."""
    session_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    device = DeviceInfo()
    if req.device_serial:
        device = await _get_device_info(req.device_serial)

    session = TestSession(
        id=session_id,
        name=req.name,
        description=req.description,
        status=SessionStatus.ACTIVE,
        tags=req.tags,
        device=device,
        network_interface=req.network_interface,
        ap_ssid=settings.ap_ssid,
        ap_channel=settings.ap_channel,
        created_at=now,
        updated_at=now,
    )

    async with _lock:
        _sessions[session_id] = session
    _persist_active_session_state(session_id)
    _save_session(session)

    logger.info("Session created: %s (%s)", session_id, req.name)
    return session


async def complete_session(session_id: str) -> TestSession:
    """Mark a session as completed."""
    clear_active = False

    async with _lock:
        session = _get_session(session_id)
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc).isoformat()
        session.updated_at = session.completed_at

        clear_active = get_active_session_id() == session_id

    if clear_active:
        _persist_active_session_state(None)
    _save_session(session)
    logger.info("Session completed: %s", session_id)
    return session


def get_active_session_id() -> Optional[str]:
    """Get the currently active session ID (for auto-linking)."""
    _load_active_session_state()
    return _active_session_id


async def set_active_session(session_id: Optional[str]) -> None:
    """Set which session is active for auto-linking. Pass None to deactivate."""
    if session_id is not None:
        async with _lock:
            _load_all()
            if session_id not in _sessions:
                raise ValueError(f"Session {session_id} not found")
    _persist_active_session_state(session_id)


# --- Artifact management ---

async def add_artifact(
    session_id: str,
    artifact_type: ArtifactType,
    name: str,
    file_path: Optional[str] = None,
    data: Optional[dict] = None,
    tags: Optional[List[str]] = None,
    description: str = "",
    metadata: Optional[dict] = None,
) -> Artifact:
    """Add an artifact to a session."""
    artifact_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    size = 0
    if file_path:
        try:
            p = Path(file_path)
            if p.exists():
                size = p.stat().st_size
        except (OSError, PermissionError):
            pass
    # Count inline data size if no file
    if size == 0 and data:
        import json as _json
        size = len(_json.dumps(data).encode())

    artifact = Artifact(
        id=artifact_id,
        session_id=session_id,
        type=artifact_type,
        name=name,
        description=description,
        file_path=file_path,
        data=data,
        tags=tags or [],
        created_at=now,
        size_bytes=size,
        metadata=metadata or {},
    )

    async with _lock:
        session = _get_session(session_id)
        _artifacts[artifact_id] = artifact
        session.artifact_ids.append(artifact_id)
        session.artifact_count = len(session.artifact_ids)
        session.total_size_bytes += size
        session.updated_at = now

    _save_artifact(artifact)
    _save_session(session)

    logger.info("Artifact added to session %s: %s (%s)", session_id, name, artifact_type.value)
    return artifact


async def auto_add_artifact(
    artifact_type: ArtifactType,
    name: str,
    **kwargs,
) -> Optional[Artifact]:
    """Add an artifact to the currently active session (if any).

    Call this from other services when they generate output to
    auto-correlate with the active test session.
    """
    active_session_id = get_active_session_id()
    if not active_session_id:
        return None
    return await add_artifact(active_session_id, artifact_type, name, **kwargs)


def log_impairment(
    session_id: str,
    profile_name: str = "",
    network_config: Optional[dict] = None,
    wifi_config: Optional[dict] = None,
    label: str = "",
) -> None:
    """Log an impairment change to a session's timeline."""
    session = _get_session(session_id)
    now = datetime.now(timezone.utc).isoformat()

    snapshot = ImpairmentSnapshot(
        timestamp=now,
        profile_name=profile_name,
        network_config=network_config,
        wifi_config=wifi_config,
        label=label,
    )
    session.impairment_log.append(snapshot)
    session.updated_at = now
    _save_session(session)


def update_session_notes(session_id: str, notes: str) -> TestSession:
    """Update session notes."""
    session = _get_session(session_id)
    session.notes = notes
    session.updated_at = datetime.now(timezone.utc).isoformat()
    _save_session(session)
    return session


def update_session_tags(session_id: str, tags: List[str]) -> TestSession:
    """Update session tags."""
    session = _get_session(session_id)
    session.tags = tags
    session.updated_at = datetime.now(timezone.utc).isoformat()
    _save_session(session)
    return session


# --- Queries ---

def get_session(session_id: str) -> Optional[TestSession]:
    _load_all()
    return _sessions.get(session_id)


def list_sessions(status: Optional[str] = None, tag: Optional[str] = None) -> List[SessionSummary]:
    _load_all()
    sessions = sorted(_sessions.values(), key=lambda s: s.created_at, reverse=True)

    if status:
        sessions = [s for s in sessions if s.status.value == status]
    if tag:
        sessions = [s for s in sessions if tag in s.tags]

    return [
        SessionSummary(
            id=s.id,
            name=s.name,
            status=s.status,
            device_model=s.device.model,
            device_ip=s.device.ip_address,
            tags=s.tags,
            artifact_count=s.artifact_count,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


def get_session_artifacts(session_id: str, artifact_type: Optional[str] = None) -> List[Artifact]:
    """Get all artifacts for a session."""
    _load_all()
    session = _sessions.get(session_id)
    if not session:
        return []

    artifacts = [_artifacts[aid] for aid in session.artifact_ids if aid in _artifacts]

    if artifact_type:
        artifacts = [a for a in artifacts if a.type.value == artifact_type]

    return sorted(artifacts, key=lambda a: a.created_at, reverse=True)


async def delete_session(session_id: str, discard_data: bool = False) -> dict:
    """Delete a session and its metadata.

    If discard_data=True, also delete the actual artifact files
    (pcaps, screenshots, reports, etc.) — not just the metadata.
    """
    async with _lock:
        session = _sessions.pop(session_id, None)
        if not session:
            return {"deleted": 0}

        clear_active = get_active_session_id() == session_id

        artifact_ids = list(session.artifact_ids)
        artifacts_to_clean = []
        for aid in artifact_ids:
            art = _artifacts.pop(aid, None)
            if art:
                artifacts_to_clean.append((aid, art))

    if clear_active:
        _persist_active_session_state(None)

    files_deleted = 0
    for aid, art in artifacts_to_clean:
        # Remove artifact metadata
        art_path = _ensure_dir() / "artifacts" / f"{aid}.json"
        art_path.unlink(missing_ok=True)
        files_deleted += 1

        # Remove actual data file if discarding
        if discard_data and art.file_path:
            fp = Path(art.file_path)
            if fp.exists():
                fp.unlink(missing_ok=True)
                logger.info("Discarded artifact file: %s", fp)

    # Remove session file
    (_ensure_dir() / f"{session_id}.json").unlink(missing_ok=True)

    logger.info("Session %s deleted (discard_data=%s, artifacts=%d)", session_id, discard_data, files_deleted)
    return {"deleted": files_deleted, "discarded_data": discard_data}


# --- Helpers ---

def _get_session(session_id: str) -> TestSession:
    _load_all()
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    return session


async def _get_device_info(serial: str) -> DeviceInfo:
    """Fetch device info from ADB."""
    try:
        from . import adb_manager
        devices = await adb_manager.list_devices()
        for d in devices:
            if d.serial == serial:
                return DeviceInfo(
                    serial=d.serial,
                    model=d.model,
                    manufacturer=d.manufacturer,
                    android_version=d.android_version,
                    ip_address=serial.split(":")[0] if ":" in serial else "",
                )
    except Exception:
        pass
    return DeviceInfo(serial=serial)
