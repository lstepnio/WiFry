"""Packet capture management using tshark.

Manages async tshark subprocesses for packet capture with BPF pre-filtering,
safety limits, and structured metadata.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.capture import (
    CaptureFilters,
    CaptureInfo,
    CaptureStatus,
    StartCaptureRequest,
)
from ..utils.shell import CommandResult, run
from . import storage

logger = logging.getLogger(__name__)

# In-memory registry of active and recent captures
_captures: Dict[str, CaptureInfo] = {}
_processes: Dict[str, asyncio.subprocess.Process] = {}
_lock = asyncio.Lock()


def _captures_dir() -> Path:
    return storage.ensure_data_path("captures")


def _metadata_path(capture_id: str) -> Path:
    return _captures_dir() / f"{capture_id}.json"


def _pcap_path(capture_id: str) -> Path:
    return _captures_dir() / f"{capture_id}.pcap"


def _save_metadata(info: CaptureInfo) -> None:
    _metadata_path(info.id).write_text(info.model_dump_json(indent=2))


def _load_metadata(capture_id: str) -> Optional[CaptureInfo]:
    path = _metadata_path(capture_id)
    if path.exists():
        return CaptureInfo.model_validate_json(path.read_text())
    return None


async def start_capture(req: StartCaptureRequest) -> CaptureInfo:
    """Start a new tshark capture."""
    capture_id = uuid.uuid4().hex[:12]
    pcap = _pcap_path(capture_id)
    bpf = req.filters.to_bpf()
    now = datetime.now(timezone.utc).isoformat()

    info = CaptureInfo(
        id=capture_id,
        name=req.name or f"capture-{capture_id}",
        interface=req.interface,
        status=CaptureStatus.RUNNING,
        filters=req.filters,
        bpf_expression=bpf,
        started_at=now,
        pcap_path=str(pcap),
    )

    if settings.mock_mode:
        info.status = CaptureStatus.COMPLETED
        info.stopped_at = now
        info.packet_count = 42
        info.file_size_bytes = 12345
        async with _lock:
            _captures[capture_id] = info
        _save_metadata(info)
        logger.info("Mock capture started: %s", capture_id)
        return info

    # Build tshark command
    cmd = [
        "tshark",
        "-i", req.interface,
        "-c", str(req.max_packets),
        "-a", f"duration:{req.max_duration_secs}",
        "-a", f"filesize:{req.max_file_size_mb * 1024}",
        "-w", str(pcap),
    ]

    if bpf:
        cmd.extend(["-f", bpf])

    logger.info("Starting capture %s: %s", capture_id, " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        "sudo", *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async with _lock:
        _captures[capture_id] = info
        _processes[capture_id] = proc
    _save_metadata(info)

    # Monitor process in background
    asyncio.create_task(_monitor_capture(capture_id, proc))

    return info


async def _monitor_capture(capture_id: str, proc: asyncio.subprocess.Process) -> None:
    """Monitor tshark: update live packet count, then finalize on exit."""
    try:
        pcap = None
        info = _captures.get(capture_id)
        if info:
            pcap = Path(info.pcap_path)

        # Poll file size and parse stderr for live packet count while running
        stderr_lines: list[str] = []

        async def _read_stderr():
            """Read stderr in background to prevent buffer deadlock."""
            if proc.stderr:
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    stderr_lines.append(line.decode("utf-8", errors="replace").strip())

        async def _drain_stdout():
            """Drain stdout to prevent buffer deadlock."""
            if proc.stdout:
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break

        stderr_task = asyncio.create_task(_read_stderr())
        stdout_task = asyncio.create_task(_drain_stdout())

        # Poll pcap file size for live updates until process exits
        while True:
            # Check if process has exited
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                break  # Process exited
            except asyncio.TimeoutError:
                pass  # Still running — update live stats

            if pcap and info:
                try:
                    # stat works on root-owned files in 1777 dirs without sudo
                    if pcap.exists():
                        info.file_size_bytes = pcap.stat().st_size
                except (OSError, PermissionError):
                    pass

        await stderr_task
        await stdout_task

        # Process finished — fix ownership FIRST (sudo tshark creates files as root)
        if pcap and pcap.exists():
            await run("chmod", "644", str(pcap), sudo=True, check=False)
            await run("chown", "wifry:wifry", str(pcap), sudo=True, check=False)

        # Now finalize metadata
        info = _captures.get(capture_id)
        if not info:
            return

        if proc.returncode == 0 or info.status == CaptureStatus.STOPPED:
            info.status = CaptureStatus.COMPLETED if info.status != CaptureStatus.STOPPED else info.status
        else:
            info.status = CaptureStatus.ERROR
            stderr_text = "\n".join(stderr_lines)
            info.error = stderr_text[:500]

        info.stopped_at = datetime.now(timezone.utc).isoformat()

        if pcap and pcap.exists():
            info.file_size_bytes = pcap.stat().st_size
            count = await _count_packets(info.pcap_path)
            info.packet_count = count

        _captures[capture_id] = info
        _save_metadata(info)
        logger.info("Capture %s finished: %s (%d packets)", capture_id, info.status, info.packet_count)

    except Exception as e:
        logger.error("Error monitoring capture %s: %s", capture_id, e)
    finally:
        _processes.pop(capture_id, None)


async def _count_packets(pcap_path: str) -> int:
    """Count packets in a pcap file using tshark."""
    result = await run(
        "tshark", "-r", pcap_path, "-T", "fields", "-e", "frame.number",
        sudo=True, check=False, timeout=30,
    )
    if result.success and result.stdout:
        lines = result.stdout.strip().splitlines()
        return len(lines)
    return 0


async def stop_capture(capture_id: str) -> CaptureInfo:
    """Stop a running capture."""
    async with _lock:
        info = _captures.get(capture_id) or _load_metadata(capture_id)
        if not info:
            raise ValueError(f"Capture {capture_id} not found")

        if info.status != CaptureStatus.RUNNING:
            return info

        info.status = CaptureStatus.STOPPED
        info.stopped_at = datetime.now(timezone.utc).isoformat()

        proc = _processes.get(capture_id)

    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()

    async with _lock:
        _captures[capture_id] = info
    _save_metadata(info)
    logger.info("Stopped capture %s", capture_id)
    return info


def get_capture(capture_id: str) -> Optional[CaptureInfo]:
    """Get capture info by ID."""
    info = _captures.get(capture_id)
    if info:
        return info
    return _load_metadata(capture_id)


async def list_captures() -> List[CaptureInfo]:
    """List all captures (in-memory + on-disk)."""
    # Load any on-disk captures not in memory
    captures_dir = _captures_dir()
    async with _lock:
        for meta_file in captures_dir.glob("*.json"):
            if ".analysis." in meta_file.name:
                continue
            cid = meta_file.stem
            if cid not in _captures:
                info = _load_metadata(cid)
                if info:
                    _captures[cid] = info

        return sorted(_captures.values(), key=lambda c: c.started_at or "", reverse=True)


async def delete_capture(capture_id: str) -> None:
    """Delete a capture and its files."""
    async with _lock:
        info = _captures.get(capture_id) or _load_metadata(capture_id)
        if not info:
            raise ValueError(f"Capture {capture_id} not found")

    # Stop if running (stop_capture acquires _lock internally)
    if info.status == CaptureStatus.RUNNING:
        await stop_capture(capture_id)

    # Remove files
    _metadata_path(capture_id).unlink(missing_ok=True)
    Path(info.pcap_path).unlink(missing_ok=True)
    # Remove analysis file if exists
    analysis_path = _captures_dir() / f"{capture_id}.analysis.json"
    analysis_path.unlink(missing_ok=True)

    async with _lock:
        _captures.pop(capture_id, None)
    logger.info("Deleted capture %s", capture_id)


def get_pcap_path(capture_id: str) -> Optional[Path]:
    """Get the pcap file path for download."""
    info = get_capture(capture_id)
    if not info:
        return None
    pcap = Path(info.pcap_path)
    if pcap.exists():
        return pcap
    return None


async def get_capture_stats(capture_id: str) -> dict:
    """Get detailed statistics from a pcap using tshark.

    Extracts protocol distribution, conversation table, IO stats,
    and TCP analysis for AI consumption.
    """
    info = get_capture(capture_id)
    if not info:
        return {}

    if settings.mock_mode:
        return _mock_stats()

    if not Path(info.pcap_path).exists():
        return {}

    stats = {}

    # Protocol hierarchy
    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "io,phs",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["protocol_hierarchy"] = result.stdout

    # Conversation table (TCP)
    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "conv,tcp",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["tcp_conversations"] = result.stdout

    # IO statistics (1-second intervals)
    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "io,stat,1",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["io_stats"] = result.stdout

    # TCP retransmission analysis
    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "expert",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["expert_info"] = result.stdout

    # DNS queries
    result = await run(
        "tshark", "-r", info.pcap_path,
        "-Y", "dns.flags.response == 0",
        "-T", "fields",
        "-e", "frame.time_relative",
        "-e", "ip.src",
        "-e", "dns.qry.name",
        "-e", "dns.qry.type",
        sudo=True, check=False, timeout=60,
    )
    if result.success and result.stdout:
        stats["dns_queries"] = result.stdout

    return stats


def _mock_stats() -> dict:
    return {
        "protocol_hierarchy": (
            "Protocol Hierarchy Statistics\n"
            "  eth                  frames:1000 bytes:650000\n"
            "    ip                 frames:980  bytes:640000\n"
            "      tcp              frames:900  bytes:600000\n"
            "        tls            frames:800  bytes:550000\n"
            "      udp              frames:60   bytes:30000\n"
            "        dns            frames:40   bytes:5000\n"
            "      icmp             frames:20   bytes:10000\n"
        ),
        "tcp_conversations": (
            "TCP Conversations\n"
            "192.168.4.10:54321 <-> 104.16.132.229:443  800 packets  550000 bytes\n"
            "192.168.4.10:54322 <-> 192.168.1.1:53      40 packets   5000 bytes\n"
        ),
        "io_stats": (
            "IO Statistics\n"
            "Interval | Frames | Bytes\n"
            "0-1      | 120    | 80000\n"
            "1-2      | 135    | 90000\n"
            "2-3      | 98     | 65000\n"
            "3-4      | 150    | 100000\n"
        ),
        "expert_info": (
            "Expert Info\n"
            "Severity: Warning  Group: Sequence  Summary: TCP Retransmission  Count: 32\n"
            "Severity: Note     Group: Sequence  Summary: TCP Dup ACK        Count: 15\n"
            "Severity: Chat     Group: Sequence  Summary: TCP Window Update   Count: 8\n"
        ),
        "dns_queries": (
            "0.001  192.168.4.10  cdn.example.com  A\n"
            "0.502  192.168.4.10  api.example.com  A\n"
            "1.003  192.168.4.10  cdn.example.com  AAAA\n"
        ),
    }
