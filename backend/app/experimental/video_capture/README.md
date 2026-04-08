# EXPERIMENTAL_VIDEO_CAPTURE

Live MJPEG video streaming from a UVC HDMI capture device (e.g. Elgato Cam Link 4K).

**Status:** Experimental — disabled by default, may be removed in a future release.

## Purpose

Stream live HDMI video output from an STB to the browser for visual monitoring
during network impairment testing. V1 is limited to live browser streaming only —
no recording, OCR, AI analysis, or audio processing.

## Feature Flag

- Flag name: `experimental_video_capture`
- Default: **disabled**
- Enable via: `PUT /api/v1/system/features/experimental_video_capture?enabled=true`
- All API endpoints return 404 when the flag is disabled.

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/experimental/video/status` | Device health and stream state |
| POST | `/api/v1/experimental/video/start` | Start capture and streaming |
| POST | `/api/v1/experimental/video/stop` | Stop capture and streaming |
| GET | `/api/v1/experimental/video/stream` | MJPEG stream (`<img src="...">`) |

## Dependencies

- **Hardware:** Elgato Cam Link 4K or any UVC-compatible USB capture device
- **System:** `v4l-utils` (installed by `setup/install.sh`)
- **Python:** `opencv-python` (optional — mock mode works without it)

To install OpenCV on the RPi:
```bash
sudo /opt/wifry/venv/bin/pip install opencv-python-headless
```

## Architecture

```
backend/app/experimental/video_capture/
  __init__.py      # Package marker with module docstring
  device.py        # UVC device discovery, health tracking, reconnection
  streamer.py      # MJPEG capture thread + async frame generator
  router.py        # FastAPI endpoints (flag-gated)
  README.md        # This file
```

- `device.py` discovers devices by scanning `/sys/class/video4linux/` and
  matching against known capture device names (not device paths), so it
  tolerates USB disconnect/reconnect and device index changes.
- `streamer.py` runs capture in a daemon thread. A shared frame buffer
  serves all connected MJPEG clients. Frame rate and JPEG quality are
  configurable via the `/start` endpoint.
- `router.py` gates every endpoint behind the `experimental_video_capture`
  feature flag. When disabled, endpoints return 404.

## Frontend

- Component: `frontend/src/components/ExperimentalVideoStream.tsx`
- Appears in: System > Tools tab (only when flag is enabled)
- Shows device status, start/stop controls, and the live MJPEG feed

## How to Remove This Module

1. Delete `backend/app/experimental/video_capture/` (this directory)
2. Delete `backend/app/experimental/__init__.py` (if no other experimental modules remain)
3. In `backend/app/main.py`: remove the `EXPERIMENTAL_VIDEO_CAPTURE` try/except router block (~5 lines)
4. In `backend/app/main.py` lifespan shutdown: remove the `EXPERIMENTAL_VIDEO_CAPTURE` streamer cleanup block (~5 lines)
5. In `backend/app/services/feature_flags.py`: remove the `experimental_video_capture` entry from `DEFAULTS`
6. Delete `frontend/src/components/ExperimentalVideoStream.tsx`
7. In `frontend/src/components/dashboard/DashboardPanels.tsx`: remove the import and the `{isEnabled('experimental_video_capture') && ...}` line
8. In `frontend/src/api/client.ts`: remove the three `EXPERIMENTAL_VIDEO_CAPTURE` functions
9. In `frontend/src/hooks/useFeatureFlags.ts`: remove `experimental_video_capture` from `FALLBACK_ENABLED`
10. Search for `EXPERIMENTAL_VIDEO_CAPTURE` across the codebase to confirm nothing remains

## Non-v1 TODOs (explicitly out of scope for this PR)

- Device reconnection background task with exponential backoff
- Recording to disk with retention policy
- Resolution/framerate auto-negotiation from device capabilities
- Audio passthrough
- Frame snapshot endpoint (single JPEG capture)
- OCR / text extraction from video frames
- AI-powered visual analysis
- Integration with session artifacts
- WebRTC streaming for lower latency
- Multiple simultaneous device support
