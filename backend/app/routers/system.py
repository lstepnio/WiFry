"""System router — RPi info, settings, reboot."""

import json
import logging
import platform
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..models.observability import AuditEvent
from ..utils.shell import run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/info")
async def get_system_info():
    """Get system information: model, CPU, memory, temperature, uptime."""
    if settings.mock_mode:
        return _mock_info()

    info: dict = {
        "platform": platform.machine(),
        "os": platform.platform(),
    }

    # RPi model
    try:
        result = await run("cat", "/proc/device-tree/model", check=False)
        info["model"] = result.stdout.rstrip("\x00") if result.success else "Unknown"
    except Exception:
        info["model"] = "Unknown"

    # CPU temperature
    try:
        result = await run("cat", "/sys/class/thermal/thermal_zone0/temp", check=False)
        if result.success:
            info["temperature_c"] = round(int(result.stdout) / 1000, 1)
    except Exception:
        info["temperature_c"] = None

    # CPU usage (1-second sample)
    try:
        result = await run(
            "sh", "-c",
            "top -bn1 | head -3 | tail -1",
            check=False,
        )
        if result.success:
            info["cpu_line"] = result.stdout
    except Exception:
        pass

    # Load averages + CPU cores
    try:
        import os
        load1, load5, load15 = os.getloadavg()
        info["load_avg"] = [round(load1, 2), round(load5, 2), round(load15, 2)]
        info["cpu_cores"] = os.cpu_count() or 1
        info["cpu_usage_pct"] = round(load1 / (os.cpu_count() or 1) * 100, 1)
    except Exception:
        info["load_avg"] = [0, 0, 0]
        info["cpu_cores"] = 1
        info["cpu_usage_pct"] = 0

    # Memory
    try:
        result = await run("free", "-m", check=False)
        if result.success:
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                parts = lines[1].split()
                info["memory_total_mb"] = int(parts[1])
                info["memory_used_mb"] = int(parts[2])
                info["memory_available_mb"] = int(parts[6]) if len(parts) > 6 else None
    except Exception:
        pass

    # Uptime
    try:
        result = await run("uptime", "-p", check=False)
        if result.success:
            info["uptime"] = result.stdout
    except Exception:
        pass

    return info


@router.post("/reboot")
async def reboot():
    """Reboot the Raspberry Pi."""
    from ..services import audit_log
    if settings.mock_mode:
        audit_log.record_event("system.reboot", resource_type="system", details={"mock_mode": True})
        return {"status": "mock", "message": "Reboot simulated (mock mode)"}

    await run("systemctl", "reboot", sudo=True, check=False)
    audit_log.record_event("system.reboot", resource_type="system")
    return {"status": "ok", "message": "Rebooting..."}


@router.get("/settings")
async def get_settings():
    """Get current system settings."""
    from ..services import settings_manager
    base = settings_manager.get_all()
    base["mock_mode"] = settings.mock_mode
    base["dns_enabled"] = settings.dns_enabled
    return base


@router.put("/settings")
async def update_settings(updates: dict):
    """Update system settings."""
    from ..services import settings_manager
    return settings_manager.update(updates)


@router.post("/settings/password")
async def change_password(current: str = "", new_password: str = ""):
    """Change the web UI password."""
    from ..services import settings_manager
    return await settings_manager.change_password(current, new_password)


@router.post("/settings/git-repo")
async def set_git_repo(url: str):
    """Set the git remote URL."""
    from ..services import settings_manager
    return await settings_manager.set_git_repo(url)


@router.post("/settings/force-update")
async def force_update():
    """Force update from git (pull + rebuild)."""
    from ..services import settings_manager
    return await settings_manager.force_update()


# --- Storage ---

@router.get("/storage/devices")
async def detect_storage():
    """Detect connected USB storage devices."""
    from ..services import storage
    return await storage.detect_devices()


@router.post("/storage/mount")
async def mount_storage(device: str):
    """Mount USB storage for WiFry data."""
    from ..services import storage
    return await storage.mount_device(device)


@router.post("/storage/unmount")
async def unmount_storage():
    """Unmount external storage."""
    from ..services import storage
    return await storage.unmount()


@router.get("/storage/status")
async def storage_status():
    """Get current storage status and paths."""
    from ..services import storage
    return storage.get_status()


@router.get("/storage/usage")
async def storage_usage():
    """Get storage usage breakdown."""
    from ..services import storage
    return await storage.get_usage()


# --- Dependency Check ---

@router.get("/dependencies")
async def check_dependencies():
    """Check which external dependencies are installed on the system."""
    deps = {}
    checks = {
        "tshark": ["tshark", "--version"],
        "ffmpeg": ["ffmpeg", "-version"],
        "ffprobe": ["ffprobe", "-version"],
        "iperf3": ["iperf3", "--version"],
        "coredns": ["coredns", "-version"],
        "mitmproxy": ["mitmdump", "--version"],
        "cloudflared": ["cloudflared", "--version"],
        "speedtest": ["speedtest", "--version"],
        "wireguard": ["wg", "--version"],
        "openvpn": ["openvpn", "--version"],
        "strongswan": ["swanctl", "--version"],
        "adb": ["adb", "--version"],
        "hping3": ["hping3", "--version"],
        "v4l2": ["v4l2-ctl", "--version"],
    }

    if settings.mock_mode:
        return {name: {"installed": True, "version": "mock"} for name in checks}

    for name, cmd in checks.items():
        try:
            result = await run(cmd[0], *cmd[1:], check=False, timeout=5)
            version = result.stdout.split('\n')[0][:100] if result.success else ""
            deps[name] = {"installed": result.success, "version": version}
        except Exception:
            deps[name] = {"installed": False, "version": ""}

    return deps


# --- Feature Flags ---

@router.get("/features")
async def get_feature_flags():
    """Get all feature flags with their current state."""
    from ..services import feature_flags
    return feature_flags.get_all()


@router.put("/features/{flag_name}")
async def set_feature_flag(flag_name: str, enabled: bool):
    """Enable or disable a feature flag."""
    from ..services import audit_log, feature_flags
    try:
        result = feature_flags.set_flag(flag_name, enabled)
        audit_log.record_event(
            "system.feature_flag.set",
            resource_type="feature_flag",
            resource_id=flag_name,
            details={"enabled": enabled},
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/features/reset")
async def reset_feature_flags():
    """Reset all feature flags to defaults."""
    from ..services import audit_log, feature_flags
    result = feature_flags.reset_defaults()
    audit_log.record_event("system.feature_flag.reset", resource_type="feature_flag")
    return result


# --- Data Management ---

# Items to preserve during factory reset (everything else is deleted).
# This allowlist approach means new data stores are automatically cleaned
# without requiring changes here — preventing the recurring regression where
# new services add data directories that factory reset doesn't know about.
_FACTORY_RESET_KEEP = {
    ".first-boot-complete",  # First-boot marker for image setup
    ".git",                  # Git repo for self-updates
    "VERSION",               # Version file (managed by updater)
}


@router.delete("/data/all")
async def delete_all_data():
    """Full factory reset — delete ALL data, settings, and reset network config.

    Uses an allowlist approach: scans the entire data directory and deletes
    everything except a small set of system files. This ensures new data
    stores are automatically cleaned without code changes.
    """
    import shutil
    from ..services import audit_log

    base = Path("/var/lib/wifry") if not settings.mock_mode else Path("/tmp/wifry")
    deleted = {}

    if base.exists():
        for entry in sorted(base.iterdir()):
            if entry.name in _FACTORY_RESET_KEEP:
                continue

            if entry.is_dir():
                count = sum(1 for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry, ignore_errors=True)
                deleted[entry.name] = count
            elif entry.is_file():
                entry.unlink(missing_ok=True)
                deleted[entry.name] = 1

    # Reset network config to defaults
    try:
        from ..services import network_config
        await network_config.apply_defaults()
        deleted["network_reset"] = "defaults applied"
    except Exception as e:
        deleted["network_reset"] = f"failed: {e}"

    # Re-create captures dir with correct permissions (tshark needs world-writable)
    captures_dir = base / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    try:
        captures_dir.chmod(0o1777)
    except Exception:
        pass

    logger.info("system.factory_reset_complete", extra={"event": "factory_reset", "deleted": deleted})
    audit_log.record_event(
        "system.data.delete_all",
        resource_type="data",
        details={"deleted": deleted},
    )
    return {"status": "ok", "deleted": deleted}


@router.delete("/data/{category}")
async def delete_category_data(category: str):
    """Delete all data in a specific category (captures, sessions, logs, etc.)."""
    import shutil
    from ..services import audit_log, storage
    paths = storage.get_data_paths()
    dir_path = paths.get(category)
    if not dir_path:
        raise HTTPException(404, f"Unknown category: {category}")
    p = Path(dir_path)
    count = 0
    if p.exists():
        count = sum(1 for f in p.rglob("*") if f.is_file())
        shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True, exist_ok=True)
    audit_log.record_event(
        "system.data.delete_category",
        resource_type="data",
        resource_id=category,
        details={"files_deleted": count},
    )
    return {"status": "ok", "category": category, "files_deleted": count}


# --- Updates ---

# --- App Logs ---

@router.get("/logs")
async def get_app_logs(lines: int = 200, level: str = "all"):
    """Get WiFry application logs (journalctl)."""
    if settings.mock_mode:
        return {"lines": [
            json.dumps({"ts": "2026-04-03T00:10:00Z", "level": "INFO", "logger": "wifry", "message": "WiFry starting up", "event": "startup"}),
            json.dumps({"ts": "2026-04-03T00:10:00Z", "level": "WARNING", "logger": "wifry", "message": "Running in MOCK MODE", "event": "startup"}),
            json.dumps({"ts": "2026-04-03T00:10:01Z", "level": "INFO", "logger": "app.services.tc_manager", "message": "Applied impairment on wlan0", "request_id": "req-demo-1", "event": "impairment_apply"}),
            json.dumps({"ts": "2026-04-03T00:10:05Z", "level": "INFO", "logger": "app.services.capture", "message": "Started capture abc123", "request_id": "req-demo-2", "event": "capture_start"}),
            json.dumps({"ts": "2026-04-03T00:10:10Z", "level": "INFO", "logger": "app.services.audit_log", "message": "audit.event", "request_id": "req-demo-2", "event": "audit", "action": "sharing.fileio.upload_bundle", "resource_type": "bundle"}),
        ], "total": 5}

    cmd = ["journalctl", "-u", "wifry-backend",
           "-u", "hostapd", "-u", "dnsmasq",
           "--no-pager", "-n", str(min(lines, 5000))]
    if level == "error":
        cmd.extend(["-p", "err"])
    elif level == "warn":
        cmd.extend(["-p", "warning"])

    result = await run(*cmd, check=False, timeout=10)
    log_lines = result.stdout.splitlines() if result.success else []
    return {"lines": log_lines, "total": len(log_lines)}


@router.post("/logs/share")
async def share_app_logs(lines: int = 500):
    """Collect app logs and upload to file.io for developer sharing."""
    from ..services import audit_log, fileio

    # Get logs
    if settings.mock_mode:
        log_content = "WiFry Mock Logs\n" + "Mock log line\n" * 20
    else:
        result = await run(
            "journalctl", "-u", "wifry-backend",
            "-u", "hostapd", "-u", "dnsmasq",
            "--no-pager", "-n", str(min(lines, 5000)),
            check=False, timeout=10,
        )
        log_content = result.stdout if result.success else "Failed to collect logs"

    # Save to temp file
    import os
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"/tmp/wifry_logs_{ts}.txt"
    with open(log_path, "w") as f:
        f.write(f"WiFry - IP Video Edition - Application Logs\n")
        f.write(f"Collected: {datetime.now().isoformat()}\n")
        f.write(f"Lines: {lines}\n")
        f.write(f"{'=' * 60}\n\n")
        f.write(log_content)
        f.write(f"\n\nAudit Events (latest 25)\n")
        f.write(f"{'=' * 60}\n")
        f.write(json.dumps(audit_log.list_events(limit=25), indent=2))

    upload = await fileio.upload_file(log_path, "15m")

    # Cleanup temp file
    try:
        os.unlink(log_path)
    except OSError:
        pass

    audit_log.record_event(
        "system.logs.share",
        resource_type="logs",
        details={"lines": lines, "upload_success": upload.get("success", False)},
    )
    return upload


@router.get("/audit", response_model=List[AuditEvent])
async def get_audit_events(limit: int = Query(100, ge=1, le=500), action: str = ""):
    """Get recent audit events for destructive or external actions."""
    from ..services import audit_log

    return audit_log.list_events(limit=limit, action=action or None)


@router.get("/version")
async def get_version():
    """Get current version and check for updates."""
    from ..services import updater
    return await updater.check_updates()


@router.get("/update/check")
async def check_updates():
    """Check for available updates from git remote."""
    from ..services import updater
    return await updater.check_updates()


@router.post("/update/apply")
async def apply_update(target_version: str = ""):
    """Apply update to a specific version (or latest). Auto-restarts backend."""
    from ..services import updater
    return await updater.apply_update(target_version)


@router.post("/update/pull")
async def pull_update():
    """Legacy: Pull latest update from git and rebuild."""
    from ..services import updater
    return await updater.pull_update()


def _mock_info() -> dict:
    return {
        "model": "Raspberry Pi 5 Model B (mock)",
        "platform": platform.machine(),
        "os": platform.platform(),
        "temperature_c": 42.5,
        "memory_total_mb": 8192,
        "memory_used_mb": 1024,
        "memory_available_mb": 6800,
        "uptime": "up 3 days, 4 hours, 12 minutes",
    }
