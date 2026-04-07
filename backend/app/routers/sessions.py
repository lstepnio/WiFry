"""Sessions router — test session management, artifacts, and support bundles."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel, Field

from ..models.session import (
    ActiveSessionResponse,
    Artifact,
    ArtifactType,
    CreateSessionRequest,
    SessionSummary,
    SupportBundle,
    TestSession,
)
from ..services import audit_log, session_manager, bundle_generator, fileio

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


# --- Session CRUD ---

@router.get("", response_model=List[SessionSummary])
async def list_sessions(
    status: Optional[str] = None,
    tag: Optional[str] = None,
):
    """List all test sessions."""
    return session_manager.list_sessions(status, tag)


@router.post("/delete-all")
async def delete_all_sessions(discard_data: bool = False):
    """Delete all sessions. With discard_data=true, also deletes all artifact files."""
    sessions = session_manager.list_sessions()
    deleted = 0
    for s in sessions:
        await session_manager.delete_session(s.id, discard_data)
        deleted += 1
    return {"status": "ok", "deleted": deleted, "discarded_data": discard_data}


@router.post("", response_model=TestSession, status_code=201)
async def create_session(req: CreateSessionRequest):
    """Create a new test session."""
    return await session_manager.create_session(req)


@router.get("/active", response_model=ActiveSessionResponse)
async def get_active_session():
    """Get the currently active session (for auto-linking)."""
    sid = session_manager.get_active_session_id()
    if not sid:
        return {"active_session_id": None}
    session = session_manager.get_session(sid)
    return {"active_session_id": sid, "session_name": session.name if session else None}


@router.post("/{session_id}/activate")
async def set_active_session(session_id: str):
    """Set a session as the active session for auto-linking."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found")
    await session_manager.set_active_session(session_id)
    return {"status": "ok", "active_session_id": session_id}


@router.post("/deactivate")
async def deactivate_session():
    """Stop recording — deactivate the current session without completing it."""
    await session_manager.set_active_session(None)
    return {"status": "ok", "active_session_id": None}


@router.get("/{session_id}", response_model=TestSession)
async def get_session(session_id: str):
    """Get full session detail."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return session


@router.post("/{session_id}/complete", response_model=TestSession)
async def complete_session(session_id: str):
    """Mark a session as completed."""
    try:
        return await session_manager.complete_session(session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{session_id}")
async def delete_session(session_id: str, discard_data: bool = False):
    """Delete a session. With discard_data=true, also deletes artifact files (pcaps, screenshots, etc.)."""
    result = await session_manager.delete_session(session_id, discard_data)
    return {"status": "ok", **result}


@router.post("/{session_id}/discard")
async def discard_session(session_id: str):
    """Discard a session and ALL its data files. Cannot be undone."""
    result = await session_manager.delete_session(session_id, discard_data=True)
    return {"status": "ok", "message": "Session and all data discarded", **result}


# --- Session metadata ---

class UpdateNotesRequest(BaseModel):
    notes: str


class UpdateTagsRequest(BaseModel):
    tags: List[str]


@router.put("/{session_id}/notes", response_model=TestSession)
async def update_notes(session_id: str, req: UpdateNotesRequest):
    """Update session notes."""
    try:
        return session_manager.update_session_notes(session_id, req.notes)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/{session_id}/tags", response_model=TestSession)
async def update_tags(session_id: str, req: UpdateTagsRequest):
    """Update session tags."""
    try:
        return session_manager.update_session_tags(session_id, req.tags)
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- Artifacts ---

@router.get("/{session_id}/artifacts", response_model=List[Artifact])
async def get_artifacts(
    session_id: str,
    type: Optional[str] = None,
):
    """Get all artifacts for a session, optionally filtered by type."""
    return session_manager.get_session_artifacts(session_id, type)


class AddArtifactRequest(BaseModel):
    type: str = Field(..., description="Artifact type")
    name: str
    description: str = ""
    file_path: Optional[str] = None
    data: Optional[dict] = None
    tags: List[str] = Field(default_factory=list)


@router.post("/{session_id}/artifacts", response_model=Artifact, status_code=201)
async def add_artifact(session_id: str, req: AddArtifactRequest):
    """Manually add an artifact to a session."""
    try:
        return await session_manager.add_artifact(
            session_id,
            ArtifactType(req.type),
            req.name,
            file_path=req.file_path,
            data=req.data,
            tags=req.tags,
            description=req.description,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# --- Support Bundles ---

@router.post("/{session_id}/bundle", response_model=SupportBundle)
async def generate_bundle(session_id: str):
    """Generate a support bundle zip for a session."""
    try:
        return await bundle_generator.generate_bundle(session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{session_id}/bundle/share")
async def generate_and_share_bundle(session_id: str, expires: str = "15m"):
    """Generate a bundle and upload to file.io in one step."""
    try:
        bundle = await bundle_generator.generate_bundle(session_id)
        upload = await fileio.upload_file(bundle.bundle_path, expires)
        audit_log.record_event(
            "session.bundle.share",
            resource_type="session",
            resource_id=session_id,
            details={
                "bundle_name": Path(bundle.bundle_path).name,
                "expires": expires,
                "upload_success": upload.get("success", False),
            },
        )
        return {
            "bundle": bundle.model_dump(),
            "upload": upload,
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{session_id}/bundle/download")
async def download_bundle(session_id: str):
    """Download the most recent bundle for a session."""
    bundles = bundle_generator.list_bundles()
    for b in bundles:
        if session_id in b["filename"]:
            return FileResponse(b["path"], filename=b["filename"], media_type="application/zip")
    raise HTTPException(404, "No bundle found. Generate one first.")


@router.get("/bundles/list")
async def list_all_bundles():
    """List all generated bundles."""
    return bundle_generator.list_bundles()
