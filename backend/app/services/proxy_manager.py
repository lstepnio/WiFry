"""mitmproxy lifecycle management and iptables redirect control."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from ..config import settings
from ..models.stream import ProxySettings, ProxyStatus
from ..utils.shell import run

logger = logging.getLogger(__name__)

_proxy_process: Optional[asyncio.subprocess.Process] = None
_proxy_settings = ProxySettings()
_intercepted_flows = 0

MITMPROXY_PORT = 8888
CERT_DIR = Path("/var/lib/wifry/certs")
ADDON_SCRIPT = Path(__file__).resolve().parent.parent / "mitmproxy_addon" / "stream_tap.py"


async def enable_proxy() -> ProxyStatus:
    """Start mitmproxy and set up iptables redirect."""
    global _proxy_process

    if settings.mock_mode:
        logger.info("Mock: proxy enabled")
        return get_status(enabled=True, running=True)

    if _proxy_process and _proxy_process.returncode is None:
        return get_status(enabled=True, running=True)

    # Ensure cert directory exists
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # Start mitmdump in transparent mode
    cmd = [
        "mitmdump",
        "--mode", "transparent",
        "--listen-port", str(MITMPROXY_PORT),
        "--set", f"confdir={CERT_DIR}",
        "-s", str(ADDON_SCRIPT),
        "--quiet",
    ]

    logger.info("Starting mitmproxy: %s", " ".join(cmd))
    _proxy_process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Wait briefly for it to start
    await asyncio.sleep(1)
    if _proxy_process.returncode is not None:
        stderr = (await _proxy_process.stderr.read()).decode()
        logger.error("mitmproxy failed to start: %s", stderr)
        raise RuntimeError(f"mitmproxy failed: {stderr}")

    # Set up iptables redirect
    iface = settings.ap_interface or "wlan0"
    await _setup_iptables_redirect(iface)

    logger.info("Proxy enabled on port %d", MITMPROXY_PORT)
    return get_status(enabled=True, running=True)


async def disable_proxy() -> ProxyStatus:
    """Stop mitmproxy and remove iptables redirect."""
    global _proxy_process

    if settings.mock_mode:
        logger.info("Mock: proxy disabled")
        return get_status(enabled=False, running=False)

    # Remove iptables redirect
    iface = settings.ap_interface or "wlan0"
    await _remove_iptables_redirect(iface)

    # Stop mitmproxy
    if _proxy_process and _proxy_process.returncode is None:
        _proxy_process.terminate()
        try:
            await asyncio.wait_for(_proxy_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _proxy_process.kill()
        _proxy_process = None

    logger.info("Proxy disabled")
    return get_status(enabled=False, running=False)


async def _setup_iptables_redirect(iface: str) -> None:
    """Add iptables rules to redirect HTTP/HTTPS to mitmproxy."""
    for port in [80, 443]:
        await run(
            "iptables", "-t", "nat", "-A", "PREROUTING",
            "-i", iface, "-p", "tcp", "--dport", str(port),
            "-j", "REDIRECT", "--to-port", str(MITMPROXY_PORT),
            sudo=True, check=False,
        )
    logger.info("iptables redirect set for %s -> :%d", iface, MITMPROXY_PORT)


async def _remove_iptables_redirect(iface: str) -> None:
    """Remove iptables redirect rules."""
    for port in [80, 443]:
        await run(
            "iptables", "-t", "nat", "-D", "PREROUTING",
            "-i", iface, "-p", "tcp", "--dport", str(port),
            "-j", "REDIRECT", "--to-port", str(MITMPROXY_PORT),
            sudo=True, check=False,
        )
    logger.info("iptables redirect removed for %s", iface)


def get_status(enabled: bool = False, running: bool = False) -> ProxyStatus:
    """Get current proxy status."""
    if not settings.mock_mode:
        running = _proxy_process is not None and _proxy_process.returncode is None
        enabled = running

    return ProxyStatus(
        enabled=enabled,
        running=running,
        port=MITMPROXY_PORT,
        save_segments=_proxy_settings.save_segments,
        max_storage_mb=_proxy_settings.max_storage_mb,
        cert_installed_hint="Download CA cert from /api/v1/proxy/cert and install on your STB",
        intercepted_flows=_intercepted_flows,
    )


def update_settings(new_settings: ProxySettings) -> ProxyStatus:
    """Update proxy settings."""
    global _proxy_settings
    _proxy_settings = new_settings
    return get_status()


def get_cert_path() -> Optional[Path]:
    """Get path to the mitmproxy CA certificate for client installation."""
    cert = CERT_DIR / "mitmproxy-ca-cert.pem"
    if cert.exists():
        return cert
    # Fallback: default mitmproxy cert location
    home_cert = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"
    if home_cert.exists():
        return home_cert
    return None


def increment_flow_count() -> None:
    """Called by the stream event handler to track intercepted flows."""
    global _intercepted_flows
    _intercepted_flows += 1
