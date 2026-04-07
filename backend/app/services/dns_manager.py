"""DNS simulation service via CoreDNS.

Manages CoreDNS as a programmable DNS resolver sitting between
dnsmasq (DHCP + client-facing DNS on port 53) and upstream resolvers.

Architecture:
  STB → dnsmasq:53 → CoreDNS:5053 → upstream (1.1.1.1, etc.)

CoreDNS Corefile is dynamically generated from the DnsConfig model.
Impairments are implemented via CoreDNS plugins:
  - forward: upstream resolution with protocol selection
  - template: NXDOMAIN injection for specific domains
  - erratic: random SERVFAIL responses
  - hosts: record overrides (A, AAAA, CNAME)
  - log: query logging
  - cache: with TTL override support
"""

import asyncio
import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

from ..config import settings
from ..models.dns import (
    UPSTREAM_PROVIDERS,
    DnsConfig,
    DnsOverride,
    DnsQueryLogEntry,
    DnsStatus,
)
from ..utils.shell import run, sudo_write

logger = logging.getLogger(__name__)

COREDNS_DIR = Path("/var/lib/wifry/coredns") if not settings.mock_mode else Path("/tmp/wifry-coredns")
COREFILE_PATH = COREDNS_DIR / "Corefile"
HOSTS_PATH = COREDNS_DIR / "hosts"
CONFIG_PATH = COREDNS_DIR / "dns_config.json"

_config: Optional[DnsConfig] = None
_process: Optional[asyncio.subprocess.Process] = None
_query_log: Deque[DnsQueryLogEntry] = deque(maxlen=1000)
_query_count: int = 0


def _ensure_dir() -> Path:
    COREDNS_DIR.mkdir(parents=True, exist_ok=True)
    return COREDNS_DIR


# --- Configuration ---

def get_config() -> DnsConfig:
    """Get current DNS config (from memory or disk)."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def _load_config() -> DnsConfig:
    if CONFIG_PATH.exists():
        try:
            return DnsConfig.model_validate_json(CONFIG_PATH.read_text())
        except Exception:
            pass
    return DnsConfig()


def _save_config(config: DnsConfig) -> None:
    _ensure_dir()
    CONFIG_PATH.write_text(config.model_dump_json(indent=2))


# --- CoreDNS lifecycle ---

async def apply_config(config: DnsConfig) -> DnsStatus:
    """Apply DNS config: generate Corefile, restart CoreDNS, update dnsmasq."""
    global _config

    _config = config
    _save_config(config)

    if config.enabled:
        _generate_corefile(config)
        _generate_hosts_file(config.overrides)
        await _restart_coredns(config)
        await _point_dnsmasq_to_coredns(config.listen_port)
    else:
        await _stop_coredns()
        await _point_dnsmasq_to_upstream(config)

    # Log to active session
    from . import session_manager
    sid = session_manager.get_active_session_id()
    if sid:
        active_impairments = _get_active_impairments(config)
        session_manager.log_impairment(
            sid,
            label=f"DNS: {'enabled' if config.enabled else 'disabled'}" +
                  (f" ({', '.join(active_impairments)})" if active_impairments else ""),
        )

    logger.info("DNS config applied (enabled=%s)", config.enabled)
    return get_status()


async def enable() -> DnsStatus:
    """Enable DNS simulation with current config."""
    config = get_config()
    config.enabled = True
    return await apply_config(config)


async def disable() -> DnsStatus:
    """Disable DNS simulation, revert to direct upstream."""
    config = get_config()
    config.enabled = False
    return await apply_config(config)


def get_status() -> DnsStatus:
    """Get current DNS status."""
    config = get_config()
    running = _process is not None and _process.returncode is None if not settings.mock_mode else config.enabled

    resolvers = config.upstream.resolvers
    healthy = [r for r in resolvers if r.healthy]

    return DnsStatus(
        enabled=config.enabled,
        running=running,
        listen_port=config.listen_port,
        upstream_provider=config.upstream.provider,
        upstream_protocol=config.upstream.protocol,
        resolver_count=len(resolvers) if resolvers else 0,
        healthy_resolvers=len(healthy) if resolvers else 0,
        override_count=len(config.overrides),
        impairments_active=_get_active_impairments(config),
        query_count=_query_count,
    )


# --- Overrides ---

def add_override(override: DnsOverride) -> List[DnsOverride]:
    """Add a DNS record override."""
    config = get_config()
    # Remove existing override for same domain+type
    config.overrides = [o for o in config.overrides if not (o.domain == override.domain and o.record_type == override.record_type)]
    config.overrides.append(override)
    _save_config(config)
    return config.overrides


def remove_override(domain: str) -> List[DnsOverride]:
    """Remove all overrides for a domain."""
    config = get_config()
    config.overrides = [o for o in config.overrides if o.domain != domain]
    _save_config(config)
    return config.overrides


def get_overrides() -> List[DnsOverride]:
    return get_config().overrides


# --- Query log ---

def get_query_log(limit: int = 100) -> List[DnsQueryLogEntry]:
    """Get recent DNS queries."""
    if settings.mock_mode and not _query_log:
        return _mock_query_log()
    return list(_query_log)[-limit:]


# --- Corefile generation ---

def _generate_corefile(config: DnsConfig) -> None:
    """Generate CoreDNS Corefile from config."""
    _ensure_dir()

    blocks = []

    # NXDOMAIN injection: separate server blocks per domain
    # These MUST be before the main catch-all block so CoreDNS
    # matches them first (more specific zones take priority)
    for domain_pattern in config.impairments.nxdomain_domains:
        clean = domain_pattern.lstrip("*").lstrip(".")
        # Server block for this domain — no forward, just return NXDOMAIN
        nxblock = f"{clean}:{config.listen_port} {{\n"
        if config.log_queries:
            nxblock += "    log\n"
        nxblock += "    template IN ANY {\n"
        nxblock += "        rcode NXDOMAIN\n"
        nxblock += '        authority "{.}. 60 IN SOA ns.wifry. admin.wifry. 0 0 0 0 60"\n'
        nxblock += "    }\n"
        nxblock += "}\n"
        blocks.append(nxblock)

    # Main server block (catch-all)
    main_block = f".:{ config.listen_port} {{\n"

    # Logging
    if config.log_queries:
        main_block += "    log\n"

    # Record overrides via hosts file
    if config.overrides:
        main_block += f"    hosts {HOSTS_PATH} {{\n"
        main_block += "        fallthrough\n"
        main_block += "    }\n"

    # Random SERVFAIL via erratic plugin
    if config.impairments.servfail_rate_pct > 0:
        # erratic plugin drops/corrupts a fraction of responses
        drop_amount = max(1, int(100 / config.impairments.servfail_rate_pct))
        main_block += f"    erratic {{\n"
        main_block += f"        drop {drop_amount}\n"
        main_block += f"    }}\n"

    # Cache with TTL override
    if config.impairments.ttl_override > 0:
        main_block += f"    cache {config.impairments.ttl_override} {{\n"
        main_block += f"        success {config.impairments.ttl_override}\n"
        main_block += f"        denial {config.impairments.ttl_override}\n"
        main_block += f"    }}\n"
    else:
        main_block += "    cache 30\n"

    # Upstream forwarding
    upstream_servers = _resolve_upstream(config)
    if upstream_servers:
        main_block += f"    forward . {' '.join(upstream_servers)}"
        if config.upstream.protocol == "dot":
            # TLS server name needed for DoT
            tls_name = _get_tls_servername(config)
            if tls_name:
                main_block += f" {{\n        tls_servername {tls_name}\n    }}"
        main_block += "\n"

    # Errors
    main_block += "    errors\n"
    main_block += "}\n"

    blocks.append(main_block)

    corefile = "\n".join(blocks)
    COREFILE_PATH.write_text(corefile)
    logger.info("Generated Corefile at %s", COREFILE_PATH)


def _generate_hosts_file(overrides: List[DnsOverride]) -> None:
    """Generate hosts file for DNS record overrides."""
    _ensure_dir()
    lines = []
    for o in overrides:
        if o.record_type in ("A", "AAAA"):
            lines.append(f"{o.value} {o.domain}")
        elif o.record_type == "CNAME":
            # CoreDNS hosts file doesn't support CNAME directly,
            # but we can add it as a rewrite (handled in template)
            lines.append(f"# CNAME: {o.domain} -> {o.value}")

    HOSTS_PATH.write_text("\n".join(lines) + "\n")


def _resolve_upstream(config: DnsConfig) -> List[str]:
    """Resolve upstream DNS servers from provider + protocol config.

    For 'multi' provider: uses the explicit resolvers list, filtering out
    unhealthy ones (simulates primary failure with secondary responding).
    """
    if config.upstream.provider == "multi" and config.upstream.resolvers:
        # Multi-resolver mode: only include healthy resolvers
        healthy = [r for r in config.upstream.resolvers if r.healthy]
        if not healthy:
            logger.warning("All resolvers marked unhealthy — DNS will fail for all queries")
            return []
        return [r.address for r in healthy]

    if config.upstream.provider == "dhcp":
        return _get_dhcp_dns_servers()

    if config.upstream.provider == "custom":
        if config.upstream.protocol == "dot":
            return [f"tls://{s}" for s in config.upstream.custom_servers]
        return config.upstream.custom_servers

    provider = UPSTREAM_PROVIDERS.get(config.upstream.provider, UPSTREAM_PROVIDERS["cloudflare"])
    protocol = config.upstream.protocol

    if protocol == "doh":
        return provider.get("doh", provider["plain"])
    elif protocol == "dot":
        return provider.get("dot", provider["plain"])
    return provider.get("plain", ["8.8.8.8"])


def _get_dhcp_dns_servers() -> List[str]:
    """Read DNS servers assigned by DHCP from /etc/resolv.conf."""
    try:
        resolv = Path("/etc/resolv.conf").read_text()
        servers = []
        for line in resolv.splitlines():
            if line.strip().startswith("nameserver"):
                parts = line.split()
                if len(parts) >= 2 and parts[1] not in ("127.0.0.1", "::1"):
                    servers.append(parts[1])
        return servers if servers else ["8.8.8.8"]
    except Exception:
        return ["8.8.8.8"]


def _get_tls_servername(config: DnsConfig) -> str:
    """Get TLS server name for DoT."""
    names = {"cloudflare": "cloudflare-dns.com", "google": "dns.google", "quad9": "dns.quad9.net"}
    return names.get(config.upstream.provider, "")


# --- CoreDNS process management ---

async def _restart_coredns(config: DnsConfig) -> None:
    """Start or restart CoreDNS."""
    global _process

    await _stop_coredns()

    if settings.mock_mode:
        logger.info("Mock: CoreDNS would start on port %d", config.listen_port)
        return

    binary = settings.coredns_binary
    _process = await asyncio.create_subprocess_exec(
        binary, "-conf", str(COREFILE_PATH),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Monitor for query log parsing
    if config.log_queries:
        asyncio.create_task(_parse_coredns_log())

    logger.info("CoreDNS started (PID %s) on port %d", _process.pid, config.listen_port)


async def _stop_coredns() -> None:
    """Stop CoreDNS if running."""
    global _process

    if _process and _process.returncode is None:
        _process.terminate()
        try:
            await asyncio.wait_for(_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _process.kill()
        logger.info("CoreDNS stopped")

    _process = None


async def _parse_coredns_log() -> None:
    """Background task to parse CoreDNS log output for query log."""
    global _query_count

    if not _process or not _process.stdout:
        return

    try:
        while True:
            line_bytes = await _process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()

            entry = _parse_log_line(line)
            if entry:
                _query_log.append(entry)
                _query_count += 1

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug("CoreDNS log parser error: %s", e)


def _parse_log_line(line: str) -> Optional[DnsQueryLogEntry]:
    """Parse a CoreDNS log line into a query entry."""
    # CoreDNS log format: [INFO] 192.168.4.10:12345 - 12345 "A IN example.com. udp ..." ...
    match = re.search(r'(\d+\.\d+\.\d+\.\d+):\d+\s.*?"(\w+)\s+IN\s+(\S+)', line)
    if match:
        return DnsQueryLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            client_ip=match.group(1),
            query_type=match.group(2),
            domain=match.group(3).rstrip("."),
        )
    return None


# --- dnsmasq integration ---

async def _point_dnsmasq_to_coredns(port: int) -> None:
    """Update dnsmasq to forward DNS to CoreDNS."""
    if settings.mock_mode:
        logger.info("Mock: dnsmasq would forward to 127.0.0.1#%d", port)
        return

    conf_path = "/etc/dnsmasq.d/wifry-dns.conf"
    await sudo_write(conf_path, f"server=127.0.0.1#{port}\nno-resolv\n")
    # Restart (not reload) to flush dnsmasq cache so new DNS rules take effect
    await run("systemctl", "restart", "dnsmasq", sudo=True, check=False)
    logger.info("dnsmasq forwarding to CoreDNS on port %d", port)


async def _point_dnsmasq_to_upstream(config: DnsConfig) -> None:
    """Revert dnsmasq to forward directly to upstream."""
    if settings.mock_mode:
        logger.info("Mock: dnsmasq would forward to upstream directly")
        return

    servers = _resolve_upstream(config)
    # Only use plain DNS servers for dnsmasq (it doesn't support DoH/DoT)
    plain_servers = [s for s in servers if not s.startswith("tls://") and not s.startswith("https://")]
    if not plain_servers:
        plain_servers = ["8.8.8.8"]

    conf_path = "/etc/dnsmasq.d/wifry-dns.conf"
    lines = [f"server={s}" for s in plain_servers]
    lines.append("no-resolv")
    await sudo_write(conf_path, "\n".join(lines) + "\n")
    await run("systemctl", "reload", "dnsmasq", sudo=True, check=False)
    logger.info("dnsmasq forwarding directly to %s", plain_servers)


# --- Helpers ---

def _get_active_impairments(config: DnsConfig) -> List[str]:
    """List active impairment types."""
    active = []
    imp = config.impairments
    if imp.delay_ms > 0:
        active.append(f"delay:{imp.delay_ms}ms")
    if imp.failure_rate_pct > 0:
        active.append(f"drop:{imp.failure_rate_pct}%")
    if imp.servfail_rate_pct > 0:
        active.append(f"servfail:{imp.servfail_rate_pct}%")
    if imp.nxdomain_domains:
        active.append(f"nxdomain:{len(imp.nxdomain_domains)} patterns")
    if imp.ttl_override > 0:
        active.append(f"ttl:{imp.ttl_override}s")
    return active


def _mock_query_log() -> List[DnsQueryLogEntry]:
    """Return mock query log for development."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        DnsQueryLogEntry(timestamp=now, client_ip="192.168.4.10", domain="cdn.example.com", query_type="A", response_code="NOERROR", latency_ms=12.5),
        DnsQueryLogEntry(timestamp=now, client_ip="192.168.4.10", domain="api.example.com", query_type="A", response_code="NOERROR", latency_ms=8.2),
        DnsQueryLogEntry(timestamp=now, client_ip="192.168.4.10", domain="cdn.example.com", query_type="AAAA", response_code="NOERROR", latency_ms=15.1),
        DnsQueryLogEntry(timestamp=now, client_ip="192.168.4.11", domain="license.drm.example.com", query_type="A", response_code="NOERROR", latency_ms=45.3),
        DnsQueryLogEntry(timestamp=now, client_ip="192.168.4.10", domain="blocked.badcdn.com", query_type="A", response_code="NXDOMAIN", latency_ms=1.0),
    ]
