"""EXPERIMENTAL_VIDEO_CAPTURE — FastAPI router for live video streaming.

Routes:
  GET /api/v1/experimental/video/status  — Device health and stream state
  GET /api/v1/experimental/video/stream  — MJPEG video stream
  POST /api/v1/experimental/video/start  — Start streaming
  POST /api/v1/experimental/video/stop   — Stop streaming

All endpoints return 404 if the feature flag is disabled.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...services import feature_flags
from . import device, streamer

logger = logging.getLogger("wifry.experimental.video_capture")

# EXPERIMENTAL_VIDEO_CAPTURE — Router with dedicated prefix
router = APIRouter(
    prefix="/api/v1/experimental/video",
    tags=["experimental-video-capture"],
)

_FLAG_NAME = "experimental_video_capture"


def _check_flag() -> None:
    """EXPERIMENTAL_VIDEO_CAPTURE — Gate all endpoints behind feature flag."""
    if not feature_flags.is_enabled(_FLAG_NAME):
        raise HTTPException(
            status_code=404,
            detail="Experimental video capture is disabled. Enable the 'experimental_video_capture' feature flag.",
        )


@router.get("/status")
async def video_status():
    """EXPERIMENTAL_VIDEO_CAPTURE — Device health and stream state."""
    _check_flag()
    dev = device.get_device_info()
    return {
        "device": dev.to_dict(),
        "streaming": streamer.is_running(),
        "clients": streamer.get_client_count(),
    }


@router.post("/start")
async def start_stream(
    width: int = streamer.DEFAULT_WIDTH,
    height: int = streamer.DEFAULT_HEIGHT,
    fps: int = streamer.DEFAULT_FPS,
    jpeg_quality: int = streamer.DEFAULT_JPEG_QUALITY,
):
    """EXPERIMENTAL_VIDEO_CAPTURE — Start video capture and streaming."""
    _check_flag()

    if streamer.is_running():
        return {"status": "already_running", "message": "Stream is already active."}

    from ...config import settings

    # EXPERIMENTAL_VIDEO_CAPTURE — Discover device (or use mock)
    if settings.mock_mode:
        dev_path = await device.discover_device_mock()
    else:
        dev_path = await device.discover_device()

    if not dev_path:
        await device.update_device_state(device.DeviceState.DISCONNECTED)
        raise HTTPException(
            status_code=503,
            detail="No UVC capture device found. Plug in an Elgato Cam Link 4K or compatible device.",
        )

    await device.update_device_state(
        device.DeviceState.CONNECTED,
        path=dev_path,
        name="UVC Capture Device",
    )

    started = streamer.start_capture(
        device_path=dev_path,
        width=width,
        height=height,
        fps=fps,
        jpeg_quality=jpeg_quality,
        mock_mode=settings.mock_mode,
    )

    if started:
        await device.update_device_state(device.DeviceState.STREAMING, path=dev_path)
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Stream started on %s", dev_path)
        return {"status": "started", "device": dev_path, "resolution": f"{width}x{height}", "fps": fps}
    else:
        return {"status": "already_running", "message": "Capture thread already active."}


@router.post("/stop")
async def stop_stream():
    """EXPERIMENTAL_VIDEO_CAPTURE — Stop video capture and streaming."""
    _check_flag()
    streamer.stop_capture()
    await device.update_device_state(device.DeviceState.CONNECTED)
    logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Stream stopped")
    return {"status": "stopped"}


@router.get("/stream")
async def video_stream():
    """EXPERIMENTAL_VIDEO_CAPTURE — MJPEG stream endpoint for browser <img> tags.

    Usage: <img src="/api/v1/experimental/video/stream" />
    """
    _check_flag()

    if not streamer.is_running():
        raise HTTPException(
            status_code=503,
            detail="Stream is not active. POST /api/v1/experimental/video/start first.",
        )

    return StreamingResponse(
        streamer.mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
