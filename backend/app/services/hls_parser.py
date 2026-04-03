"""HLS M3U8 playlist parser (RFC 8216).

Pure Python parser — no external dependencies. Handles both
master playlists (variant streams) and media playlists (segments).
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin


@dataclass
class HLSSegment:
    uri: str
    duration: float
    sequence: int
    title: str = ""
    byterange: Optional[str] = None
    discontinuity: bool = False
    key_method: str = ""  # e.g. "AES-128", "SAMPLE-AES", "NONE"
    key_uri: str = ""


@dataclass
class HLSVariant:
    uri: str
    bandwidth: int
    average_bandwidth: int = 0
    resolution: str = ""
    codecs: str = ""
    frame_rate: Optional[float] = None
    audio: str = ""
    subtitles: str = ""


@dataclass
class HLSMediaPlaylist:
    """Parsed media (segment) playlist."""

    target_duration: float = 0
    media_sequence: int = 0
    segments: List[HLSSegment] = field(default_factory=list)
    is_endlist: bool = False
    playlist_type: str = ""  # "VOD" or "EVENT"
    version: int = 0
    total_duration: float = 0


@dataclass
class HLSMasterPlaylist:
    """Parsed master playlist."""

    variants: List[HLSVariant] = field(default_factory=list)
    version: int = 0


def is_master_playlist(content: str) -> bool:
    """Check if M3U8 content is a master playlist (has EXT-X-STREAM-INF)."""
    return "#EXT-X-STREAM-INF" in content


def parse_master(content: str, base_url: str = "") -> HLSMasterPlaylist:
    """Parse a master playlist returning variant streams."""
    result = HLSMasterPlaylist()
    lines = content.strip().splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXT-X-VERSION:"):
            result.version = int(line.split(":")[1])

        elif line.startswith("#EXT-X-STREAM-INF:"):
            attrs = _parse_attributes(line.split(":", 1)[1])
            # Next non-comment line is the URI
            i += 1
            while i < len(lines) and lines[i].strip().startswith("#"):
                i += 1
            if i < len(lines):
                uri = lines[i].strip()
                if base_url and not uri.startswith("http"):
                    uri = urljoin(base_url, uri)

                variant = HLSVariant(
                    uri=uri,
                    bandwidth=int(attrs.get("BANDWIDTH", 0)),
                    average_bandwidth=int(attrs.get("AVERAGE-BANDWIDTH", 0)),
                    resolution=attrs.get("RESOLUTION", ""),
                    codecs=attrs.get("CODECS", ""),
                    frame_rate=float(attrs["FRAME-RATE"]) if "FRAME-RATE" in attrs else None,
                    audio=attrs.get("AUDIO", ""),
                    subtitles=attrs.get("SUBTITLES", ""),
                )
                result.variants.append(variant)

        i += 1

    # Sort variants by bandwidth (highest first)
    result.variants.sort(key=lambda v: v.bandwidth, reverse=True)
    return result


def parse_media(content: str, base_url: str = "") -> HLSMediaPlaylist:
    """Parse a media playlist returning segments."""
    result = HLSMediaPlaylist()
    lines = content.strip().splitlines()

    current_duration = 0.0
    current_title = ""
    current_discontinuity = False
    current_key_method = ""
    current_key_uri = ""
    sequence = 0

    for line in lines:
        line = line.strip()

        if line.startswith("#EXT-X-VERSION:"):
            result.version = int(line.split(":")[1])

        elif line.startswith("#EXT-X-TARGETDURATION:"):
            result.target_duration = float(line.split(":")[1])

        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            result.media_sequence = int(line.split(":")[1])
            sequence = result.media_sequence

        elif line.startswith("#EXT-X-PLAYLIST-TYPE:"):
            result.playlist_type = line.split(":")[1].strip()

        elif line.startswith("#EXTINF:"):
            parts = line.split(":", 1)[1]
            comma_idx = parts.find(",")
            if comma_idx >= 0:
                current_duration = float(parts[:comma_idx])
                current_title = parts[comma_idx + 1:].strip()
            else:
                current_duration = float(parts.rstrip(","))

        elif line.startswith("#EXT-X-DISCONTINUITY"):
            current_discontinuity = True

        elif line.startswith("#EXT-X-KEY:"):
            attrs = _parse_attributes(line.split(":", 1)[1])
            current_key_method = attrs.get("METHOD", "NONE")
            current_key_uri = attrs.get("URI", "")

        elif line.startswith("#EXT-X-ENDLIST"):
            result.is_endlist = True

        elif line and not line.startswith("#"):
            # This is a segment URI
            uri = line
            if base_url and not uri.startswith("http"):
                uri = urljoin(base_url, uri)

            segment = HLSSegment(
                uri=uri,
                duration=current_duration,
                sequence=sequence,
                title=current_title,
                discontinuity=current_discontinuity,
                key_method=current_key_method,
                key_uri=current_key_uri,
            )
            result.segments.append(segment)
            result.total_duration += current_duration
            sequence += 1

            # Reset per-segment state
            current_duration = 0.0
            current_title = ""
            current_discontinuity = False

    return result


def _parse_attributes(attr_string: str) -> dict:
    """Parse HLS attribute list (KEY=VALUE,KEY="VALUE",...)."""
    attrs = {}
    # Regex to match KEY=VALUE or KEY="VALUE"
    pattern = r'([A-Z\-]+)=(?:"([^"]*)"|([\w\.\-\/]+))'
    for match in re.finditer(pattern, attr_string):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        attrs[key] = value
    return attrs


def detect_hls(url: str, content_type: str) -> bool:
    """Check if a URL/content-type indicates HLS content."""
    if "mpegurl" in content_type.lower() or "x-mpegurl" in content_type.lower():
        return True
    url_lower = url.lower().split("?")[0]
    return url_lower.endswith(".m3u8") or url_lower.endswith(".m3u")


def detect_segment(url: str, content_type: str) -> bool:
    """Check if a URL/content-type indicates a media segment."""
    ct = content_type.lower()
    if "video/mp2t" in ct or "video/mp4" in ct or "application/octet-stream" in ct:
        return True
    url_lower = url.lower().split("?")[0]
    return (
        url_lower.endswith(".ts")
        or url_lower.endswith(".m4s")
        or url_lower.endswith(".m4v")
        or url_lower.endswith(".m4a")
        or url_lower.endswith(".fmp4")
    )
