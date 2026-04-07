"""WiFi scanner + speed test + video probe router."""

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..services import speed_test, video_probe, wifi_scanner
from ..services.hls_parser import is_master_playlist, parse_master, parse_media
from ..services.dash_parser import parse_mpd, detect_dash
from ..utils.shell import run

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tools"])


# --- WiFi Scanner ---

@router.get("/api/v1/wifi/scan")
async def scan_wifi(interface: str = ""):
    """Scan WiFi environment. Auto-links to active session."""
    result = await wifi_scanner.scan(interface)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.WIFI_SCAN,
        name=f"WiFi Scan ({result.scan_interface})",
        data={"network_count": len(result.networks), "our_channel": result.our_channel, "our_band": result.our_band},
        tags=["wifi", "scan", "environment"],
    )

    return {
        "scan_interface": result.scan_interface,
        "our_channel": result.our_channel,
        "our_band": result.our_band,
        "network_count": len(result.networks),
        "networks": [asdict(n) for n in result.networks],
        "channels_2g": [asdict(c) for c in result.channels_2g],
        "channels_5g": [asdict(c) for c in result.channels_5g],
    }


# --- Speed Test ---

@router.post("/api/v1/speedtest/server")
async def start_speedtest_server(port: int = 5201):
    """Start iperf3 server for client-to-RPi testing."""
    return await speed_test.start_server(port)


@router.delete("/api/v1/speedtest/server")
async def stop_speedtest_server():
    """Stop iperf3 server."""
    return await speed_test.stop_server()


@router.post("/api/v1/speedtest/run")
async def run_speedtest(
    target: str = "127.0.0.1",
    port: int = 5201,
    duration: int = 10,
    reverse: bool = False,
    udp: bool = False,
    bandwidth: str = "",
):
    """Run a speed test. Auto-links to active session."""
    result = await speed_test.run_client_test(target, port, duration, reverse, udp, bandwidth)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.SPEED_TEST,
        name=f"Speed Test: {target}",
        data=result,
        tags=["speedtest", "iperf3"],
        metadata={"target": target, "duration": duration},
    )

    return result


@router.get("/api/v1/speedtest/results")
async def get_speedtest_results():
    """Get stored speed test results."""
    return speed_test.get_results()


@router.delete("/api/v1/speedtest/results/{test_id}")
async def delete_speedtest_result(test_id: str):
    """Delete a single speed test result."""
    speed_test.delete_result(test_id)
    return {"status": "ok"}


@router.delete("/api/v1/speedtest/results")
async def delete_all_speedtest_results():
    """Delete all speed test results."""
    count = speed_test.delete_all_results()
    return {"status": "ok", "deleted": count}


# --- Ookla Speedtest ---

@router.post("/api/v1/speedtest/ookla")
async def run_ookla_speedtest(server_id: str = ""):
    """Run Ookla Speedtest CLI (real internet speed). Auto-links to active session."""
    result = await speed_test.run_ookla_test(server_id)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.SPEED_TEST,
        name=f"Ookla Speedtest: {result.get('server_name', 'unknown')}",
        data=result,
        tags=["speedtest", "ookla", "internet"],
    )

    return result


@router.get("/api/v1/speedtest/ookla/servers")
async def list_ookla_servers():
    """List nearby Ookla Speedtest servers."""
    return await speed_test.list_ookla_servers()


# --- Video Probe ---

@router.post("/api/v1/probe/segment")
async def probe_single_segment(path: str):
    """Analyze a single media segment with ffprobe."""
    result = await video_probe.probe_segment(path)
    return asdict(result)


@router.post("/api/v1/probe/segments")
async def probe_multiple_segments(paths: List[str]):
    """Analyze multiple segments. Auto-links to active session."""
    result = await video_probe.probe_segments(paths)

    from ..services import session_manager
    from ..models.session import ArtifactType
    await session_manager.auto_add_artifact(
        ArtifactType.PROBE,
        name=f"Video Probe ({result.segments_analyzed} segments)",
        data={"video_codec": result.video_codec, "resolution": result.video_resolution,
              "avg_bitrate_bps": result.avg_bitrate_bps, "errors": result.total_errors},
        tags=["probe", "ffprobe", "video-quality"],
    )

    return asdict(result)


@router.post("/api/v1/probe/keyframes")
async def get_keyframes(path: str):
    """Get keyframe info from a media segment."""
    return await video_probe.get_keyframe_info(path)


# --- Probe from URL ---

class ProbeUrlRequest(BaseModel):
    url: str
    max_segments: int = 5


async def _fetch_url(url: str) -> str:
    """Fetch URL content using curl."""
    result = await run("curl", "-sL", "-m", "15", url, check=False, timeout=20)
    if not result.success:
        raise HTTPException(502, f"Failed to fetch {url}: {result.stderr[:200]}")
    return result.stdout


async def _download_segment(url: str, dest: Path) -> bool:
    """Download a media segment to disk."""
    result = await run(
        "curl", "-sL", "-m", "30", "-o", str(dest), url,
        check=False, timeout=35,
    )
    return result.success and dest.exists() and dest.stat().st_size > 0


@router.post("/api/v1/probe/url")
async def probe_from_url(req: ProbeUrlRequest):
    """Fetch a manifest URL, download segments, and probe them.

    Supports:
    - HLS master playlist (.m3u8) — picks highest bitrate variant
    - HLS media playlist (.m3u8) — downloads segments directly
    - DASH MPD (.mpd) — picks first representation
    - Direct media URL (.ts, .mp4, .m4s) — downloads and probes
    """
    url = req.url.strip()
    max_seg = min(req.max_segments, 20)
    segment_dir = Path("/tmp/wifry-probe-segments")
    segment_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old probe segments
    for old in segment_dir.glob("*"):
        old.unlink(missing_ok=True)

    segment_urls: List[str] = []
    manifest_info: dict = {}

    # Detect type by extension or content
    url_lower = url.lower()

    if url_lower.endswith((".ts", ".m4s", ".mp4", ".m4v", ".m4a", ".aac")):
        # Direct media file
        segment_urls = [url]
        manifest_info = {"type": "direct", "url": url}

    elif url_lower.endswith(".mpd") or "dash" in url_lower:
        # DASH MPD
        content = await _fetch_url(url)
        mpd = parse_mpd(content, base_url=url)
        manifest_info = {
            "type": "dash",
            "url": url,
            "periods": len(mpd.periods),
            "duration_secs": mpd.media_presentation_duration_secs,
        }
        # Get segment URLs from first period, first adaptation set, first representation
        for period in mpd.periods:
            for adapt in period.adaptation_sets:
                if adapt.representations:
                    rep = adapt.representations[0]
                    manifest_info["representation"] = {
                        "id": rep.id,
                        "bandwidth": rep.bandwidth,
                        "width": rep.width,
                        "height": rep.height,
                        "codecs": rep.codecs,
                    }
                    # Build segment URLs from template or segment list
                    base = mpd.base_url or url.rsplit("/", 1)[0] + "/"
                    for seg_url in rep.segment_urls[:max_seg]:
                        full_url = seg_url if seg_url.startswith("http") else urljoin(base, seg_url)
                        segment_urls.append(full_url)
                    if segment_urls:
                        break
            if segment_urls:
                break

    else:
        # Assume HLS
        content = await _fetch_url(url)

        if is_master_playlist(content):
            master = parse_master(content, base_url=url)
            if not master.variants:
                raise HTTPException(400, "No variants found in master playlist")

            # Pick highest bitrate
            best = max(master.variants, key=lambda v: v.bandwidth)
            manifest_info = {
                "type": "hls_master",
                "url": url,
                "variants": len(master.variants),
                "selected": {
                    "bandwidth": best.bandwidth,
                    "resolution": best.resolution,
                    "codecs": best.codecs,
                    "uri": best.uri,
                },
            }

            # Fetch the media playlist
            media_url = best.uri if best.uri.startswith("http") else urljoin(url, best.uri)
            content = await _fetch_url(media_url)
        else:
            media_url = url

        # Parse media playlist (base_url must be the media playlist URL, not master)
        media = parse_media(content, base_url=media_url)
        manifest_info.setdefault("type", "hls_media")
        manifest_info["segments_total"] = len(media.segments)
        manifest_info["target_duration"] = media.target_duration

        for seg in media.segments[:max_seg]:
            seg_url = seg.uri if seg.uri.startswith("http") else urljoin(media_url, seg.uri)
            segment_urls.append(seg_url)

    if not segment_urls:
        raise HTTPException(400, "No segments found in manifest")

    # Download segments
    downloaded_paths: List[str] = []
    for i, seg_url in enumerate(segment_urls[:max_seg]):
        ext = ".ts"
        if ".m4s" in seg_url:
            ext = ".m4s"
        elif ".mp4" in seg_url:
            ext = ".mp4"

        dest = segment_dir / f"seg_{i:04d}{ext}"
        ok = await _download_segment(seg_url, dest)
        if ok:
            downloaded_paths.append(str(dest))
        else:
            logger.warning("Failed to download segment: %s", seg_url)

    if not downloaded_paths:
        raise HTTPException(502, "Failed to download any segments")

    # Probe downloaded segments
    probe_result = await video_probe.probe_segments(downloaded_paths)
    result = asdict(probe_result)
    result["manifest"] = manifest_info
    result["segment_urls"] = segment_urls[:max_seg]

    return result
