"""Hardware validation service — runs checks and returns structured results.

This is the API-facing counterpart to the pytest HW tests. Same checks,
but returns JSON instead of using assert.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    name: str
    tier: int
    category: str
    status: str  # "pass", "fail", "skip"
    message: str = ""
    duration_ms: float = 0


@dataclass
class ValidationReport:
    results: List[TestResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: float = 0


async def _check(
    name: str, tier: int, category: str, coro
) -> TestResult:
    """Run a single check, catching exceptions."""
    start = time.monotonic()
    try:
        ok, msg = await coro
        status = "pass" if ok else "fail"
        return TestResult(
            name=name, tier=tier, category=category,
            status=status, message=msg,
            duration_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as e:
        return TestResult(
            name=name, tier=tier, category=category,
            status="fail", message=str(e),
            duration_ms=(time.monotonic() - start) * 1000,
        )


# --- Tier 1: System Readiness ---

async def _check_binary(name: str) -> tuple[bool, str]:
    result = await run("which", name, check=False)
    if result.success:
        return True, result.stdout.strip()
    return False, f"'{name}' not found in PATH"


async def _check_service(name: str) -> tuple[bool, str]:
    result = await run("systemctl", "is-active", name, check=False)
    status = result.stdout.strip()
    return status == "active", f"Service '{name}' is {status}"


async def _check_sudo(cmd: str, args: list) -> tuple[bool, str]:
    result = await run(cmd, *args, sudo=True, check=False, timeout=5)
    if "password is required" in result.stderr:
        return False, f"sudo {cmd} requires password"
    return True, "OK"


async def _check_file_exists(path: str) -> tuple[bool, str]:
    return Path(path).exists(), path


async def _check_captures_dir() -> tuple[bool, str]:
    p = Path("/var/lib/wifry/captures")
    if not p.exists():
        return False, "Directory does not exist"
    mode = oct(p.stat().st_mode)
    if mode.endswith("777"):
        return True, f"Mode: {mode}"
    return False, f"Mode is {mode}, expected *777"


async def _check_dnsmasq_confdir() -> tuple[bool, str]:
    p = Path("/etc/dnsmasq.conf")
    if not p.exists():
        return False, "/etc/dnsmasq.conf not found"
    for line in p.read_text().splitlines():
        s = line.strip()
        if s.startswith("conf-dir=") and "/etc/dnsmasq.d" in s:
            return True, s
    return False, "conf-dir=/etc/dnsmasq.d not enabled"


async def _check_wlan0_ip() -> tuple[bool, str]:
    result = await run("ip", "-j", "addr", "show", "wlan0", check=False)
    if not result.success:
        return False, "wlan0 not found"
    if "192.168.4.1" in result.stdout:
        return True, "192.168.4.1"
    return False, "192.168.4.1 not assigned to wlan0"


async def _check_hostapd_ctrl() -> tuple[bool, str]:
    p = Path("/var/run/hostapd")
    return p.exists(), str(p)


async def _check_reg_domain() -> tuple[bool, str]:
    result = await run("iw", "reg", "get", sudo=True, check=False)
    if not result.success:
        return False, "iw reg get failed"
    for line in result.stdout.splitlines():
        if line.strip().startswith("country") and ":" in line:
            country = line.strip().split()[1].rstrip(":")
            if country not in ("00", "99"):
                return True, f"Country: {country}"
    return False, "No valid regulatory domain"


async def _check_wifi_caps() -> tuple[bool, str]:
    result = await run("iw", "dev", "wlan0", "info", sudo=True, check=False)
    if not result.success:
        return False, "wlan0 not found"
    caps = []
    phy_match = re.search(r"wiphy (\d+)", result.stdout)
    if phy_match:
        phy = f"phy{phy_match.group(1)}"
        info_result = await run("iw", "phy", phy, "info", sudo=True, check=False)
        if info_result.success:
            info = info_result.stdout
            if "* AP" in info:
                caps.append("AP")
            if "Band 2:" in info:
                caps.append("5GHz")
    return len(caps) > 0, f"Capabilities: {', '.join(caps) or 'none'}"


async def _run_tier1() -> List[TestResult]:
    """Run Tier 1: System Readiness checks."""
    results = []

    # Binaries
    for binary in ["tshark", "tc", "iw", "hostapd_cli", "iptables", "ip",
                    "dumpcap", "systemctl", "hping3", "curl"]:
        r = await _check(f"Binary: {binary}", 1, "Binaries",
                         _check_binary(binary))
        results.append(r)

    # Services
    for svc in ["hostapd", "dnsmasq", "wifry-backend"]:
        r = await _check(f"Service: {svc}", 1, "Services",
                         _check_service(svc))
        results.append(r)

    # Sudoers
    sudo_cmds = [
        ("tc", ["-j", "qdisc", "show", "dev", "lo"]),
        ("ip", ["-j", "addr", "show", "lo"]),
        ("iw", ["dev", "wlan0", "info"]),
    ]
    for cmd, args in sudo_cmds:
        r = await _check(f"Sudo: {cmd}", 1, "Permissions",
                         _check_sudo(cmd, args))
        results.append(r)

    # Files & permissions
    results.append(await _check("Captures dir writable", 1, "Permissions",
                                _check_captures_dir()))
    results.append(await _check("hostapd.conf exists", 1, "Files",
                                _check_file_exists("/etc/hostapd/hostapd.conf")))
    results.append(await _check("dnsmasq conf-dir enabled", 1, "Files",
                                _check_dnsmasq_confdir()))

    # Network
    results.append(await _check("wlan0 has AP IP", 1, "Network",
                                _check_wlan0_ip()))
    results.append(await _check("hostapd ctrl_interface", 1, "Network",
                                _check_hostapd_ctrl()))
    results.append(await _check("Regulatory domain", 1, "Network",
                                _check_reg_domain()))

    # WiFi
    results.append(await _check("WiFi capabilities", 1, "WiFi",
                                _check_wifi_caps()))

    return results


# --- Tier 2: API Smoke Tests ---

async def _run_tier2() -> List[TestResult]:
    """Run Tier 2: API Smoke Tests."""
    results = []

    async with httpx.AsyncClient(
        base_url="http://localhost:8080", timeout=15.0
    ) as api:
        # Health check
        try:
            resp = await api.get("/api/v1/health")
            ok = resp.status_code == 200 and resp.json().get("mock_mode") is False
            results.append(TestResult(
                name="Health (non-mock)", tier=2, category="API",
                status="pass" if ok else "fail",
                message="mock_mode=false" if ok else f"Unexpected: {resp.text[:100]}",
            ))
        except Exception as e:
            results.append(TestResult(
                name="Health (non-mock)", tier=2, category="API",
                status="fail", message=str(e),
            ))

        # Endpoint availability
        endpoints = [
            "/api/v1/system/info", "/api/v1/system/features",
            "/api/v1/impairments", "/api/v1/wifi-impairments",
            "/api/v1/profiles", "/api/v1/network/interfaces",
            "/api/v1/captures", "/api/v1/sessions",
            "/api/v1/dns/status", "/api/v1/network-config/current",
        ]
        for ep in endpoints:
            try:
                resp = await api.get(ep)
                ok = resp.status_code == 200
                results.append(TestResult(
                    name=f"GET {ep}", tier=2, category="API",
                    status="pass" if ok else "fail",
                    message=f"Status: {resp.status_code}",
                ))
            except Exception as e:
                results.append(TestResult(
                    name=f"GET {ep}", tier=2, category="API",
                    status="fail", message=str(e),
                ))

        # tc netem apply/clear
        try:
            config = {"delay": {"ms": 10, "jitter_ms": 0, "correlation_pct": 0}}
            resp = await api.put("/api/v1/impairments/wlan0", json=config)
            apply_ok = resp.status_code == 200
            resp = await api.delete("/api/v1/impairments/wlan0")
            clear_ok = resp.status_code == 200
            results.append(TestResult(
                name="tc netem apply/clear", tier=2, category="Impairments",
                status="pass" if (apply_ok and clear_ok) else "fail",
                message=f"apply={apply_ok}, clear={clear_ok}",
            ))
        except Exception as e:
            results.append(TestResult(
                name="tc netem apply/clear", tier=2, category="Impairments",
                status="fail", message=str(e),
            ))

    return results


# --- Tier 3: Integration (requires client) ---

async def _run_tier3(client_ip: str) -> List[TestResult]:
    """Run Tier 3: Integration tests with connected client."""
    results = []

    # Client reachable
    ping_result = await run("ping", "-c", "3", "-W", "2", client_ip,
                            check=False, timeout=15)
    reachable = ping_result.success and "0 received" not in ping_result.stdout
    results.append(TestResult(
        name=f"Ping client {client_ip}", tier=3, category="Connectivity",
        status="pass" if reachable else "fail",
        message="Reachable" if reachable else "Not reachable",
    ))

    if not reachable:
        results.append(TestResult(
            name="Remaining integration tests", tier=3, category="Connectivity",
            status="skip", message="Client not reachable, skipping remaining tests",
        ))
        return results

    async with httpx.AsyncClient(
        base_url="http://localhost:8080", timeout=30.0
    ) as api:
        # Client in API
        try:
            resp = await api.get("/api/v1/network/clients")
            clients = [c["ip"] for c in resp.json()]
            ok = client_ip in clients
            results.append(TestResult(
                name="Client in API", tier=3, category="Connectivity",
                status="pass" if ok else "fail",
                message=f"Found: {clients}" if ok else f"Not in: {clients}",
            ))
        except Exception as e:
            results.append(TestResult(
                name="Client in API", tier=3, category="Connectivity",
                status="fail", message=str(e),
            ))

        # DHCP fail cleanup
        try:
            config = {
                "dhcp_disruption": {"enabled": True, "mode": "fail"},
                "tx_power": {"enabled": False},
                "channel_interference": {"enabled": False},
                "band_switch": {"enabled": False},
                "deauth": {"enabled": False},
                "broadcast_storm": {"enabled": False},
                "rate_limit": {"enabled": False},
                "periodic_disconnect": {"enabled": False},
            }
            await api.put("/api/v1/wifi-impairments", json=config)
            check = await run("iptables", "-L", "OUTPUT", "-n",
                              sudo=True, check=False)
            added = "wifry-dhcp-fail" in check.stdout

            await api.delete("/api/v1/wifi-impairments")
            check = await run("iptables", "-L", "OUTPUT", "-n",
                              sudo=True, check=False)
            removed = "wifry-dhcp-fail" not in check.stdout

            results.append(TestResult(
                name="DHCP fail iptables cleanup", tier=3, category="WiFi Impairments",
                status="pass" if (added and removed) else "fail",
                message=f"added={added}, removed={removed}",
            ))
        except Exception as e:
            results.append(TestResult(
                name="DHCP fail iptables cleanup", tier=3, category="WiFi Impairments",
                status="fail", message=str(e),
            ))

    return results


# --- Main entry point ---

async def run_validation(
    tiers: List[int] = None,
    client_ip: Optional[str] = None,
) -> ValidationReport:
    """Run hardware validation and return structured report."""
    if settings.mock_mode:
        return ValidationReport(
            results=[TestResult(
                name="Mock mode", tier=0, category="System",
                status="skip", message="HW tests unavailable in mock mode",
            )],
            skipped=1,
        )

    if tiers is None:
        tiers = [1, 2, 3]

    start = time.monotonic()
    all_results: List[TestResult] = []

    if 1 in tiers:
        all_results.extend(await _run_tier1())

    if 2 in tiers:
        all_results.extend(await _run_tier2())

    if 3 in tiers:
        if client_ip:
            all_results.extend(await _run_tier3(client_ip))
        else:
            # Auto-detect client
            try:
                async with httpx.AsyncClient(
                    base_url="http://localhost:8080", timeout=10
                ) as api:
                    resp = await api.get("/api/v1/network/clients")
                    clients = resp.json()
                    if clients:
                        client_ip = clients[0]["ip"]
                        all_results.extend(await _run_tier3(client_ip))
                    else:
                        all_results.append(TestResult(
                            name="Integration tests", tier=3, category="Connectivity",
                            status="skip",
                            message="No WiFi clients connected — connect a device to run Tier 3",
                        ))
            except Exception:
                all_results.append(TestResult(
                    name="Integration tests", tier=3, category="Connectivity",
                    status="skip", message="Could not detect connected clients",
                ))

    report = ValidationReport(
        results=all_results,
        passed=sum(1 for r in all_results if r.status == "pass"),
        failed=sum(1 for r in all_results if r.status == "fail"),
        skipped=sum(1 for r in all_results if r.status == "skip"),
        duration_ms=(time.monotonic() - start) * 1000,
    )

    logger.info(
        "HW validation: %d passed, %d failed, %d skipped (%.0fms)",
        report.passed, report.failed, report.skipped, report.duration_ms,
    )
    return report
