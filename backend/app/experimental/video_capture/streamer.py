"""EXPERIMENTAL_VIDEO_CAPTURE — MJPEG-over-HTTP video streamer.

Opens a UVC capture device via OpenCV, reads frames, encodes as JPEG,
and yields them as a multipart MJPEG stream. The streamer runs in a
background thread to avoid blocking the async event loop.

CPU/memory bounded:
- Single capture at configurable resolution (default 1280x720)
- Frame rate capped (default 15 fps)
- JPEG quality tunable (default 70)
- Only one active stream reader drives capture; additional clients
  receive the same shared frame via a broadcast pattern.
"""

import asyncio
import logging
import threading
import time
from typing import AsyncGenerator, Optional

logger = logging.getLogger("wifry.experimental.video_capture")

# EXPERIMENTAL_VIDEO_CAPTURE — Stream configuration defaults
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 15
DEFAULT_JPEG_QUALITY = 70

_capture_lock = threading.Lock()
_frame_lock = threading.Lock()
_latest_frame: Optional[bytes] = None
_running = False
_capture_thread: Optional[threading.Thread] = None
_client_count = 0
_client_lock = threading.Lock()


def _capture_loop(
    device_path: str,
    width: int,
    height: int,
    fps: int,
    jpeg_quality: int,
    mock_mode: bool,
) -> None:
    """EXPERIMENTAL_VIDEO_CAPTURE — Background thread: read frames from device."""
    global _latest_frame, _running

    if mock_mode:
        _mock_capture_loop(fps)
        return

    try:
        import cv2
    except ImportError:
        logger.error("[EXPERIMENTAL_VIDEO_CAPTURE] opencv-python not installed — cannot stream")
        _running = False
        return

    logger.info(
        "[EXPERIMENTAL_VIDEO_CAPTURE] Starting capture: %s @ %dx%d %dfps q%d",
        device_path, width, height, fps, jpeg_quality,
    )

    cap = None
    frame_interval = 1.0 / max(fps, 1)

    try:
        cap = cv2.VideoCapture(device_path)
        if not cap.isOpened():
            logger.error("[EXPERIMENTAL_VIDEO_CAPTURE] Failed to open device: %s", device_path)
            _running = False
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)

        encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]

        while _running:
            t_start = time.monotonic()
            ret, frame = cap.read()
            if not ret:
                logger.warning("[EXPERIMENTAL_VIDEO_CAPTURE] Frame read failed — device may have disconnected")
                break

            ok, encoded = cv2.imencode(".jpg", frame, encode_params)
            if ok:
                with _frame_lock:
                    _latest_frame = encoded.tobytes()

            elapsed = time.monotonic() - t_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    except Exception:
        logger.exception("[EXPERIMENTAL_VIDEO_CAPTURE] Capture loop error")
    finally:
        if cap is not None:
            cap.release()
        _running = False
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Capture loop stopped")


def _mock_capture_loop(fps: int) -> None:
    """EXPERIMENTAL_VIDEO_CAPTURE — Generate a synthetic test pattern in mock mode."""
    global _latest_frame, _running

    frame_interval = 1.0 / max(fps, 1)
    frame_count = 0

    try:
        import cv2
        import numpy as np

        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Mock capture loop starting (with OpenCV)")
        while _running:
            # Gray frame with frame counter text
            img = np.zeros((DEFAULT_HEIGHT, DEFAULT_WIDTH, 3), dtype=np.uint8)
            img[:] = (48, 48, 48)
            cv2.putText(
                img,
                f"EXPERIMENTAL_VIDEO_CAPTURE mock frame {frame_count}",
                (50, DEFAULT_HEIGHT // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2,
            )
            _, encoded = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            with _frame_lock:
                _latest_frame = encoded.tobytes()
            frame_count += 1
            time.sleep(frame_interval)
    except ImportError:
        # No OpenCV — generate a minimal valid JPEG placeholder
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Mock capture loop starting (no OpenCV, static JPEG)")
        # Smallest valid JPEG: 1x1 pixel black
        _TINY_JPEG = (
            b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
            b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
            b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
            b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342'
            b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
            b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b'
            b'\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04'
            b'\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa'
            b'\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n'
            b'\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz'
            b'\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99'
            b'\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7'
            b'\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5'
            b'\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1'
            b'\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa'
            b'\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7\xa3\xa0\xa0\x02\x80'
            b'\xff\xd9'
        )
        with _frame_lock:
            _latest_frame = _TINY_JPEG
        while _running:
            time.sleep(1.0 / max(fps, 1))
    finally:
        _running = False
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Mock capture loop stopped")


def start_capture(
    device_path: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    mock_mode: bool = False,
) -> bool:
    """EXPERIMENTAL_VIDEO_CAPTURE — Start the background capture thread.

    Returns True if started, False if already running.
    """
    global _running, _capture_thread

    with _capture_lock:
        if _running and _capture_thread and _capture_thread.is_alive():
            return False

        _running = True
        _capture_thread = threading.Thread(
            target=_capture_loop,
            args=(device_path, width, height, fps, jpeg_quality, mock_mode),
            daemon=True,
            name="exp-video-capture",
        )
        _capture_thread.start()
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Capture thread started")
        return True


def stop_capture() -> None:
    """EXPERIMENTAL_VIDEO_CAPTURE — Stop the background capture thread."""
    global _running, _latest_frame

    _running = False
    if _capture_thread and _capture_thread.is_alive():
        _capture_thread.join(timeout=5.0)
    with _frame_lock:
        _latest_frame = None
    logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Capture stopped")


def is_running() -> bool:
    return _running and _capture_thread is not None and _capture_thread.is_alive()


def get_latest_frame() -> bytes | None:
    """EXPERIMENTAL_VIDEO_CAPTURE — Return a copy of the latest JPEG frame, or None."""
    with _frame_lock:
        return bytes(_latest_frame) if _latest_frame is not None else None


async def mjpeg_frames() -> AsyncGenerator[bytes, None]:
    """EXPERIMENTAL_VIDEO_CAPTURE — Yield MJPEG multipart frames for HTTP streaming."""
    global _client_count

    with _client_lock:
        _client_count += 1
    logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Stream client connected (total: %d)", _client_count)

    try:
        while _running:
            with _frame_lock:
                frame = _latest_frame
            if frame is None:
                await asyncio.sleep(0.1)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )
            await asyncio.sleep(1.0 / DEFAULT_FPS)
    finally:
        with _client_lock:
            _client_count -= 1
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Stream client disconnected (total: %d)", _client_count)


def get_client_count() -> int:
    with _client_lock:
        return _client_count
