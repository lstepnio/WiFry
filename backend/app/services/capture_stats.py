"""Deterministic capture statistics extraction via tshark.

Runs tshark queries against a completed pcap file and parses the output
into a typed CaptureSummary model.  All queries run with nice/ionice for
RPi 5 friendliness.

Design principles from rpi5-performance-guide.md:
- nice -n 10 / ionice -c2 -n7 on all post-processing
- Adaptive per-query timeout: 60s base, scales with file size
- Sequential execution (one tshark at a time) to avoid RAM spikes
- Page cache pre-warming: limited to <100 MB pcaps
- Minimised tshark passes: TCP health in single pass (not 8)
"""

import asyncio
import json
import logging
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from ..models.analysis_packs import AnalysisPack, PackConfig, ThresholdRule, get_pack_config
from ..models.capture import (
    AnomalyFlag,
    CaptureMeta,
    CaptureSummary,
    Conversation,
    DnsSummary,
    EndpointEntry,
    ExpertEntry,
    ExpertSummary,
    FocusFlow,
    HealthBadge,
    IcmpSummary,
    InterestAnnotations,
    InterestWindow,
    ProtocolBreakdown,
    ProtocolEntry,
    TcpHealth,
    ThroughputSample,
    ThroughputSummary,
    TlsHandshake,
    TlsSummary,
)
from ..utils.shell import CommandResult, run

logger = logging.getLogger(__name__)

# Resource control: only one post-processing pipeline at a time
_post_process_semaphore = asyncio.Semaphore(1)
_QUERY_TIMEOUT_BASE = 60  # seconds per tshark query (base)
_PIPELINE_TIMEOUT_BASE = 300  # total pipeline timeout (base)
_PREWARM_MAX_MB = 100  # skip page-cache prewarm above this size


def _adaptive_timeout(pcap_path: str, base: float = _QUERY_TIMEOUT_BASE) -> float:
    """Scale tshark timeout based on pcap file size.

    RPi 5 processes ~7 MB/s for stat queries and ~3 MB/s for field
    extraction.  For a 400 MB pcap, 60 s is nowhere near enough.
    """
    try:
        size_mb = Path(pcap_path).stat().st_size / (1024 * 1024)
        if size_mb > 200:
            return max(base, size_mb * 1.5)  # ~1.5 s per MB for very large
        elif size_mb > 50:
            return max(base, size_mb * 1.0)  # ~1 s per MB for large
        return base
    except OSError:
        return base


def _pipeline_timeout(pcap_path: str) -> float:
    """Scale total pipeline timeout based on pcap size."""
    try:
        size_mb = Path(pcap_path).stat().st_size / (1024 * 1024)
        if size_mb > 200:
            return max(_PIPELINE_TIMEOUT_BASE, size_mb * 10)  # ~10 s/MB
        elif size_mb > 50:
            return max(_PIPELINE_TIMEOUT_BASE, size_mb * 6)
        return _PIPELINE_TIMEOUT_BASE
    except OSError:
        return _PIPELINE_TIMEOUT_BASE


async def _tshark_query(pcap_path: str, *args: str, timeout: float = 0) -> CommandResult:
    """Run a tshark query with nice/ionice resource controls."""
    if settings.mock_mode:
        return CommandResult(returncode=0, stdout="", stderr="")

    if timeout <= 0:
        timeout = _adaptive_timeout(pcap_path)

    # Use nice + ionice for lower priority on RPi
    cmd_args = [
        "nice", "-n", "10",
        "ionice", "-c2", "-n7",
        "tshark", "-r", pcap_path,
        *args,
    ]
    return await run(*cmd_args, check=False, timeout=timeout)


async def _prewarm_cache(pcap_path: str) -> None:
    """Pre-warm page cache to avoid random I/O during queries.

    Skipped for files > _PREWARM_MAX_MB — catting a 400 MB pcap wastes
    too much time and pushes useful pages out of cache on the RPi.
    """
    if settings.mock_mode:
        return
    try:
        size_mb = Path(pcap_path).stat().st_size / (1024 * 1024)
        if size_mb > _PREWARM_MAX_MB:
            logger.info("Skipping prewarm for large pcap (%.0f MB)", size_mb)
            return
        await run("cat", pcap_path, check=False, timeout=60)
    except Exception:
        pass  # Non-critical


async def generate_summary(
    capture_id: str,
    pcap_path: str,
    pack: str = "custom",
    meta: Optional[CaptureMeta] = None,
) -> CaptureSummary:
    """Generate a CaptureSummary from a pcap file.

    Acquires the post-processing semaphore to prevent concurrent
    tshark processes from overwhelming the RPi.
    """
    if settings.mock_mode:
        return _mock_summary(capture_id, pack, meta)

    pcap = Path(pcap_path)
    if not pcap.exists():
        logger.warning("Pcap file not found: %s", pcap_path)
        return CaptureSummary(meta=meta or CaptureMeta(capture_id=capture_id, pack=pack))

    timeout = _pipeline_timeout(pcap_path)
    logger.info(
        "Starting summary pipeline for %s (%.1f MB, timeout=%ds)",
        capture_id,
        pcap.stat().st_size / (1024 * 1024),
        timeout,
    )
    async with _post_process_semaphore:
        return await asyncio.wait_for(
            _run_pipeline(capture_id, pcap_path, pack, meta),
            timeout=timeout,
        )


async def _run_pipeline(
    capture_id: str,
    pcap_path: str,
    pack: str,
    meta: Optional[CaptureMeta],
) -> CaptureSummary:
    """Execute the extraction pipeline sequentially."""
    if not meta:
        meta = CaptureMeta(capture_id=capture_id, pack=pack)

    # Pre-warm page cache
    await _prewarm_cache(pcap_path)

    # Determine which queries to run based on pack
    try:
        pack_enum = AnalysisPack(pack)
        pack_config = get_pack_config(pack_enum)
        query_set = set(pack_config.queries)
    except (ValueError, KeyError):
        query_set = {"protocol", "tcp", "io", "expert", "dns", "throughput", "endpoints"}

    summary = CaptureSummary(meta=meta)

    # Run queries sequentially to avoid RAM spikes
    if "protocol" in query_set:
        summary.protocol_breakdown = await _extract_protocol_hierarchy(pcap_path)

    if "tcp" in query_set:
        summary.tcp_health = await _extract_tcp_health(pcap_path)
        convs = await _extract_conversations(pcap_path)
        summary.conversations = convs[:20]  # Cap at 20 conversations

    if "io" in query_set:
        summary.throughput = await _extract_throughput(pcap_path)

    if "expert" in query_set:
        summary.expert = await _extract_expert_info(pcap_path)

    if "dns" in query_set:
        summary.dns = await _extract_dns(pcap_path)

    if "icmp" in query_set:
        summary.icmp = await _extract_icmp(pcap_path)

    if "endpoints" in query_set:
        endpoints = await _extract_endpoints(pcap_path)
        summary.endpoints = endpoints[:30]  # Cap at 30 endpoints

    if "tls" in query_set:
        summary.tls = await _extract_tls(pcap_path)

    if "throughput" in query_set and summary.throughput is None:
        summary.throughput = await _extract_throughput(pcap_path)

    # Run interest detection
    try:
        summary.interest = _detect_interest(summary, pack)
    except Exception as e:
        logger.warning("Interest detection failed: %s", e)

    logger.info("Summary generated for capture %s: %d bytes JSON",
                capture_id, len(summary.model_dump_json()))
    return summary


# ── Individual Extractors ─────────────────────────────────────────────────────

async def _extract_protocol_hierarchy(pcap_path: str) -> ProtocolBreakdown:
    """Extract protocol hierarchy via tshark -z io,phs."""
    result = await _tshark_query(pcap_path, "-q", "-z", "io,phs")
    breakdown = ProtocolBreakdown()

    if not result.success or not result.stdout:
        return breakdown

    total_frames = 0
    unencrypted_bytes = 0
    encrypted_bytes = 0

    for line in result.stdout.splitlines():
        # Parse lines like "  eth                  frames:1000 bytes:650000"
        match = re.match(r"^\s+(\S+)\s+frames:(\d+)\s+bytes:(\d+)", line)
        if match:
            name = match.group(1)
            frames = int(match.group(2))
            bytes_val = int(match.group(3))

            indent = len(line) - len(line.lstrip())
            if indent <= 2:  # Top-level
                total_frames = max(total_frames, frames)

            breakdown.protocols.append(ProtocolEntry(
                name=name, frames=frames, bytes=bytes_val
            ))

            # Track encrypted vs unencrypted
            if name.lower() in ("tls", "ssl", "dtls"):
                encrypted_bytes += bytes_val
            elif name.lower() in ("http", "ftp", "telnet", "smtp", "pop", "imap"):
                unencrypted_bytes += bytes_val

    breakdown.total_frames = total_frames
    if breakdown.protocols:
        breakdown.total_bytes = breakdown.protocols[0].bytes if breakdown.protocols else 0

    # Calculate percentages
    if breakdown.total_bytes > 0:
        for p in breakdown.protocols:
            p.pct = round(p.bytes / breakdown.total_bytes * 100, 1)
        total_app = encrypted_bytes + unencrypted_bytes
        if total_app > 0:
            breakdown.unencrypted_pct = round(unencrypted_bytes / total_app * 100, 1)

    return breakdown


async def _extract_tcp_health(pcap_path: str) -> TcpHealth:
    """Extract TCP health metrics in a SINGLE tshark pass.

    Previous implementation ran 8 separate tshark passes, each scanning
    the entire pcap.  For a 400 MB file on RPi that took 8+ minutes.
    This version extracts all TCP analysis flags in one pass.
    """
    health = TcpHealth()

    # Single pass: extract all TCP frames with analysis flags
    result = await _tshark_query(
        pcap_path,
        "-Y", "tcp",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "tcp.analysis.retransmission",
        "-e", "tcp.analysis.fast_retransmission",
        "-e", "tcp.analysis.duplicate_ack",
        "-e", "tcp.analysis.zero_window",
        "-e", "tcp.flags.reset",
        "-e", "tcp.analysis.out_of_order",
        "-e", "tcp.analysis.window_full",
        "-E", "separator=|",
    )

    if not result.success or not result.stdout:
        return health

    for line in result.stdout.strip().splitlines():
        health.total_segments += 1
        parts = line.split("|")
        # Each field is empty if flag not set, or has a value if set
        if len(parts) >= 8:
            if parts[1].strip():  # retransmission
                health.retransmission_count += 1
            if parts[2].strip():  # fast_retransmission
                health.fast_retransmission_count += 1
            if parts[3].strip():  # duplicate_ack
                health.duplicate_ack_count += 1
            if parts[4].strip():  # zero_window
                health.zero_window_count += 1
            if parts[5].strip() == "1":  # rst flag
                health.rst_count += 1
            if parts[6].strip():  # out_of_order
                health.out_of_order_count += 1
            if parts[7].strip():  # window_full
                health.window_full_count += 1

    # Calculate retransmission percentage
    if health.total_segments > 0:
        health.retransmission_pct = round(
            health.retransmission_count / health.total_segments * 100, 2
        )

    return health


async def _extract_conversations(pcap_path: str) -> List[Conversation]:
    """Extract TCP conversation table."""
    result = await _tshark_query(pcap_path, "-q", "-z", "conv,tcp")
    conversations: List[Conversation] = []

    if not result.success or not result.stdout:
        return conversations

    for line in result.stdout.splitlines():
        # Parse conversation lines:
        # 192.168.4.10:54321 <-> 104.16.132.229:443  800 550000 ...
        parts = line.strip().split()
        if len(parts) < 5 or "<->" not in parts:
            continue

        try:
            arrow_idx = parts.index("<->")
            src_parts = parts[arrow_idx - 1].rsplit(":", 1)
            dst_parts = parts[arrow_idx + 1].rsplit(":", 1)

            if len(src_parts) != 2 or len(dst_parts) != 2:
                continue

            # Fields after dst: frames_a_to_b bytes_a_to_b frames_b_to_a bytes_b_to_a frames_total bytes_total rel_start duration
            remaining = parts[arrow_idx + 2:]
            total_frames = int(remaining[4]) if len(remaining) > 4 else 0
            total_bytes = int(remaining[5]) if len(remaining) > 5 else 0
            duration = float(remaining[7]) if len(remaining) > 7 else 0.0

            conv = Conversation(
                src=src_parts[0],
                src_port=int(src_parts[1]),
                dst=dst_parts[0],
                dst_port=int(dst_parts[1]),
                protocol="tcp",
                frames=total_frames,
                bytes=total_bytes,
                duration_secs=duration,
                bps=round(total_bytes * 8 / duration) if duration > 0 else 0,
            )
            conversations.append(conv)
        except (ValueError, IndexError):
            continue

    # Sort by bytes descending
    conversations.sort(key=lambda c: c.bytes, reverse=True)
    return conversations


async def _extract_throughput(pcap_path: str) -> ThroughputSummary:
    """Extract IO stats in 1-second intervals."""
    result = await _tshark_query(pcap_path, "-q", "-z", "io,stat,1")
    summary = ThroughputSummary()

    if not result.success or not result.stdout:
        return summary

    samples: List[ThroughputSample] = []
    for line in result.stdout.splitlines():
        # Parse lines like "| 0.000000 <> 1.000000 | 120 | 80000 |"
        # or "0 <> 1   120    80000"
        match = re.search(r"(\d+\.?\d*)\s*<>\s*(\d+\.?\d*)\s*\|\s*(\d+)\s*\|\s*(\d+)", line)
        if not match:
            match = re.search(r"(\d+\.?\d*)\s*<>\s*(\d+\.?\d*)\s+(\d+)\s+(\d+)", line)
        if match:
            start = float(match.group(1))
            end = float(match.group(2))
            frames = int(match.group(3))
            bytes_val = int(match.group(4))
            duration = end - start if end > start else 1.0
            bps = round(bytes_val * 8 / duration)

            samples.append(ThroughputSample(
                interval_start=start,
                interval_end=end,
                frames=frames,
                bytes=bytes_val,
                bps=bps,
            ))

    summary.samples = samples

    if samples:
        bps_values = [s.bps for s in samples if s.bps > 0]
        if bps_values:
            summary.avg_bps = round(statistics.mean(bps_values))
            summary.max_bps = max(bps_values)
            summary.min_bps = min(bps_values)
            if summary.avg_bps > 0:
                stdev = statistics.stdev(bps_values) if len(bps_values) > 1 else 0
                summary.coefficient_of_variation = round(stdev / summary.avg_bps, 3)

    return summary


async def _extract_expert_info(pcap_path: str) -> ExpertSummary:
    """Extract tshark expert info summary."""
    result = await _tshark_query(pcap_path, "-q", "-z", "expert")
    summary = ExpertSummary()

    if not result.success or not result.stdout:
        return summary

    entries: List[ExpertEntry] = []
    for line in result.stdout.splitlines():
        # "Severity: Warning  Group: Sequence  Summary: TCP Retransmission  Count: 32"
        sev_match = re.search(r"Severity:\s*(\w+)", line)
        grp_match = re.search(r"Group:\s*(\w+)", line)
        sum_match = re.search(r"Summary:\s*(.+?)(?:\s+Count:|\s*$)", line)
        cnt_match = re.search(r"Count:\s*(\d+)", line)

        if sev_match and sum_match:
            entry = ExpertEntry(
                severity=sev_match.group(1).lower(),
                group=grp_match.group(1) if grp_match else "",
                summary=sum_match.group(1).strip(),
                count=int(cnt_match.group(1)) if cnt_match else 1,
            )
            entries.append(entry)

            if entry.severity == "error":
                summary.error_count += entry.count
            elif entry.severity == "warning":
                summary.warning_count += entry.count
            elif entry.severity == "note":
                summary.note_count += entry.count
            elif entry.severity == "chat":
                summary.chat_count += entry.count

    summary.entries = entries
    return summary


async def _extract_dns(pcap_path: str) -> DnsSummary:
    """Extract DNS statistics in a single tshark pass."""
    summary = DnsSummary()

    # Single pass: extract all DNS frames (queries + responses)
    result = await _tshark_query(
        pcap_path,
        "-Y", "dns",
        "-T", "fields",
        "-e", "dns.flags.response",
        "-e", "dns.qry.name",
        "-e", "dns.flags.rcode",
        "-e", "dns.time",
        "-E", "separator=|",
    )
    if not result.success or not result.stdout:
        return summary

    domains: Dict[str, int] = {}
    latencies: List[float] = []

    for line in result.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 2:
            continue

        is_response = parts[0].strip() == "1"
        domain = parts[1].strip() if len(parts) > 1 else ""

        if not is_response:
            # DNS query
            summary.total_queries += 1
            if domain:
                domains[domain] = domains.get(domain, 0) + 1
        else:
            # DNS response
            summary.total_responses += 1
            if len(parts) >= 3:
                rcode = parts[2].strip()
                if rcode == "3":  # NXDOMAIN
                    summary.nxdomain_count += 1
                elif rcode == "2":  # SERVFAIL
                    summary.servfail_count += 1
            if len(parts) >= 4 and parts[3].strip():
                try:
                    lat_ms = float(parts[3].strip()) * 1000
                    latencies.append(lat_ms)
                except ValueError:
                    pass

    summary.unique_domains = len(domains)
    summary.top_domains = [
        {"domain": d, "count": c}
        for d, c in sorted(domains.items(), key=lambda x: -x[1])[:10]
    ]

    if latencies:
        summary.avg_latency_ms = round(statistics.mean(latencies), 1)
        summary.max_latency_ms = round(max(latencies), 1)

    # Estimate timeouts (queries with no matching response)
    if summary.total_queries > summary.total_responses:
        summary.timeout_count = summary.total_queries - summary.total_responses

    return summary


async def _extract_icmp(pcap_path: str) -> IcmpSummary:
    """Extract ICMP statistics."""
    summary = IcmpSummary()

    result = await _tshark_query(
        pcap_path,
        "-Y", "icmp",
        "-T", "fields",
        "-e", "icmp.type",
        "-e", "icmp.resptime",
        "-E", "separator=|",
    )
    if not result.success or not result.stdout:
        return summary

    rtts: List[float] = []
    for line in result.stdout.strip().splitlines():
        summary.total_count += 1
        parts = line.split("|")
        icmp_type = parts[0].strip() if parts else ""

        if icmp_type == "8":
            summary.echo_request_count += 1
        elif icmp_type == "0":
            summary.echo_reply_count += 1
        elif icmp_type == "3":
            summary.unreachable_count += 1
        elif icmp_type == "11":
            summary.ttl_exceeded_count += 1

        if len(parts) >= 2 and parts[1].strip():
            try:
                rtts.append(float(parts[1].strip()))
            except ValueError:
                pass

    if rtts:
        summary.avg_rtt_ms = round(statistics.mean(rtts), 2)

    return summary


async def _extract_endpoints(pcap_path: str) -> List[EndpointEntry]:
    """Extract IP endpoint statistics."""
    result = await _tshark_query(pcap_path, "-q", "-z", "endpoints,ip")
    endpoints: List[EndpointEntry] = []

    if not result.success or not result.stdout:
        return endpoints

    for line in result.stdout.splitlines():
        # Parse lines like "192.168.4.10  800  550000  400  300000  400  250000"
        parts = line.strip().split()
        if len(parts) < 3:
            continue

        # First field should be an IP address
        ip = parts[0]
        if not re.match(r"\d+\.\d+\.\d+\.\d+", ip):
            continue

        try:
            frames = int(parts[1])
            bytes_val = int(parts[2])
            tx_frames = int(parts[3]) if len(parts) > 3 else 0
            rx_frames = int(parts[5]) if len(parts) > 5 else 0

            endpoints.append(EndpointEntry(
                ip=ip,
                frames=frames,
                bytes=bytes_val,
                tx_frames=tx_frames,
                rx_frames=rx_frames,
            ))
        except (ValueError, IndexError):
            continue

    endpoints.sort(key=lambda e: e.bytes, reverse=True)
    return endpoints


async def _extract_tls(pcap_path: str) -> TlsSummary:
    """Extract TLS handshake and alert statistics in a single pass."""
    summary = TlsSummary()

    # Single pass: extract TLS handshakes (ServerHello) and alerts
    result = await _tshark_query(
        pcap_path,
        "-Y", "tls.handshake.type == 2 || tls.alert_message",
        "-T", "fields",
        "-e", "tls.handshake.type",
        "-e", "ip.dst",
        "-e", "tls.handshake.extensions_server_name",
        "-e", "tls.record.version",
        "-e", "tls.handshake.ciphersuite",
        "-e", "tls.alert_message",
        "-E", "separator=|",
    )
    if not result.success or not result.stdout:
        return summary

    versions: Dict[str, int] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split("|")
        hs_type = parts[0].strip() if parts else ""
        alert = parts[5].strip() if len(parts) > 5 else ""

        if hs_type == "2":  # ServerHello
            summary.total_handshakes += 1
            version = parts[3].strip() if len(parts) > 3 else "unknown"
            versions[version] = versions.get(version, 0) + 1
            hs = TlsHandshake(
                server=parts[1].strip() if len(parts) > 1 else "",
                sni=parts[2].strip() if len(parts) > 2 else "",
                version=version,
                cipher=parts[4].strip() if len(parts) > 4 else "",
            )
            summary.handshakes.append(hs)

        if alert:  # TLS alert
            summary.handshake_failure_count += 1

    summary.versions = versions
    # Cap handshakes list
    summary.handshakes = summary.handshakes[:20]
    return summary


# ── Interest Detection ────────────────────────────────────────────────────────

def _get_metric_value(summary: CaptureSummary, metric_path: str) -> Optional[float]:
    """Resolve a dotted metric path to a numeric value from the summary."""
    parts = metric_path.split(".")
    obj: Any = summary

    for part in parts:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None

    if isinstance(obj, (int, float)):
        return float(obj)
    return None


def _check_threshold(value: float, rule: ThresholdRule) -> bool:
    """Check if a value violates a threshold rule."""
    ops = {
        "gt": lambda v, t: v > t,
        "lt": lambda v, t: v < t,
        "gte": lambda v, t: v >= t,
        "lte": lambda v, t: v <= t,
        "eq": lambda v, t: v == t,
    }
    op = ops.get(rule.operator, lambda v, t: False)
    return op(value, rule.value)


def _detect_interest(summary: CaptureSummary, pack: str) -> InterestAnnotations:
    """Run threshold-based interest detection."""
    annotations = InterestAnnotations()

    # Get pack thresholds
    try:
        pack_enum = AnalysisPack(pack)
        pack_config = get_pack_config(pack_enum)
        thresholds = pack_config.thresholds
    except (ValueError, KeyError):
        thresholds = []

    # Check each threshold
    for rule in thresholds:
        value = _get_metric_value(summary, rule.metric)
        if value is not None and _check_threshold(value, rule):
            annotations.anomaly_flags.append(AnomalyFlag(
                metric=rule.metric,
                value=value,
                threshold=rule.value,
                severity=rule.severity,
                label=rule.label,
            ))

    # Detect interesting time windows (throughput dips)
    if summary.throughput and summary.throughput.samples:
        avg = summary.throughput.avg_bps
        if avg > 0:
            for sample in summary.throughput.samples:
                if sample.bps < avg * 0.3 and sample.bps > 0:  # >70% drop
                    annotations.interest_windows.append(InterestWindow(
                        start_secs=sample.interval_start,
                        end_secs=sample.interval_end,
                        reason=f"Throughput dip: {sample.bps:,.0f} bps vs avg {avg:,.0f} bps",
                    ))

    # Identify focus flows (conversations with issues)
    if summary.conversations and summary.tcp_health:
        retx_pct = summary.tcp_health.retransmission_pct
        if retx_pct > 1.0:
            # Flag top flows by bytes as potential contributors
            for conv in summary.conversations[:5]:
                annotations.focus_flows.append(FocusFlow(
                    src=f"{conv.src}:{conv.src_port}",
                    dst=f"{conv.dst}:{conv.dst_port}",
                    reason=f"Top flow ({conv.bytes:,} bytes) during {retx_pct}% retransmission rate",
                ))

    # Determine health badge
    has_critical = any(f.severity == "critical" for f in annotations.anomaly_flags)
    has_high = any(f.severity == "high" for f in annotations.anomaly_flags)
    has_medium = any(f.severity == "medium" for f in annotations.anomaly_flags)

    min_packets = summary.meta.total_packets if summary.meta else 0
    if min_packets < 10:
        annotations.health_badge = HealthBadge.INSUFFICIENT
    elif has_critical or has_high:
        annotations.health_badge = HealthBadge.UNHEALTHY
    elif has_medium:
        annotations.health_badge = HealthBadge.DEGRADED
    else:
        annotations.health_badge = HealthBadge.HEALTHY

    return annotations


# ── Mock Data ────────────────────────────────────────────────────────────────

def _mock_summary(capture_id: str, pack: str, meta: Optional[CaptureMeta] = None) -> CaptureSummary:
    """Return a realistic mock summary for development."""
    if not meta:
        meta = CaptureMeta(
            capture_id=capture_id,
            pack=pack,
            interface="wlan0",
            duration_secs=30.0,
            total_packets=1000,
            total_bytes=650000,
            pcap_file_bytes=12345,
        )

    return CaptureSummary(
        meta=meta,
        protocol_breakdown=ProtocolBreakdown(
            total_frames=1000,
            total_bytes=650000,
            protocols=[
                ProtocolEntry(name="eth", frames=1000, bytes=650000, pct=100.0),
                ProtocolEntry(name="ip", frames=980, bytes=640000, pct=98.5),
                ProtocolEntry(name="tcp", frames=900, bytes=600000, pct=92.3),
                ProtocolEntry(name="tls", frames=800, bytes=550000, pct=84.6),
                ProtocolEntry(name="udp", frames=60, bytes=30000, pct=4.6),
                ProtocolEntry(name="dns", frames=40, bytes=5000, pct=0.8),
                ProtocolEntry(name="icmp", frames=20, bytes=10000, pct=1.5),
            ],
            unencrypted_pct=0.0,
        ),
        tcp_health=TcpHealth(
            total_segments=900,
            retransmission_count=29,
            retransmission_pct=3.2,
            fast_retransmission_count=8,
            duplicate_ack_count=15,
            zero_window_count=0,
            rst_count=2,
            out_of_order_count=3,
            window_full_count=0,
        ),
        conversations=[
            Conversation(
                src="192.168.4.10", src_port=54321,
                dst="104.16.132.229", dst_port=443,
                protocol="tcp", frames=800, bytes=550000,
                duration_secs=28.5, bps=154386,
            ),
            Conversation(
                src="192.168.4.10", src_port=54322,
                dst="192.168.1.1", dst_port=53,
                protocol="tcp", frames=40, bytes=5000,
                duration_secs=2.1, bps=19048,
            ),
        ],
        dns=DnsSummary(
            total_queries=3,
            total_responses=3,
            unique_domains=2,
            nxdomain_count=0,
            servfail_count=0,
            timeout_count=0,
            avg_latency_ms=12.5,
            max_latency_ms=25.0,
            top_domains=[
                {"domain": "cdn.example.com", "count": 2},
                {"domain": "api.example.com", "count": 1},
            ],
        ),
        throughput=ThroughputSummary(
            samples=[
                ThroughputSample(interval_start=0, interval_end=1, frames=120, bytes=80000, bps=640000),
                ThroughputSample(interval_start=1, interval_end=2, frames=135, bytes=90000, bps=720000),
                ThroughputSample(interval_start=2, interval_end=3, frames=98, bytes=65000, bps=520000),
                ThroughputSample(interval_start=3, interval_end=4, frames=150, bytes=100000, bps=800000),
            ],
            avg_bps=670000,
            max_bps=800000,
            min_bps=520000,
            coefficient_of_variation=0.16,
        ),
        expert=ExpertSummary(
            entries=[
                ExpertEntry(severity="warning", group="Sequence", summary="TCP Retransmission", count=29),
                ExpertEntry(severity="note", group="Sequence", summary="TCP Dup ACK", count=15),
                ExpertEntry(severity="chat", group="Sequence", summary="TCP Window Update", count=8),
            ],
            warning_count=29,
            note_count=15,
            chat_count=8,
        ),
        icmp=IcmpSummary(
            total_count=20,
            echo_request_count=10,
            echo_reply_count=10,
            avg_rtt_ms=8.5,
        ),
        endpoints=[
            EndpointEntry(ip="192.168.4.10", frames=800, bytes=550000, tx_frames=400, rx_frames=400),
            EndpointEntry(ip="104.16.132.229", frames=800, bytes=550000, tx_frames=400, rx_frames=400),
        ],
        interest=InterestAnnotations(
            anomaly_flags=[
                AnomalyFlag(
                    metric="tcp_health.retransmission_pct",
                    value=3.2,
                    threshold=2.0,
                    severity="high",
                    label="High TCP retransmission rate",
                ),
            ],
            focus_flows=[
                FocusFlow(
                    src="192.168.4.10:54321",
                    dst="104.16.132.229:443",
                    reason="Top flow (550,000 bytes) during 3.2% retransmission rate",
                ),
            ],
            health_badge=HealthBadge.UNHEALTHY,
        ),
    )
