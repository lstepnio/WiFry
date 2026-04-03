"""WiFi scanner + speed test + video probe router."""

from dataclasses import asdict
from typing import List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..services import speed_test, video_probe, wifi_scanner

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
