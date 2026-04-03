"""Video quality probe using ffprobe.

Analyzes saved media segments for codec info, actual bitrate,
keyframe intervals, and detects corruption or encoding anomalies.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)


@dataclass
class StreamInfo:
    """Info about a single stream within a segment."""

    index: int
    codec_type: str  # "video", "audio"
    codec_name: str  # "h264", "hevc", "aac"
    profile: str = ""
    level: str = ""
    width: int = 0
    height: int = 0
    frame_rate: float = 0
    bit_rate: int = 0
    sample_rate: int = 0
    channels: int = 0


@dataclass
class SegmentAnalysis:
    """Analysis result for a single segment."""

    path: str
    file_size_bytes: int
    duration_secs: float
    actual_bitrate_bps: int
    format_name: str
    streams: List[StreamInfo] = field(default_factory=list)
    keyframe_count: int = 0
    keyframe_interval_secs: float = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    """Aggregated probe result across multiple segments."""

    segments_analyzed: int = 0
    total_duration_secs: float = 0
    avg_bitrate_bps: int = 0
    max_bitrate_bps: int = 0
    min_bitrate_bps: int = 0
    video_codec: str = ""
    video_resolution: str = ""
    video_profile: str = ""
    avg_keyframe_interval_secs: float = 0
    audio_codec: str = ""
    audio_channels: int = 0
    audio_sample_rate: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    segments: List[SegmentAnalysis] = field(default_factory=list)


async def probe_segment(path: str) -> SegmentAnalysis:
    """Analyze a single media segment with ffprobe."""
    if settings.mock_mode:
        return _mock_segment_analysis(path)

    p = Path(path)
    if not p.exists():
        return SegmentAnalysis(path=path, file_size_bytes=0, duration_secs=0,
                               actual_bitrate_bps=0, format_name="",
                               errors=[f"File not found: {path}"])

    # Run ffprobe
    result = await run(
        "ffprobe", "-v", "error",
        "-show_format", "-show_streams",
        "-print_format", "json",
        path,
        check=False, timeout=30,
    )

    if not result.success:
        return SegmentAnalysis(path=path, file_size_bytes=p.stat().st_size,
                               duration_secs=0, actual_bitrate_bps=0, format_name="",
                               errors=[result.stderr[:200]])

    try:
        data = json.loads(result.stdout)
        return _parse_ffprobe(path, p.stat().st_size, data)
    except (json.JSONDecodeError, KeyError) as e:
        return SegmentAnalysis(path=path, file_size_bytes=p.stat().st_size,
                               duration_secs=0, actual_bitrate_bps=0, format_name="",
                               errors=[str(e)])


async def probe_segments(paths: List[str]) -> ProbeResult:
    """Analyze multiple segments and aggregate results."""
    result = ProbeResult()
    bitrates = []

    for path in paths:
        analysis = await probe_segment(path)
        result.segments.append(analysis)
        result.segments_analyzed += 1
        result.total_duration_secs += analysis.duration_secs
        result.total_errors += len(analysis.errors)
        result.total_warnings += len(analysis.warnings)

        if analysis.actual_bitrate_bps > 0:
            bitrates.append(analysis.actual_bitrate_bps)

        # Extract codec info from first valid segment
        if not result.video_codec:
            for s in analysis.streams:
                if s.codec_type == "video":
                    result.video_codec = s.codec_name
                    result.video_profile = s.profile
                    if s.width and s.height:
                        result.video_resolution = f"{s.width}x{s.height}"
                elif s.codec_type == "audio" and not result.audio_codec:
                    result.audio_codec = s.codec_name
                    result.audio_channels = s.channels
                    result.audio_sample_rate = s.sample_rate

        if analysis.keyframe_interval_secs > 0:
            result.avg_keyframe_interval_secs = analysis.keyframe_interval_secs

    if bitrates:
        result.avg_bitrate_bps = int(sum(bitrates) / len(bitrates))
        result.max_bitrate_bps = max(bitrates)
        result.min_bitrate_bps = min(bitrates)

    return result


async def get_keyframe_info(path: str) -> dict:
    """Get keyframe (I-frame) positions from a segment."""
    if settings.mock_mode:
        return {"keyframes": [0.0, 2.0, 4.0], "count": 3, "avg_interval_secs": 2.0}

    result = await run(
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=pict_type,pts_time",
        "-print_format", "json",
        path,
        check=False, timeout=60,
    )

    if not result.success:
        return {"error": result.stderr[:200]}

    try:
        data = json.loads(result.stdout)
        frames = data.get("frames", [])
        keyframe_times = [
            float(f["pts_time"])
            for f in frames
            if f.get("pict_type") == "I" and "pts_time" in f
        ]

        intervals = [keyframe_times[i+1] - keyframe_times[i] for i in range(len(keyframe_times)-1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 0

        return {
            "keyframes": keyframe_times,
            "count": len(keyframe_times),
            "avg_interval_secs": round(avg_interval, 3),
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return {"error": str(e)}


def _parse_ffprobe(path: str, file_size: int, data: dict) -> SegmentAnalysis:
    """Parse ffprobe JSON output."""
    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0))
    bitrate = int(fmt.get("bit_rate", 0))

    # If bitrate not reported, calculate from size/duration
    if not bitrate and duration > 0:
        bitrate = int((file_size * 8) / duration)

    streams = []
    for s in data.get("streams", []):
        si = StreamInfo(
            index=s.get("index", 0),
            codec_type=s.get("codec_type", ""),
            codec_name=s.get("codec_name", ""),
            profile=s.get("profile", ""),
            level=str(s.get("level", "")),
            width=s.get("width", 0),
            height=s.get("height", 0),
            bit_rate=int(s.get("bit_rate", 0)),
            sample_rate=int(s.get("sample_rate", 0)),
            channels=s.get("channels", 0),
        )
        # Parse frame rate
        r_frame = s.get("r_frame_rate", "0/1")
        if "/" in r_frame:
            num, den = r_frame.split("/")
            si.frame_rate = round(float(num) / float(den), 2) if float(den) > 0 else 0
        streams.append(si)

    analysis = SegmentAnalysis(
        path=path,
        file_size_bytes=file_size,
        duration_secs=round(duration, 3),
        actual_bitrate_bps=bitrate,
        format_name=fmt.get("format_name", ""),
        streams=streams,
    )

    # Warnings
    if duration <= 0:
        analysis.warnings.append("Zero duration detected")
    if not any(s.codec_type == "video" for s in streams):
        analysis.warnings.append("No video stream found")

    return analysis


def _mock_segment_analysis(path: str) -> SegmentAnalysis:
    import random
    return SegmentAnalysis(
        path=path,
        file_size_bytes=random.randint(2_000_000, 4_000_000),
        duration_secs=6.006,
        actual_bitrate_bps=random.randint(4_500_000, 6_500_000),
        format_name="mpegts",
        streams=[
            StreamInfo(index=0, codec_type="video", codec_name="h264",
                       profile="High", level="4.1", width=1920, height=1080,
                       frame_rate=29.97, bit_rate=5_800_000),
            StreamInfo(index=1, codec_type="audio", codec_name="aac",
                       profile="LC", sample_rate=48000, channels=2,
                       bit_rate=128000),
        ],
        keyframe_count=3,
        keyframe_interval_secs=2.0,
    )
