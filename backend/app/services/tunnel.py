"""Cloudflare Quick Tunnel for sharing diagnostics.

Uses `cloudflared` to create a temporary tunnel that exposes
the WiFry web UI and file-sharing endpoints to a public URL.
No Cloudflare account needed — Quick Tunnels are free and ephemeral.
Tunnel process state and public URLs are intentionally not restored
after a backend restart.

The tunnel exposes a read-only file share service with:
  - Test reports (HTML)
  - Packet captures (pcap)
  - AI analysis results
  - Screenshots / HDMI frames
  - Annotations / notes
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..models.tunnel import TunnelStatus
from ..utils.shell import run
from . import audit_log

logger = logging.getLogger(__name__)

_tunnel_process: Optional[asyncio.subprocess.Process] = None
_tunnel_url: Optional[str] = None
_started_at: Optional[str] = None


async def start_tunnel(port: int = 8080) -> dict:
    """Start a Cloudflare Quick Tunnel pointing at the WiFry backend.

    cloudflared will output a URL like:
      https://random-words.trycloudflare.com
    """
    global _tunnel_process, _tunnel_url, _started_at

    if settings.mock_mode and _tunnel_url:
        return get_status()

    if _tunnel_process and _tunnel_process.returncode is None:
        return get_status()

    if settings.mock_mode:
        _tunnel_url = "https://wifry-demo-abc123.trycloudflare.com"
        _started_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "tunnel.started",
            extra={"event": "tunnel_start", "port": port, "mock_mode": True, "tunnel_host": "trycloudflare.com"},
        )
        audit_log.record_event(
            "sharing.tunnel.start",
            resource_type="tunnel",
            details={"port": port, "mock_mode": True},
        )
        return get_status()

    # Start cloudflared quick tunnel
    _tunnel_process = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel", "--url", f"http://localhost:{port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _started_at = datetime.now(timezone.utc).isoformat()

    # cloudflared prints the URL to stderr
    # Watch for it in a background task
    asyncio.create_task(_watch_for_url())

    # Wait briefly for URL to appear
    for _ in range(30):
        await asyncio.sleep(0.5)
        if _tunnel_url:
            break

    if not _tunnel_url:
        logger.warning("Tunnel started but URL not yet detected. Check /api/v1/tunnel/status.")
        audit_log.record_event(
            "sharing.tunnel.start",
            outcome="degraded",
            resource_type="tunnel",
            details={"port": port, "url_detected": False},
        )
    else:
        audit_log.record_event(
            "sharing.tunnel.start",
            resource_type="tunnel",
            details={"port": port, "url_detected": True, "tunnel_host": _tunnel_url.split("/", 3)[2]},
        )

    return get_status()


async def _watch_for_url() -> None:
    """Read cloudflared stderr to extract the tunnel URL."""
    global _tunnel_url

    if not _tunnel_process or not _tunnel_process.stderr:
        return

    try:
        while True:
            line_bytes = await _tunnel_process.stderr.readline()
            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace").strip()
            logger.debug("cloudflared: %s", line)

            # Look for the tunnel URL
            match = re.search(r"(https://[\w\-]+\.trycloudflare\.com)", line)
            if match:
                _tunnel_url = match.group(1)
                logger.info(
                    "tunnel.url_detected",
                    extra={
                        "event": "tunnel_url_detected",
                        "tunnel_host": _tunnel_url.split("/", 3)[2],
                    },
                )
                break

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Error watching cloudflared output: %s", e)


async def stop_tunnel() -> dict:
    """Stop the Cloudflare tunnel."""
    global _tunnel_process, _tunnel_url, _started_at

    from . import collaboration

    if settings.mock_mode:
        _tunnel_url = None
        _started_at = None
        await collaboration.disconnect_all_users()
        audit_log.record_event("sharing.tunnel.stop", resource_type="tunnel", details={"mock_mode": True})
        return get_status()

    if _tunnel_process and _tunnel_process.returncode is None:
        _tunnel_process.terminate()
        try:
            await asyncio.wait_for(_tunnel_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _tunnel_process.kill()

    _tunnel_process = None
    _tunnel_url = None
    _started_at = None

    await collaboration.disconnect_all_users()

    logger.info("tunnel.stopped", extra={"event": "tunnel_stop"})
    audit_log.record_event("sharing.tunnel.stop", resource_type="tunnel")
    return get_status()


def get_status() -> dict:
    """Get current tunnel status."""
    running = False
    if settings.mock_mode:
        running = _tunnel_url is not None
    else:
        running = _tunnel_process is not None and _tunnel_process.returncode is None

    return TunnelStatus(
        active=running,
        url=_tunnel_url,
        started_at=_started_at,
        share_url=f"{_tunnel_url}/api/v1/share" if _tunnel_url else None,
        message=f"Sharing via {_tunnel_url}" if _tunnel_url else "Tunnel not active",
    ).model_dump(mode="json")


async def check_cloudflared() -> dict:
    """Check if cloudflared is installed."""
    if settings.mock_mode:
        return {"installed": True, "version": "2024.6.0 (mock)"}

    result = await run("cloudflared", "--version", check=False)
    if result.success:
        return {"installed": True, "version": result.stdout.strip()}
    return {"installed": False, "version": None, "install_hint": "curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared"}
