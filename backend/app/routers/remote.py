"""Remote management API for Claude Code integration.

Enables Claude to run shell commands, deploy files, read logs,
and manage services on the RPi without manual SSH copy-paste.

TODO: Add API key authentication before exposing to wider networks.
"""

import base64
import logging
import shlex
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..utils.shell import run, sudo_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/remote", tags=["remote"])


# --- Models ---

class ExecRequest(BaseModel):
    command: str
    timeout: float = 30.0
    sudo: bool = False


class ExecResponse(BaseModel):
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float


class DeployRequest(BaseModel):
    path: str
    content: str
    owner: str = "wifry:wifry"
    mode: str = ""
    sudo: bool = True


class DeployResponse(BaseModel):
    path: str
    bytes_written: int
    success: bool
    message: str


class ServiceRequest(BaseModel):
    pass  # action and name come from path params


# --- Shell execution ---

@router.post("/exec", response_model=ExecResponse)
async def exec_command(req: ExecRequest):
    """Execute a shell command and return output.

    The command string is split via shlex for safety.
    Use sudo=true for privileged commands.
    """
    start = time.monotonic()

    try:
        parts = shlex.split(req.command)
    except ValueError as e:
        raise HTTPException(400, f"Invalid command syntax: {e}")

    if not parts:
        raise HTTPException(400, "Empty command")

    logger.info("Remote exec: %s (sudo=%s)", req.command, req.sudo)

    result = await run(
        *parts,
        sudo=req.sudo,
        timeout=req.timeout,
        check=False,
    )

    duration = (time.monotonic() - start) * 1000
    return ExecResponse(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=duration,
    )


# --- File deployment ---

@router.post("/deploy", response_model=DeployResponse)
async def deploy_file(req: DeployRequest):
    """Write file content to a path on the RPi.

    For privileged paths (e.g., /opt/wifry/), uses sudo tee.
    Then optionally sets owner and mode.
    """
    logger.info("Remote deploy: %s (%d bytes)", req.path, len(req.content))

    try:
        if req.sudo:
            # Ensure parent directory exists
            parent = str(Path(req.path).parent)
            await run("mkdir", "-p", parent, sudo=True, check=False)
            await sudo_write(req.path, req.content)
        else:
            Path(req.path).parent.mkdir(parents=True, exist_ok=True)
            Path(req.path).write_text(req.content)

        # Set ownership
        if req.owner:
            await run("chown", req.owner, req.path, sudo=True, check=False)

        # Set mode
        if req.mode:
            await run("chmod", req.mode, req.path, sudo=True, check=False)

        return DeployResponse(
            path=req.path,
            bytes_written=len(req.content),
            success=True,
            message="OK",
        )
    except Exception as e:
        logger.error("Deploy failed: %s", e)
        return DeployResponse(
            path=req.path,
            bytes_written=0,
            success=False,
            message=str(e),
        )


@router.post("/deploy-tarball")
async def deploy_tarball(data: dict):
    """Deploy a base64-encoded tarball to a directory.

    Body: {"target_dir": "/opt/wifry/frontend/dist", "tarball_b64": "..."}
    """
    target_dir = data.get("target_dir", "")
    tarball_b64 = data.get("tarball_b64", "")

    if not target_dir or not tarball_b64:
        raise HTTPException(400, "target_dir and tarball_b64 required")

    logger.info("Remote deploy tarball to %s", target_dir)

    try:
        # Decode and write to temp file
        tarball = base64.b64decode(tarball_b64)
        tmp = Path("/tmp/wifry-deploy.tar.gz")
        tmp.write_bytes(tarball)

        # Extract
        await run("mkdir", "-p", target_dir, sudo=True, check=False)
        result = await run(
            "tar", "xzf", str(tmp), "-C", target_dir,
            sudo=True, check=False, timeout=30,
        )
        tmp.unlink(missing_ok=True)

        if not result.success:
            raise RuntimeError(result.stderr)

        # Fix ownership
        await run("chown", "-R", "wifry:wifry", target_dir, sudo=True, check=False)

        return {"success": True, "target_dir": target_dir, "bytes": len(tarball)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Log reading ---

ALLOWED_LOG_SERVICES = [
    "wifry-backend", "wifry-frontend", "wifry-first-boot",
    "hostapd", "dnsmasq", "dhcpcd",
]


@router.get("/logs/{service}")
async def read_logs(service: str, lines: int = 50, since: str = ""):
    """Read journalctl logs for a service."""
    if service not in ALLOWED_LOG_SERVICES:
        raise HTTPException(400, f"Service '{service}' not in allowed list: {ALLOWED_LOG_SERVICES}")

    cmd = ["journalctl", "-u", service, "--no-pager", "-n", str(min(lines, 500))]
    if since:
        cmd.extend(["--since", since])

    result = await run(*cmd, sudo=True, check=False, timeout=10)
    return {
        "service": service,
        "lines": result.stdout.splitlines() if result.success else [],
        "error": result.stderr if not result.success else "",
    }


@router.get("/logs-file/{path:path}")
async def read_log_file(path: str, tail: int = 100):
    """Read a log file directly (e.g., /var/log/wifry-first-boot.log)."""
    # Only allow reading from /var/log/ and /tmp/
    if not path.startswith("/var/log/") and not path.startswith("/tmp/"):
        raise HTTPException(400, "Only /var/log/ and /tmp/ paths allowed")

    result = await run("tail", "-n", str(min(tail, 1000)), path, sudo=True, check=False)
    return {
        "path": path,
        "lines": result.stdout.splitlines() if result.success else [],
        "error": result.stderr if not result.success else "",
    }


# --- File reading ---

@router.get("/file")
async def read_file(path: str, lines: Optional[int] = None):
    """Read a file from the RPi filesystem."""
    if not Path(path).exists():
        raise HTTPException(404, f"File not found: {path}")

    try:
        if lines:
            result = await run("head", "-n", str(lines), path, check=False)
            return {"path": path, "content": result.stdout}
        else:
            content = Path(path).read_text()
            return {"path": path, "content": content}
    except PermissionError:
        result = await run("cat", path, sudo=True, check=False)
        return {"path": path, "content": result.stdout}
    except Exception as e:
        raise HTTPException(500, str(e))


# --- Service management ---

ALLOWED_SERVICES = [
    "wifry-backend", "wifry-frontend",
    "hostapd", "dnsmasq", "dhcpcd",
]
ALLOWED_ACTIONS = ["restart", "stop", "start", "status"]


@router.post("/service/{name}/{action}")
async def manage_service(name: str, action: str):
    """Restart, stop, start, or check status of a systemd service."""
    if name not in ALLOWED_SERVICES:
        raise HTTPException(400, f"Service '{name}' not in allowed list: {ALLOWED_SERVICES}")
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, f"Action '{action}' not in allowed list: {ALLOWED_ACTIONS}")

    logger.info("Remote service: %s %s", action, name)

    if action == "status":
        result = await run("systemctl", "status", name, check=False)
        is_active = await run("systemctl", "is-active", name, check=False)
        return {
            "service": name,
            "active": is_active.stdout.strip() == "active",
            "status": result.stdout,
        }

    result = await run("systemctl", action, name, sudo=True, check=False)
    # Check resulting status
    is_active = await run("systemctl", "is-active", name, check=False)

    return {
        "service": name,
        "action": action,
        "success": result.success,
        "active": is_active.stdout.strip() == "active",
        "error": result.stderr if not result.success else "",
    }


# --- System overview ---

@router.get("/status")
async def system_status():
    """Quick system overview: services, memory, temp, disk."""
    services = {}
    for svc in ALLOWED_SERVICES:
        result = await run("systemctl", "is-active", svc, check=False)
        services[svc] = result.stdout.strip()

    # Memory
    mem_result = await run("free", "-m", check=False)
    mem_lines = mem_result.stdout.splitlines()
    mem_info = {}
    if len(mem_lines) >= 2:
        parts = mem_lines[1].split()
        if len(parts) >= 7:
            mem_info = {
                "total_mb": int(parts[1]),
                "used_mb": int(parts[2]),
                "available_mb": int(parts[6]),
            }

    # Temperature
    temp = 0.0
    try:
        temp_str = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        temp = int(temp_str) / 1000
    except Exception:
        pass

    # Disk
    disk_result = await run("df", "-h", "/", check=False)
    disk_lines = disk_result.stdout.splitlines()
    disk_info = disk_lines[1] if len(disk_lines) >= 2 else ""

    return {
        "services": services,
        "memory": mem_info,
        "temperature_c": temp,
        "disk": disk_info,
    }
