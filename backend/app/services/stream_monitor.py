"""Real-time ABR stream monitoring.

Tracks active HLS/DASH stream sessions, computes metrics (throughput,
buffer health, bitrate switches), and provides data for the UI.
"""

import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models.stream import (
    BitrateSwitch,
    SegmentInfo,
    StreamEvent,
    StreamSession,
    StreamSessionSummary,
    StreamType,
    VariantInfo,
)
from . import hls_parser, dash_parser

logger = logging.getLogger(__name__)

# In-memory registry of stream sessions
_sessions: Dict[str, StreamSession] = {}

# Map client_ip + master_url -> session_id for dedup
_session_index: Dict[str, str] = {}

# Max segments to keep per session (rolling window)
MAX_SEGMENTS = 200


def process_event(event: StreamEvent) -> Optional[str]:
    """Process a stream event from the mitmproxy addon.

    Returns the session ID if the event was matched to a session.
    """
    if event.event_type == "manifest":
        return _handle_manifest(event)
    elif event.event_type == "segment":
        return _handle_segment(event)
    elif event.event_type == "error":
        return _handle_error(event)
    return None


def _handle_manifest(event: StreamEvent) -> Optional[str]:
    """Handle a manifest event (M3U8 or MPD)."""
    if not event.body:
        return None

    url = event.url
    client_ip = event.client_ip

    # Detect HLS vs DASH
    if hls_parser.detect_hls(url, event.content_type):
        return _handle_hls_manifest(event)
    elif dash_parser.detect_dash(url, event.content_type):
        return _handle_dash_manifest(event)

    return None


def _handle_hls_manifest(event: StreamEvent) -> Optional[str]:
    """Handle an HLS M3U8 manifest."""
    url = event.url
    body = event.body or ""

    if hls_parser.is_master_playlist(body):
        # Master playlist: create or update session
        master = hls_parser.parse_master(body, base_url=url)
        session = _get_or_create_session(event.client_ip, url, StreamType.HLS)

        session.variants = [
            VariantInfo(
                bandwidth=v.bandwidth,
                resolution=v.resolution,
                codecs=v.codecs,
                url=v.uri,
                frame_rate=v.frame_rate,
            )
            for v in master.variants
        ]

        if session.variants and not session.active_variant:
            session.active_variant = session.variants[0]  # assume highest initially

        logger.info(
            "HLS master playlist for %s: %d variants (max %d bps)",
            event.client_ip, len(session.variants),
            session.variants[0].bandwidth if session.variants else 0,
        )
        return session.id

    else:
        # Media playlist: find the session and detect active variant
        session = _find_session_by_client(event.client_ip)
        if session:
            # Try to match which variant this media playlist belongs to
            for variant in session.variants:
                if variant.url and variant.url in url:
                    if session.active_variant and session.active_variant.bandwidth != variant.bandwidth:
                        # Bitrate switch detected
                        switch = BitrateSwitch(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            from_bandwidth=session.active_variant.bandwidth,
                            to_bandwidth=variant.bandwidth,
                            from_resolution=session.active_variant.resolution,
                            to_resolution=variant.resolution,
                        )
                        session.bitrate_switches_log.append(switch)
                        session.bitrate_switches += 1
                        logger.info(
                            "Bitrate switch for %s: %d -> %d bps",
                            event.client_ip, switch.from_bandwidth, switch.to_bandwidth,
                        )
                    session.active_variant = variant
                    break

            return session.id

    return None


def _handle_dash_manifest(event: StreamEvent) -> Optional[str]:
    """Handle a DASH MPD manifest."""
    url = event.url
    body = event.body or ""

    manifest = dash_parser.parse_mpd(body, base_url=url)
    session = _get_or_create_session(event.client_ip, url, StreamType.DASH)

    video_reps = manifest.video_representations
    session.variants = [
        VariantInfo(
            bandwidth=r.bandwidth,
            resolution=r.resolution,
            codecs=r.codecs,
            url="",
            frame_rate=r.frame_rate,
        )
        for r in video_reps
    ]

    if session.variants and not session.active_variant:
        session.active_variant = session.variants[0]

    logger.info(
        "DASH manifest for %s: %d video representations (max %d bps)",
        event.client_ip, len(video_reps),
        video_reps[0].bandwidth if video_reps else 0,
    )
    return session.id


def _handle_segment(event: StreamEvent) -> Optional[str]:
    """Handle a segment download event."""
    session = _find_session_by_client(event.client_ip)
    if not session:
        return None

    throughput_bps = 0
    if event.request_time_secs > 0:
        throughput_bps = int((event.response_size_bytes * 8) / event.request_time_secs)

    segment = SegmentInfo(
        url=event.url,
        sequence=session.total_segments,
        duration_secs=0,  # filled from manifest if available
        download_time_secs=event.request_time_secs,
        size_bytes=event.response_size_bytes,
        bitrate_bps=session.active_variant.bandwidth if session.active_variant else 0,
        throughput_bps=throughput_bps,
        timestamp=datetime.now(timezone.utc).isoformat(),
        status_code=event.status_code,
    )

    # Try to estimate segment duration from manifest target duration
    # (actual duration comes from M3U8 EXTINF, but we approximate)
    if session.variants and session.active_variant:
        # Approximate: most segments are ~6s for HLS, varies for DASH
        segment.duration_secs = 6.0  # default estimate

    session.segments.append(segment)
    if len(session.segments) > MAX_SEGMENTS:
        session.segments = session.segments[-MAX_SEGMENTS:]

    session.total_segments += 1
    session.last_activity = segment.timestamp

    if event.status_code >= 400:
        session.segment_errors += 1

    # Update metrics
    _update_metrics(session)

    return session.id


def _handle_error(event: StreamEvent) -> Optional[str]:
    """Handle an error event (e.g. 404 segment)."""
    session = _find_session_by_client(event.client_ip)
    if session:
        session.segment_errors += 1
        return session.id
    return None


def _get_or_create_session(
    client_ip: str, master_url: str, stream_type: StreamType
) -> StreamSession:
    """Get existing or create new stream session."""
    key = f"{client_ip}:{master_url}"
    if key in _session_index:
        sid = _session_index[key]
        if sid in _sessions:
            session = _sessions[sid]
            session.last_activity = datetime.now(timezone.utc).isoformat()
            return session

    sid = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    session = StreamSession(
        id=sid,
        stream_type=stream_type,
        client_ip=client_ip,
        master_url=master_url,
        started_at=now,
        last_activity=now,
    )
    _sessions[sid] = session
    _session_index[key] = sid
    return session


def _find_session_by_client(client_ip: str) -> Optional[StreamSession]:
    """Find the most recent active session for a client IP."""
    best = None
    for session in _sessions.values():
        if session.client_ip == client_ip and session.active:
            if best is None or session.last_activity > best.last_activity:
                best = session
    return best


def _update_metrics(session: StreamSession) -> None:
    """Recalculate session metrics from recent segments."""
    recent = session.segments[-30:]  # last 30 segments
    if not recent:
        return

    # Average throughput
    valid = [s for s in recent if s.throughput_bps > 0]
    if valid:
        session.avg_throughput_bps = int(sum(s.throughput_bps for s in valid) / len(valid))
        session.current_bitrate_bps = valid[-1].bitrate_bps

    # Throughput ratio (actual / required)
    if session.active_variant and session.active_variant.bandwidth > 0:
        session.throughput_ratio = round(
            session.avg_throughput_bps / session.active_variant.bandwidth, 2
        )

    # Buffer health estimation (simplified)
    buffer = 30.0  # assume 30s initial buffer
    for seg in recent:
        if seg.duration_secs > 0 and seg.download_time_secs > 0:
            buffer += seg.duration_secs - seg.download_time_secs
            if buffer < 0:
                session.rebuffer_events += 1
                buffer = 0
    session.buffer_health_secs = max(0, round(buffer, 1))


# --- Public API ---

def get_sessions() -> List[StreamSessionSummary]:
    """Get summary of all stream sessions."""
    summaries = []
    for s in sorted(_sessions.values(), key=lambda x: x.last_activity, reverse=True):
        summaries.append(StreamSessionSummary(
            id=s.id,
            stream_type=s.stream_type,
            client_ip=s.client_ip,
            active=s.active,
            current_bitrate_bps=s.current_bitrate_bps,
            resolution=s.active_variant.resolution if s.active_variant else "",
            buffer_health_secs=s.buffer_health_secs,
            throughput_ratio=s.throughput_ratio,
            bitrate_switches=s.bitrate_switches,
            segment_errors=s.segment_errors,
            total_segments=s.total_segments,
            started_at=s.started_at,
            last_activity=s.last_activity,
        ))
    return summaries


def get_session(session_id: str) -> Optional[StreamSession]:
    """Get full session detail."""
    return _sessions.get(session_id)


def get_session_segments(session_id: str) -> List[SegmentInfo]:
    """Get segment history for a session."""
    session = _sessions.get(session_id)
    if session:
        return session.segments
    return []


def get_mock_sessions() -> List[StreamSessionSummary]:
    """Return mock sessions for development."""
    return [
        StreamSessionSummary(
            id="mock-hls-001",
            stream_type=StreamType.HLS,
            client_ip="192.168.4.10",
            active=True,
            current_bitrate_bps=6000000,
            resolution="1920x1080",
            buffer_health_secs=18.5,
            throughput_ratio=1.45,
            bitrate_switches=2,
            segment_errors=0,
            total_segments=156,
            started_at="2026-04-02T20:00:00Z",
            last_activity="2026-04-02T20:15:36Z",
        ),
        StreamSessionSummary(
            id="mock-dash-001",
            stream_type=StreamType.DASH,
            client_ip="192.168.4.11",
            active=True,
            current_bitrate_bps=3000000,
            resolution="1280x720",
            buffer_health_secs=8.2,
            throughput_ratio=1.12,
            bitrate_switches=5,
            segment_errors=1,
            total_segments=89,
            started_at="2026-04-02T20:05:00Z",
            last_activity="2026-04-02T20:14:12Z",
        ),
    ]


def get_mock_session_detail() -> StreamSession:
    """Return a mock session detail for development."""
    return StreamSession(
        id="mock-hls-001",
        stream_type=StreamType.HLS,
        client_ip="192.168.4.10",
        master_url="https://cdn.example.com/live/master.m3u8",
        variants=[
            VariantInfo(bandwidth=6000000, resolution="1920x1080", codecs="avc1.64001f,mp4a.40.2", url="1080p.m3u8"),
            VariantInfo(bandwidth=3000000, resolution="1280x720", codecs="avc1.640020,mp4a.40.2", url="720p.m3u8"),
            VariantInfo(bandwidth=1500000, resolution="854x480", codecs="avc1.42c01e,mp4a.40.2", url="480p.m3u8"),
        ],
        active_variant=VariantInfo(bandwidth=6000000, resolution="1920x1080", codecs="avc1.64001f,mp4a.40.2", url="1080p.m3u8"),
        segments=[
            SegmentInfo(url=f"seg{i}.ts", sequence=i, duration_secs=6.0, download_time_secs=3.5 + (i % 5) * 0.4, size_bytes=2800000, bitrate_bps=6000000, throughput_bps=int(2800000 * 8 / (3.5 + (i % 5) * 0.4)), timestamp=f"2026-04-02T20:{i:02d}:00Z")
            for i in range(20)
        ],
        started_at="2026-04-02T20:00:00Z",
        last_activity="2026-04-02T20:19:00Z",
        current_bitrate_bps=6000000,
        avg_throughput_bps=7200000,
        buffer_health_secs=18.5,
        throughput_ratio=1.45,
        bitrate_switches=2,
        segment_errors=0,
        total_segments=156,
    )
