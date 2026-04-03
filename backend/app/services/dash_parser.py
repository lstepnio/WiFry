"""MPEG-DASH MPD manifest parser.

Parses MPD XML manifests to extract adaptation sets, representations,
and segment information. Uses stdlib xml.etree.ElementTree.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

MPD_NS = "{urn:mpeg:dash:schema:mpd:2011}"


@dataclass
class DASHRepresentation:
    """A single representation (quality level) in an adaptation set."""

    id: str
    bandwidth: int
    width: int = 0
    height: int = 0
    codecs: str = ""
    mime_type: str = ""
    frame_rate: Optional[float] = None

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return ""


@dataclass
class DASHSegmentTemplate:
    """Segment URL template for generating segment URLs."""

    media: str = ""        # e.g. "$RepresentationID$/$Number$.m4s"
    initialization: str = ""  # e.g. "$RepresentationID$/init.mp4"
    timescale: int = 1
    duration: int = 0
    start_number: int = 1

    @property
    def segment_duration_secs(self) -> float:
        if self.timescale and self.duration:
            return self.duration / self.timescale
        return 0


@dataclass
class DASHAdaptationSet:
    """An adaptation set (video, audio, etc.)."""

    id: str = ""
    content_type: str = ""  # "video", "audio", "text"
    mime_type: str = ""
    codecs: str = ""
    representations: List[DASHRepresentation] = field(default_factory=list)
    segment_template: Optional[DASHSegmentTemplate] = None


@dataclass
class DASHPeriod:
    """A period in the MPD."""

    id: str = ""
    duration_secs: float = 0
    adaptation_sets: List[DASHAdaptationSet] = field(default_factory=list)


@dataclass
class DASHManifest:
    """Parsed MPD manifest."""

    type: str = "static"  # "static" (VOD) or "dynamic" (live)
    min_buffer_time_secs: float = 0
    media_presentation_duration_secs: float = 0
    periods: List[DASHPeriod] = field(default_factory=list)
    base_url: str = ""

    @property
    def all_representations(self) -> List[DASHRepresentation]:
        reps = []
        for period in self.periods:
            for adapt in period.adaptation_sets:
                reps.extend(adapt.representations)
        return reps

    @property
    def video_representations(self) -> List[DASHRepresentation]:
        reps = []
        for period in self.periods:
            for adapt in period.adaptation_sets:
                if adapt.content_type == "video" or "video" in adapt.mime_type:
                    reps.extend(adapt.representations)
        return sorted(reps, key=lambda r: r.bandwidth, reverse=True)


def parse_mpd(content: str, base_url: str = "") -> DASHManifest:
    """Parse an MPD manifest XML string."""
    root = ET.fromstring(content)
    manifest = DASHManifest(base_url=base_url)

    manifest.type = root.get("type", "static")
    manifest.min_buffer_time_secs = _parse_duration(root.get("minBufferTime", ""))
    manifest.media_presentation_duration_secs = _parse_duration(
        root.get("mediaPresentationDuration", "")
    )

    # BaseURL
    base_el = root.find(f"{MPD_NS}BaseURL")
    if base_el is not None and base_el.text:
        manifest.base_url = base_el.text if base_el.text.startswith("http") else urljoin(base_url, base_el.text)

    # Periods
    for period_el in root.findall(f"{MPD_NS}Period"):
        period = DASHPeriod(
            id=period_el.get("id", ""),
            duration_secs=_parse_duration(period_el.get("duration", "")),
        )

        for adapt_el in period_el.findall(f"{MPD_NS}AdaptationSet"):
            adapt = _parse_adaptation_set(adapt_el)
            period.adaptation_sets.append(adapt)

        manifest.periods.append(period)

    return manifest


def _parse_adaptation_set(el: ET.Element) -> DASHAdaptationSet:
    """Parse an AdaptationSet element."""
    adapt = DASHAdaptationSet(
        id=el.get("id", ""),
        content_type=el.get("contentType", ""),
        mime_type=el.get("mimeType", ""),
        codecs=el.get("codecs", ""),
    )

    # Infer content_type from mimeType if not set
    if not adapt.content_type and adapt.mime_type:
        if "video" in adapt.mime_type:
            adapt.content_type = "video"
        elif "audio" in adapt.mime_type:
            adapt.content_type = "audio"
        elif "text" in adapt.mime_type:
            adapt.content_type = "text"

    # SegmentTemplate
    seg_tmpl_el = el.find(f"{MPD_NS}SegmentTemplate")
    if seg_tmpl_el is not None:
        adapt.segment_template = DASHSegmentTemplate(
            media=seg_tmpl_el.get("media", ""),
            initialization=seg_tmpl_el.get("initialization", ""),
            timescale=int(seg_tmpl_el.get("timescale", "1")),
            duration=int(seg_tmpl_el.get("duration", "0")),
            start_number=int(seg_tmpl_el.get("startNumber", "1")),
        )

    # Representations
    for rep_el in el.findall(f"{MPD_NS}Representation"):
        rep = DASHRepresentation(
            id=rep_el.get("id", ""),
            bandwidth=int(rep_el.get("bandwidth", "0")),
            width=int(rep_el.get("width", "0")),
            height=int(rep_el.get("height", "0")),
            codecs=rep_el.get("codecs", "") or adapt.codecs,
            mime_type=rep_el.get("mimeType", "") or adapt.mime_type,
        )
        fr = rep_el.get("frameRate")
        if fr:
            if "/" in fr:
                num, den = fr.split("/")
                rep.frame_rate = float(num) / float(den)
            else:
                rep.frame_rate = float(fr)

        # Check for per-representation SegmentTemplate
        rep_seg_el = rep_el.find(f"{MPD_NS}SegmentTemplate")
        if rep_seg_el is not None and adapt.segment_template is None:
            adapt.segment_template = DASHSegmentTemplate(
                media=rep_seg_el.get("media", ""),
                initialization=rep_seg_el.get("initialization", ""),
                timescale=int(rep_seg_el.get("timescale", "1")),
                duration=int(rep_seg_el.get("duration", "0")),
                start_number=int(rep_seg_el.get("startNumber", "1")),
            )

        adapt.representations.append(rep)

    # Sort representations by bandwidth (highest first)
    adapt.representations.sort(key=lambda r: r.bandwidth, reverse=True)
    return adapt


def _parse_duration(iso_duration: str) -> float:
    """Parse ISO 8601 duration (PT1H2M3.4S) to seconds."""
    if not iso_duration:
        return 0

    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?",
        iso_duration,
    )
    if not match:
        return 0

    hours = float(match.group(1) or 0)
    minutes = float(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def detect_dash(url: str, content_type: str) -> bool:
    """Check if a URL/content-type indicates DASH content."""
    ct = content_type.lower()
    if "dash+xml" in ct or "mpd" in ct:
        return True
    url_lower = url.lower().split("?")[0]
    return url_lower.endswith(".mpd")
