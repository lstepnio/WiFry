"""Packet capture management using dumpcap with ring buffer.

V2 capture engine per capture-v2-master-spec and rpi5-performance-guide:
- dumpcap for capture (~5 MB RSS vs tshark's 30-80 MB)
- Ring buffer: 10 MB segments, max 10 files (100 MB ceiling)
- mergecap on stop to produce single pcap
- Post-processing pipeline: summary generation → interest detection
- Concurrent capture limit (semaphore)
- Disk space preflight checks
- Mid-capture disk monitoring
"""

import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.analysis_packs import AnalysisPack, get_pack_config
from ..models.capture import (
    CaptureMeta,
    CaptureFilters,
    CaptureInfo,
    CaptureStatus,
    CaptureSummary,
    StartCaptureRequest,
)
from ..utils.shell import CommandResult, run
from . import storage

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Ring buffer: 10 MB segments, max 10 files = 100 MB ceiling per capture
RING_SEGMENT_SIZE_KB = 10240  # 10 MB
RING_MAX_FILES = 10

# Concurrent capture limit — RPi 5 can handle 2 simultaneous dumpcap processes
_capture_semaphore = asyncio.Semaphore(2)

# Preflight thresholds
MIN_DISK_SPACE_MB = 200
MIN_RAM_MB = 256

# In-memory registry of active and recent captures
_captures: Dict[str, CaptureInfo] = {}
_processes: Dict[str, asyncio.subprocess.Process] = {}
_lock = asyncio.Lock()
_STALE_CAPTURE_MESSAGE = (
    "Capture interrupted before completion. Live capture state does not survive "
    "backend restarts."
)


def _captures_dir() -> Path:
    return storage.ensure_data_path("captures")


def _metadata_path(capture_id: str) -> Path:
    return _captures_dir() / f"{capture_id}.json"


def _pcap_path(capture_id: str) -> Path:
    return _captures_dir() / f"{capture_id}.pcap"


def _segments_dir(capture_id: str) -> Path:
    return _captures_dir() / f"{capture_id}_segments"


def _summary_path(capture_id: str) -> Path:
    return _captures_dir() / f"{capture_id}.summary.json"


def _save_metadata(info: CaptureInfo) -> None:
    _metadata_path(info.id).write_text(info.model_dump_json(indent=2))


def _load_metadata(capture_id: str) -> Optional[CaptureInfo]:
    path = _metadata_path(capture_id)
    if path.exists():
        info = CaptureInfo.model_validate_json(path.read_text())
        return _reconcile_capture(info)
    return None


def _reconcile_capture(info: CaptureInfo) -> CaptureInfo:
    """Fix captures that were running when the backend restarted."""
    if info.status not in (CaptureStatus.RUNNING, CaptureStatus.PROCESSING) or info.id in _processes:
        return info

    info.status = CaptureStatus.ERROR
    info.stopped_at = info.stopped_at or datetime.now(timezone.utc).isoformat()
    info.error = info.error or _STALE_CAPTURE_MESSAGE

    pcap = Path(info.pcap_path)
    if pcap.exists():
        try:
            info.file_size_bytes = pcap.stat().st_size
        except OSError:
            pass

    _captures[info.id] = info
    _save_metadata(info)
    logger.warning("Capture %s marked as interrupted after state reload", info.id)
    return info


# ── Preflight Checks ─────────────────────────────────────────────────────────

async def _preflight_check() -> Optional[str]:
    """Check if system is ready for a new capture.

    Returns None if OK, or an error message string.
    """
    if settings.mock_mode:
        return None

    # Check concurrent captures
    active = sum(1 for info in _captures.values() if info.status == CaptureStatus.RUNNING)
    if active >= 2:
        return f"Maximum concurrent captures reached ({active}/2). Stop a running capture first."

    # Check disk space
    try:
        stat = shutil.disk_usage(str(_captures_dir()))
        free_mb = stat.free / (1024 * 1024)
        if free_mb < MIN_DISK_SPACE_MB:
            return f"Insufficient disk space: {free_mb:.0f} MB free (minimum {MIN_DISK_SPACE_MB} MB)"
    except OSError:
        pass  # Can't check — proceed anyway

    # Check available RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_kb = int(line.split()[1])
                    if mem_kb / 1024 < MIN_RAM_MB:
                        return f"Insufficient RAM: {mem_kb / 1024:.0f} MB available (minimum {MIN_RAM_MB} MB)"
                    break
    except (OSError, ValueError):
        pass  # Non-Linux or can't check

    return None


# ── Capture Lifecycle ─────────────────────────────────────────────────────────

async def start_capture(req: StartCaptureRequest) -> CaptureInfo:
    """Start a new dumpcap capture with ring buffer."""
    # Preflight
    err = await _preflight_check()
    if err:
        raise ValueError(err)

    capture_id = uuid.uuid4().hex[:12]
    pcap = _pcap_path(capture_id)
    now = datetime.now(timezone.utc).isoformat()

    # Resolve pack config for BPF and duration overrides
    pack_name = req.pack or "custom"
    try:
        pack_enum = AnalysisPack(pack_name)
        pack_config = get_pack_config(pack_enum)
    except (ValueError, KeyError):
        pack_config = None

    # Use pack BPF if no custom filter specified
    bpf = req.filters.to_bpf()
    if not bpf and pack_config and pack_config.bpf:
        bpf = pack_config.bpf

    info = CaptureInfo(
        id=capture_id,
        name=req.name or f"capture-{capture_id}",
        interface=req.interface,
        status=CaptureStatus.RUNNING,
        pack=pack_name,
        filters=req.filters,
        bpf_expression=bpf,
        started_at=now,
        pcap_path=str(pcap),
    )

    if settings.mock_mode:
        info.status = CaptureStatus.COMPLETED
        info.stopped_at = now
        info.packet_count = 1000
        info.file_size_bytes = 650000
        async with _lock:
            _captures[capture_id] = info
        _save_metadata(info)

        # Generate mock summary
        asyncio.create_task(_post_process(capture_id))

        logger.info("Mock capture started: %s (pack=%s)", capture_id, pack_name)
        return info

    # Create segments directory for ring buffer
    seg_dir = _segments_dir(capture_id)
    seg_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    segment_base = seg_dir / f"{capture_id}.pcapng"

    # Build dumpcap command with ring buffer
    cmd = [
        "dumpcap",
        "-i", req.interface,
        "-w", str(segment_base),
        "-b", f"filesize:{RING_SEGMENT_SIZE_KB}",
        "-b", f"files:{RING_MAX_FILES}",
        "-a", f"duration:{req.max_duration_secs}",
    ]

    # dumpcap uses -c for packet count
    if req.max_packets and req.max_packets < 1000000:
        cmd.extend(["-c", str(req.max_packets)])

    # File size autostop (in KB)
    cmd.extend(["-a", f"filesize:{req.max_file_size_mb * 1024}"])

    if bpf:
        cmd.extend(["-f", bpf])

    logger.info("Starting capture %s: %s", capture_id, " ".join(cmd))

    # dumpcap runs WITHOUT sudo — it uses Linux capabilities (cap_net_raw,cap_net_admin)
    # set via setcap during install. This avoids privilege-dropping issues where
    # sudo dumpcap would drop back to root for file I/O, breaking writes to
    # wifry-owned directories.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
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
    """Monitor dumpcap: update live stats, then finalize on exit."""
    try:
        info = _captures.get(capture_id)
        seg_dir = _segments_dir(capture_id)

        # Read stderr in background to prevent buffer deadlock
        stderr_lines: list[str] = []

        async def _read_stderr():
            if proc.stderr:
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    stderr_lines.append(line.decode("utf-8", errors="replace").strip())

        async def _drain_stdout():
            if proc.stdout:
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break

        stderr_task = asyncio.create_task(_read_stderr())
        stdout_task = asyncio.create_task(_drain_stdout())

        # Poll segment directory for live size updates + disk monitoring
        disk_check_counter = 0
        while True:
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                pass

            # Update live file size from segments
            if info and seg_dir.exists():
                try:
                    total_size = sum(f.stat().st_size for f in seg_dir.iterdir() if f.is_file())
                    info.file_size_bytes = total_size
                except (OSError, PermissionError):
                    pass

            # Mid-capture disk check every 10 seconds
            disk_check_counter += 1
            if disk_check_counter >= 10 and not settings.mock_mode:
                disk_check_counter = 0
                try:
                    stat = shutil.disk_usage(str(_captures_dir()))
                    if stat.free < 50 * 1024 * 1024:  # Emergency: < 50 MB
                        logger.warning("Emergency stop: disk space critical (%d MB free)", stat.free // (1024 * 1024))
                        proc.terminate()
                        if info:
                            info.error = "Emergency stop: disk space critically low"
                except OSError:
                    pass

        await stderr_task
        await stdout_task

        # ── Post-capture: merge segments → single pcap ────────────────────
        info = _captures.get(capture_id)
        if not info:
            return

        # Segments are already wifry-owned (dumpcap runs as wifry via capabilities)

        # Merge ring buffer segments into single pcap
        merged_pcap = _pcap_path(capture_id)
        merged_ok = await _merge_segments(capture_id, seg_dir, merged_pcap)

        if not merged_ok:
            # Fallback: try to find the single segment if only one exists
            segments = sorted(seg_dir.glob("*.pcapng"))
            if segments:
                try:
                    shutil.copy2(str(segments[0]), str(merged_pcap))
                    merged_ok = True
                except OSError:
                    pass

        # Finalize status
        if proc.returncode == 0 or info.status == CaptureStatus.STOPPED:
            if info.status != CaptureStatus.STOPPED:
                info.status = CaptureStatus.COMPLETED
        else:
            info.status = CaptureStatus.ERROR
            stderr_text = "\n".join(stderr_lines)
            info.error = stderr_text[:500] if stderr_text else f"dumpcap exited with code {proc.returncode}"

        info.stopped_at = datetime.now(timezone.utc).isoformat()

        if merged_pcap.exists():
            info.file_size_bytes = merged_pcap.stat().st_size
            count = await _count_packets(str(merged_pcap))
            info.packet_count = count

        info.pcap_path = str(merged_pcap)
        _captures[capture_id] = info
        _save_metadata(info)

        # Clean up segment directory
        if seg_dir.exists() and merged_ok:
            try:
                shutil.rmtree(str(seg_dir))
            except OSError as e:
                logger.warning("Failed to clean segments dir: %s", e)

        logger.info(
            "Capture %s finished: %s (%d packets, %d bytes)",
            capture_id, info.status, info.packet_count, info.file_size_bytes,
        )

        # Trigger post-processing (summary generation)
        if info.status in (CaptureStatus.COMPLETED, CaptureStatus.STOPPED) and info.packet_count > 0:
            asyncio.create_task(_post_process(capture_id))

    except Exception as e:
        logger.error("Error monitoring capture %s: %s", capture_id, e)
    finally:
        _processes.pop(capture_id, None)


async def _merge_segments(capture_id: str, seg_dir: Path, output_path: Path) -> bool:
    """Merge ring buffer segments using mergecap."""
    segments = sorted(seg_dir.glob("*.pcapng"))
    if not segments:
        return False

    if len(segments) == 1:
        # Single segment — just copy
        try:
            shutil.copy2(str(segments[0]), str(output_path))
            return True
        except OSError:
            return False

    # Multiple segments — use mergecap (no sudo needed, files are wifry-owned)
    seg_paths = [str(s) for s in segments]
    result = await run(
        "mergecap", "-w", str(output_path), *seg_paths,
        check=False, timeout=120,
    )

    if result.success:
        logger.info("Merged %d segments for capture %s", len(segments), capture_id)
        return True
    else:
        logger.error("mergecap failed for capture %s: %s", capture_id, result.stderr)
        return False


async def _count_packets(pcap_path: str) -> int:
    """Count packets in a pcap file using capinfos (faster than tshark)."""
    result = await run(
        "capinfos", "-c", "-M", pcap_path,
        check=False, timeout=30,
    )
    if result.success and result.stdout:
        # Parse "Number of packets: 1234" or "Number of packets = 1234"
        for line in result.stdout.splitlines():
            if "packets" in line.lower():
                import re
                match = re.search(r"(\d+)", line.split(":")[-1] if ":" in line else line.split("=")[-1])
                if match:
                    return int(match.group(1))

    # Fallback: count with tshark
    result = await run(
        "tshark", "-r", pcap_path, "-T", "fields", "-e", "frame.number",
        check=False, timeout=30,
    )
    if result.success and result.stdout:
        return len(result.stdout.strip().splitlines())
    return 0


async def _post_process(capture_id: str) -> None:
    """Run post-processing pipeline: generate summary + run retention."""
    try:
        info = _captures.get(capture_id) or _load_metadata(capture_id)
        if not info:
            return

        # Mark as processing
        info.status = CaptureStatus.PROCESSING
        _captures[capture_id] = info
        _save_metadata(info)

        # Build CaptureMeta
        meta = CaptureMeta(
            capture_id=capture_id,
            pack=info.pack,
            interface=info.interface,
            bpf=info.bpf_expression,
            started_at=info.started_at or "",
            stopped_at=info.stopped_at or "",
            total_packets=info.packet_count,
            total_bytes=info.file_size_bytes,
            pcap_file_bytes=info.file_size_bytes,
        )

        # Calculate duration
        if info.started_at and info.stopped_at:
            try:
                start = datetime.fromisoformat(info.started_at.replace("Z", "+00:00"))
                stop = datetime.fromisoformat(info.stopped_at.replace("Z", "+00:00"))
                meta.duration_secs = round((stop - start).total_seconds(), 1)
            except ValueError:
                pass

        # Generate summary
        from . import capture_stats
        summary = await capture_stats.generate_summary(
            capture_id=capture_id,
            pcap_path=info.pcap_path,
            pack=info.pack,
            meta=meta,
        )

        # Save summary to disk
        summary_path = _summary_path(capture_id)
        summary_path.write_text(summary.model_dump_json(indent=2))

        # Update capture metadata with health badge
        info.health_badge = summary.interest.health_badge.value
        info.has_summary = True

        # Check if analysis already exists
        analysis_path = _captures_dir() / f"{capture_id}.analysis.json"
        info.has_analysis = analysis_path.exists()

        # Restore to completed/stopped status
        if info.status == CaptureStatus.PROCESSING:
            info.status = CaptureStatus.COMPLETED
        _captures[capture_id] = info
        _save_metadata(info)

        logger.info("Post-processing complete for capture %s (health: %s)", capture_id, info.health_badge)

        # Run retention in background
        from . import capture_retention
        asyncio.create_task(capture_retention.enforce_retention())

    except Exception as e:
        # TimeoutError and CancelledError have empty str() in Python 3.11
        err_name = type(e).__name__
        err_detail = str(e) or "(no detail)"
        logger.error(
            "Post-processing failed for capture %s: %s: %s",
            capture_id, err_name, err_detail,
        )
        # Restore to completed status even if post-processing failed
        info = _captures.get(capture_id)
        if info and info.status == CaptureStatus.PROCESSING:
            info.status = CaptureStatus.COMPLETED
            info.error = f"Summary generation failed: {err_name}"
            _captures[capture_id] = info
            _save_metadata(info)


# ── CRUD Operations ──────────────────────────────────────────────────────────

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
        # Send SIGTERM (graceful stop — dumpcap flushes buffers)
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
    info = _load_metadata(capture_id)
    if info:
        _captures[capture_id] = info
    return info


def get_summary(capture_id: str) -> Optional[CaptureSummary]:
    """Load the generated CaptureSummary for a capture."""
    path = _summary_path(capture_id)
    if path.exists():
        try:
            return CaptureSummary.model_validate_json(path.read_text())
        except Exception as e:
            logger.warning("Failed to load summary for %s: %s", capture_id, e)
    return None


async def list_captures() -> List[CaptureInfo]:
    """List all captures (in-memory + on-disk)."""
    captures_dir = _captures_dir()
    async with _lock:
        for meta_file in captures_dir.glob("*.json"):
            if ".analysis." in meta_file.name or ".summary." in meta_file.name:
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

    # Stop if running
    if info.status == CaptureStatus.RUNNING:
        await stop_capture(capture_id)

    # Remove all capture files
    _metadata_path(capture_id).unlink(missing_ok=True)
    Path(info.pcap_path).unlink(missing_ok=True)
    _summary_path(capture_id).unlink(missing_ok=True)
    (_captures_dir() / f"{capture_id}.analysis.json").unlink(missing_ok=True)

    # Remove segments directory if it still exists
    seg_dir = _segments_dir(capture_id)
    if seg_dir.exists():
        shutil.rmtree(str(seg_dir), ignore_errors=True)

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
    """Get capture statistics — returns CaptureSummary JSON if available,
    falls back to legacy raw tshark extraction.

    This provides backward compatibility for v1 AI analysis while
    v2 analysis uses get_summary() directly.
    """
    # Try v2 summary first
    summary = get_summary(capture_id)
    if summary:
        return json.loads(summary.model_dump_json())

    # Fall back to legacy extraction for captures without summaries
    info = get_capture(capture_id)
    if not info:
        return {}

    if settings.mock_mode:
        return _mock_stats()

    if not Path(info.pcap_path).exists():
        return {}

    stats = {}

    # Legacy tshark extraction (v1 format)
    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "io,phs",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["protocol_hierarchy"] = result.stdout

    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "conv,tcp",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["tcp_conversations"] = result.stdout

    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "io,stat,1",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["io_stats"] = result.stdout

    result = await run(
        "tshark", "-r", info.pcap_path, "-q", "-z", "expert",
        sudo=True, check=False, timeout=60,
    )
    if result.success:
        stats["expert_info"] = result.stdout

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
    """Legacy mock stats for v1 compatibility."""
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
