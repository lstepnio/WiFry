"""mitmproxy addon for intercepting HLS/DASH streams.

This script runs inside mitmproxy (mitmdump -s stream_tap.py) and sends
stream events to the WiFry backend via localhost HTTP.

Events:
  - manifest: HLS M3U8 or DASH MPD response
  - segment:  media segment (.ts, .m4s) response
  - error:    HTTP error for streaming URLs
"""

import json
import logging
import time
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger("wifry.stream_tap")

WIFRY_BACKEND = "http://127.0.0.1:8080/api/v1/internal/stream-event"

# Content types and extensions for detection
MANIFEST_TYPES = {"application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml"}
MANIFEST_EXTENSIONS = {".m3u8", ".m3u", ".mpd"}
SEGMENT_TYPES = {"video/mp2t", "video/mp4", "application/octet-stream"}
SEGMENT_EXTENSIONS = {".ts", ".m4s", ".m4v", ".m4a", ".fmp4"}


def _get_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in MANIFEST_EXTENSIONS | SEGMENT_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ""


def _is_manifest(url: str, content_type: str) -> bool:
    ct = content_type.lower().split(";")[0].strip()
    if ct in MANIFEST_TYPES:
        return True
    return _get_extension(url) in MANIFEST_EXTENSIONS


def _is_segment(url: str, content_type: str) -> bool:
    ct = content_type.lower().split(";")[0].strip()
    if ct in SEGMENT_TYPES:
        ext = _get_extension(url)
        # octet-stream only counts if the extension matches
        if ct == "application/octet-stream":
            return ext in SEGMENT_EXTENSIONS
        return True
    return _get_extension(url) in SEGMENT_EXTENSIONS


def _send_event(event: dict) -> None:
    """Send event to WiFry backend. Fire-and-forget."""
    if requests is None:
        logger.warning("requests library not available, cannot send event")
        return
    try:
        requests.post(WIFRY_BACKEND, json=event, timeout=2)
    except Exception as e:
        logger.debug("Failed to send event: %s", e)


class StreamTap:
    """mitmproxy addon that taps ABR streaming traffic."""

    def __init__(self):
        self._request_start: dict = {}  # flow.id -> start_time

    def request(self, flow):
        """Record request start time for download duration measurement."""
        self._request_start[flow.id] = time.monotonic()

    def response(self, flow):
        """Inspect HTTP responses for manifests and segments."""
        url = flow.request.pretty_url
        content_type = flow.response.headers.get("content-type", "")
        status_code = flow.response.status_code
        client_ip = flow.client_conn.peername[0] if flow.client_conn.peername else ""

        # Calculate download time
        start = self._request_start.pop(flow.id, None)
        request_time = time.monotonic() - start if start else 0

        if _is_manifest(url, content_type):
            body = flow.response.get_text(strict=False) or ""
            _send_event({
                "event_type": "manifest",
                "client_ip": client_ip,
                "url": url,
                "content_type": content_type,
                "status_code": status_code,
                "request_time_secs": round(request_time, 3),
                "response_size_bytes": len(flow.response.raw_content),
                "body": body,
            })

        elif _is_segment(url, content_type):
            _send_event({
                "event_type": "segment",
                "client_ip": client_ip,
                "url": url,
                "content_type": content_type,
                "status_code": status_code,
                "request_time_secs": round(request_time, 3),
                "response_size_bytes": len(flow.response.raw_content),
            })

        elif status_code >= 400 and (_get_extension(url) in MANIFEST_EXTENSIONS | SEGMENT_EXTENSIONS):
            _send_event({
                "event_type": "error",
                "client_ip": client_ip,
                "url": url,
                "status_code": status_code,
                "request_time_secs": round(request_time, 3),
            })


addons = [StreamTap()]
