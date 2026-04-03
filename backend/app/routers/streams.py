"""Streams + proxy router — stream monitoring and proxy control."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from ..models.stream import (
    ProxySettings,
    ProxyStatus,
    SegmentInfo,
    StreamEvent,
    StreamSession,
    StreamSessionSummary,
)
from ..services import proxy_manager, stream_monitor

router = APIRouter(tags=["streams"])


# --- Stream monitoring ---

@router.get("/api/v1/streams", response_model=List[StreamSessionSummary])
async def list_streams():
    """List active and recent stream sessions."""
    if settings.mock_mode:
        return stream_monitor.get_mock_sessions()
    return stream_monitor.get_sessions()


@router.get("/api/v1/streams/{session_id}", response_model=StreamSession)
async def get_stream(session_id: str):
    """Get full stream session detail."""
    if settings.mock_mode:
        return stream_monitor.get_mock_session_detail()

    session = stream_monitor.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Stream session '{session_id}' not found")
    return session


@router.get("/api/v1/streams/{session_id}/segments", response_model=List[SegmentInfo])
async def get_stream_segments(session_id: str):
    """Get segment history for a stream session."""
    segments = stream_monitor.get_session_segments(session_id)
    if not segments and not settings.mock_mode:
        raise HTTPException(404, "No segments found for this session")
    return segments


# --- Internal endpoint (mitmproxy addon → backend) ---

@router.post("/api/v1/internal/stream-event")
async def receive_stream_event(event: StreamEvent):
    """Receive a stream event from the mitmproxy addon."""
    proxy_manager.increment_flow_count()
    session_id = stream_monitor.process_event(event)
    return {"status": "ok", "session_id": session_id}


# --- Proxy control ---

@router.get("/api/v1/proxy/status", response_model=ProxyStatus)
async def get_proxy_status():
    """Get current proxy status."""
    return proxy_manager.get_status()


@router.post("/api/v1/proxy/enable", response_model=ProxyStatus)
async def enable_proxy():
    """Enable transparent HTTPS proxy."""
    return await proxy_manager.enable_proxy()


@router.post("/api/v1/proxy/disable", response_model=ProxyStatus)
async def disable_proxy():
    """Disable transparent HTTPS proxy."""
    return await proxy_manager.disable_proxy()


@router.get("/api/v1/proxy/cert")
async def download_cert():
    """Download the mitmproxy CA certificate for installation on STBs."""
    cert = proxy_manager.get_cert_path()
    if not cert:
        raise HTTPException(
            404,
            "CA certificate not found. Enable the proxy first to generate it.",
        )
    return FileResponse(cert, filename="wifry-ca-cert.pem", media_type="application/x-pem-file")


@router.put("/api/v1/proxy/settings", response_model=ProxyStatus)
async def update_proxy_settings(new_settings: ProxySettings):
    """Update proxy settings (segment saving, storage limit)."""
    return proxy_manager.update_settings(new_settings)
