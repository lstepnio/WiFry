"""Captures router — packet capture CRUD + AI analysis."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..models.capture import (
    AnalysisRequest,
    AnalysisResult,
    CaptureInfo,
    StartCaptureRequest,
)
from ..services import ai_analyzer, capture

router = APIRouter(prefix="/api/v1/captures", tags=["captures"])


@router.post("", response_model=CaptureInfo, status_code=201)
async def start_capture(req: StartCaptureRequest):
    """Start a new packet capture. Auto-links to active session."""
    info = await capture.start_capture(req)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.CAPTURE,
        name=f"Capture: {info.name}",
        file_path=info.pcap_path,
        tags=["capture", "pcap"],
        metadata={"capture_id": info.id, "interface": info.interface, "bpf": info.bpf_expression},
    )

    return info


from typing import List

@router.get("", response_model=List[CaptureInfo])
async def list_captures():
    """List all captures."""
    return await capture.list_captures()


@router.get("/{capture_id}", response_model=CaptureInfo)
async def get_capture(capture_id: str):
    """Get capture metadata."""
    info = capture.get_capture(capture_id)
    if not info:
        raise HTTPException(404, f"Capture '{capture_id}' not found")
    return info


@router.post("/{capture_id}/stop", response_model=CaptureInfo)
async def stop_capture(capture_id: str):
    """Stop a running capture."""
    try:
        return await capture.stop_capture(capture_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{capture_id}")
async def delete_capture(capture_id: str):
    """Delete a capture and its files."""
    try:
        await capture.delete_capture(capture_id)
        return {"status": "ok", "capture_id": capture_id}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{capture_id}/download")
async def download_capture(capture_id: str):
    """Download the pcap file."""
    pcap = capture.get_pcap_path(capture_id)
    if not pcap:
        raise HTTPException(404, "Pcap file not found")
    return FileResponse(
        pcap,
        media_type="application/vnd.tcpdump.pcap",
        filename=f"{capture_id}.pcap",
    )


@router.post("/{capture_id}/analyze", response_model=AnalysisResult)
async def analyze_capture(capture_id: str, req: AnalysisRequest):
    """Run AI analysis on a capture."""
    info = capture.get_capture(capture_id)
    if not info:
        raise HTTPException(404, f"Capture '{capture_id}' not found")

    result = await ai_analyzer.analyze_capture(capture_id, req)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.ANALYSIS,
        name=f"AI Analysis: {capture_id}",
        data={"summary": result.summary, "issue_count": len(result.issues), "provider": result.provider},
        tags=["analysis", "ai", result.provider],
        metadata={"capture_id": capture_id},
    )

    return result


@router.get("/{capture_id}/analysis", response_model=AnalysisResult)
async def get_analysis(capture_id: str):
    """Get previous AI analysis results."""
    result = ai_analyzer.get_analysis(capture_id)
    if not result:
        raise HTTPException(404, "No analysis found for this capture")
    return result
