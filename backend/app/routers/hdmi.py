"""HDMI capture router — Elgato Cam Link 4K + compatible devices."""

from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

from ..services import hdmi_capture

router = APIRouter(prefix="/api/v1/hdmi", tags=["hdmi"])


@router.get("/devices")
async def detect_devices():
    """Detect connected HDMI capture devices."""
    return await hdmi_capture.detect_devices()


@router.post("/frame")
async def capture_frame(device: str = "/dev/video0", resolution: str = "1920x1080"):
    """Capture HDMI frame, save on RPi. Auto-links to active session."""
    try:
        path = await hdmi_capture.capture_frame(device, resolution)
        size = Path(path).stat().st_size if Path(path).exists() else 0

        from ..services import session_manager
        from ..models.session import ArtifactType
        await session_manager.auto_add_artifact(
            ArtifactType.HDMI_FRAME,
            name=f"HDMI Frame ({resolution})",
            file_path=path,
            tags=["hdmi", "frame", "screenshot"],
            metadata={"device": device, "resolution": resolution},
        )

        return {
            "status": "ok",
            "path": path,
            "filename": Path(path).name,
            "size_bytes": size,
        }
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/record/start")
async def start_recording(
    device: str = "/dev/video0",
    resolution: str = "1920x1080",
    max_duration_secs: int = 300,
):
    """Start recording HDMI input. Auto-links to active session."""
    rec = await hdmi_capture.start_recording(device, resolution, max_duration_secs)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.HDMI_RECORDING,
        name=f"HDMI Recording ({resolution})",
        file_path=rec.get("output", ""),
        tags=["hdmi", "recording", "video"],
        metadata={"device": device, "resolution": resolution, "rec_id": rec.get("id", "")},
    )

    return rec


@router.post("/record/{rec_id}/stop")
async def stop_recording(rec_id: str):
    """Stop a recording."""
    return await hdmi_capture.stop_recording(rec_id)


@router.get("/recordings")
async def list_recordings():
    """List HDMI recordings."""
    return hdmi_capture.list_recordings()


@router.get("/recordings/{rec_id}/download")
async def download_recording(rec_id: str):
    """Download an HDMI recording."""
    recs = hdmi_capture.list_recordings()
    for r in recs:
        if r.get("id") == rec_id:
            path = Path(r.get("output", ""))
            if path.exists():
                return FileResponse(path, filename=path.name, media_type="video/mp4")
    raise HTTPException(404, "Recording not found")


@router.get("/frames")
async def list_frames():
    """List captured HDMI frames."""
    return hdmi_capture.list_frames()


@router.get("/frames/download/{filename}")
async def download_frame(filename: str):
    """Download an HDMI frame."""
    frames = hdmi_capture.list_frames()
    for f in frames:
        if f["filename"] == filename:
            return FileResponse(f["path"], filename=filename, media_type="image/png")
    raise HTTPException(404, "Frame not found")


@router.delete("/frames/{filename}")
async def delete_frame(filename: str):
    """Delete an HDMI frame."""
    frames = hdmi_capture.list_frames()
    for f in frames:
        if f["filename"] == filename:
            Path(f["path"]).unlink(missing_ok=True)
            return {"status": "ok", "filename": filename}
    raise HTTPException(404, "Frame not found")


@router.delete("/recordings/{rec_id}")
async def delete_recording(rec_id: str):
    """Delete an HDMI recording."""
    recs = hdmi_capture.list_recordings()
    for r in recs:
        if r.get("id") == rec_id:
            path = Path(r.get("output", ""))
            if path.exists():
                path.unlink()
            return {"status": "ok", "rec_id": rec_id}
    raise HTTPException(404, "Recording not found")
