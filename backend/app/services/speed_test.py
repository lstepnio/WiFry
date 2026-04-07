"""Built-in speed test using iperf3 and Ookla Speedtest CLI.

Two test modes:
  - iperf3: Measures throughput through the impairment path (LAN)
  - Ookla Speedtest CLI: Measures real internet speed through the RPi's
    upstream connection (WAN). Shows what the STB would see in the real world.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

_server_process: Optional[asyncio.subprocess.Process] = None
_results: Dict[str, dict] = {}

RESULTS_DIR = Path("/var/lib/wifry/speedtests") if not settings.mock_mode else Path("/tmp/wifry-speedtests")


def _ensure_dir() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _save_result(result: dict) -> None:
    """Persist a speed test result to disk."""
    _ensure_dir()
    rid = result.get("id", "unknown")
    (RESULTS_DIR / f"{rid}.json").write_text(json.dumps(result, indent=2))


def _load_results() -> None:
    """Load persisted results from disk into memory."""
    _ensure_dir()
    for f in RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            _results[data["id"]] = data
        except (json.JSONDecodeError, KeyError):
            pass


# Load on import
_load_results()


@dataclass
class SpeedTestResult:
    id: str
    mode: str  # "server" (client→RPi) or "client" (RPi→target)
    target: str
    started_at: str
    duration_secs: float
    download_mbps: float
    upload_mbps: float
    latency_ms: float
    jitter_ms: float
    packet_loss_pct: float
    retransmits: int
    raw: dict


async def start_server(port: int = 5201) -> dict:
    """Start iperf3 server on the RPi for clients to test against."""
    global _server_process

    if settings.mock_mode:
        return {"status": "running", "port": port, "message": "iperf3 server running (mock)"}

    if _server_process and _server_process.returncode is None:
        return {"status": "already_running", "port": port}

    _server_process = await asyncio.create_subprocess_exec(
        "iperf3", "-s", "-p", str(port), "-J", "--one-off",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    logger.info("iperf3 server started on port %d", port)
    return {"status": "running", "port": port}


async def stop_server() -> dict:
    """Stop the iperf3 server."""
    global _server_process

    if _server_process and _server_process.returncode is None:
        _server_process.terminate()
        try:
            await asyncio.wait_for(_server_process.wait(), timeout=3)
        except asyncio.TimeoutError:
            _server_process.kill()
        _server_process = None

    return {"status": "stopped"}


async def run_client_test(
    target: str = "127.0.0.1",
    port: int = 5201,
    duration: int = 10,
    reverse: bool = False,
    udp: bool = False,
    bandwidth: str = "",
) -> dict:
    """Run iperf3 as client (RPi → target or reverse)."""
    test_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()

    if settings.mock_mode:
        return _mock_result(test_id, target, now, duration)

    cmd = ["iperf3", "-c", target, "-p", str(port), "-t", str(duration), "-J"]
    if reverse:
        cmd.append("-R")
    if udp:
        cmd.append("-u")
        if bandwidth:
            cmd.extend(["-b", bandwidth])

    result = await run(*cmd, timeout=float(duration + 15), check=False)

    if not result.success:
        return {
            "id": test_id,
            "error": result.stderr or result.stdout,
            "started_at": now,
        }

    try:
        data = json.loads(result.stdout)
        parsed = _parse_iperf3_json(test_id, target, now, data)
        _results[test_id] = parsed
        _save_result(parsed)
        return parsed
    except (json.JSONDecodeError, KeyError) as e:
        return {"id": test_id, "error": str(e), "started_at": now}


def get_results() -> List[dict]:
    """Get all stored speed test results."""
    return sorted(_results.values(), key=lambda r: r.get("started_at", ""), reverse=True)


def delete_result(test_id: str) -> None:
    """Delete a single speed test result."""
    _results.pop(test_id, None)
    (RESULTS_DIR / f"{test_id}.json").unlink(missing_ok=True)


def delete_all_results() -> int:
    """Delete all speed test results. Returns count deleted."""
    count = len(_results)
    _results.clear()
    _ensure_dir()
    for f in RESULTS_DIR.glob("*.json"):
        f.unlink(missing_ok=True)
    return count


def _parse_iperf3_json(test_id: str, target: str, started_at: str, data: dict) -> dict:
    """Parse iperf3 JSON output into a clean result."""
    end = data.get("end", {})
    sum_sent = end.get("sum_sent", {})
    sum_recv = end.get("sum_received", {})
    streams = end.get("streams", [{}])

    # TCP results
    sender_bps = sum_sent.get("bits_per_second", 0)
    receiver_bps = sum_recv.get("bits_per_second", 0)
    retransmits = sum_sent.get("retransmits", 0)

    # UDP results (if applicable)
    udp_result = end.get("sum", {})
    jitter = udp_result.get("jitter_ms", 0)
    lost_pct = udp_result.get("lost_percent", 0)

    return {
        "id": test_id,
        "target": target,
        "started_at": started_at,
        "duration_secs": sum_sent.get("seconds", 0),
        "download_mbps": round(receiver_bps / 1_000_000, 2),
        "upload_mbps": round(sender_bps / 1_000_000, 2),
        "jitter_ms": round(jitter, 2),
        "packet_loss_pct": round(lost_pct, 2),
        "retransmits": retransmits,
        "bytes_sent": sum_sent.get("bytes", 0),
        "bytes_received": sum_recv.get("bytes", 0),
    }


async def run_ookla_test(server_id: str = "") -> dict:
    """Run Ookla Speedtest CLI test.

    Uses the official Speedtest CLI (speedtest --format=json) to measure
    real-world internet speed through the RPi's upstream connection.
    """
    test_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()

    if settings.mock_mode:
        result = _mock_ookla_result(test_id, now)
        _results[test_id] = result
        _save_result(result)
        return result

    cmd = ["speedtest", "--format=json", "--accept-license", "--accept-gdpr"]
    if server_id:
        cmd.extend(["--server-id", server_id])

    result = await run(*cmd, timeout=120, check=False)

    if not result.success:
        return {"id": test_id, "type": "ookla", "error": result.stderr or result.stdout, "started_at": now}

    try:
        data = json.loads(result.stdout)
        parsed = _parse_ookla_json(test_id, now, data)
        _results[test_id] = parsed
        _save_result(parsed)
        return parsed
    except (json.JSONDecodeError, KeyError) as e:
        return {"id": test_id, "type": "ookla", "error": str(e), "started_at": now}


async def list_ookla_servers() -> list:
    """List nearby Ookla Speedtest servers."""
    if settings.mock_mode:
        return [
            {"id": "12345", "name": "Comcast - Denver, CO", "host": "speedtest.denver.comcast.net", "distance_km": 12.5},
            {"id": "12346", "name": "CenturyLink - Denver, CO", "host": "speedtest.centurylink.net", "distance_km": 15.2},
            {"id": "12347", "name": "AT&T - Denver, CO", "host": "speedtest.att.com", "distance_km": 18.0},
        ]

    result = await run("speedtest", "--servers", "--format=json", "--accept-license", "--accept-gdpr", timeout=30, check=False)
    if not result.success:
        return []

    try:
        data = json.loads(result.stdout)
        servers = data.get("servers", [])
        return [{"id": str(s.get("id", "")), "name": s.get("name", ""), "host": s.get("host", ""), "distance_km": s.get("distance", 0)} for s in servers[:10]]
    except (json.JSONDecodeError, KeyError):
        return []


def _parse_ookla_json(test_id: str, started_at: str, data: dict) -> dict:
    """Parse Ookla Speedtest CLI JSON output."""
    download = data.get("download", {})
    upload = data.get("upload", {})
    ping = data.get("ping", {})
    server = data.get("server", {})
    isp = data.get("isp", "")
    result_url = data.get("result", {}).get("url", "")

    return {
        "id": test_id,
        "type": "ookla",
        "started_at": started_at,
        "download_mbps": round(download.get("bandwidth", 0) * 8 / 1_000_000, 2),
        "upload_mbps": round(upload.get("bandwidth", 0) * 8 / 1_000_000, 2),
        "ping_ms": round(ping.get("latency", 0), 2),
        "jitter_ms": round(ping.get("jitter", 0), 2),
        "packet_loss_pct": data.get("packetLoss", 0),
        "server_name": server.get("name", ""),
        "server_location": f"{server.get('location', '')}, {server.get('country', '')}",
        "server_id": str(server.get("id", "")),
        "isp": isp,
        "result_url": result_url,
        "bytes_sent": upload.get("bytes", 0),
        "bytes_received": download.get("bytes", 0),
    }


def _mock_ookla_result(test_id: str, started_at: str) -> dict:
    import random
    return {
        "id": test_id,
        "type": "ookla",
        "started_at": started_at,
        "download_mbps": round(random.uniform(80, 250), 2),
        "upload_mbps": round(random.uniform(20, 80), 2),
        "ping_ms": round(random.uniform(5, 25), 2),
        "jitter_ms": round(random.uniform(0.5, 3.0), 2),
        "packet_loss_pct": round(random.uniform(0, 0.2), 3),
        "server_name": "Comcast - Denver, CO",
        "server_location": "Denver, CO, US",
        "server_id": "12345",
        "isp": "Comcast Cable",
        "result_url": "https://www.speedtest.net/result/mock",
        "bytes_sent": random.randint(20_000_000, 80_000_000),
        "bytes_received": random.randint(80_000_000, 250_000_000),
    }


def _mock_result(test_id: str, target: str, started_at: str, duration: int) -> dict:
    import random
    return {
        "id": test_id,
        "target": target,
        "started_at": started_at,
        "duration_secs": duration,
        "download_mbps": round(random.uniform(45, 95), 2),
        "upload_mbps": round(random.uniform(20, 50), 2),
        "jitter_ms": round(random.uniform(0.5, 5.0), 2),
        "packet_loss_pct": round(random.uniform(0, 0.5), 3),
        "retransmits": random.randint(0, 15),
        "bytes_sent": random.randint(50_000_000, 120_000_000),
        "bytes_received": random.randint(50_000_000, 120_000_000),
    }
