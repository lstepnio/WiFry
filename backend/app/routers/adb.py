"""ADB router — device management, shell, logcat, file ops, key events."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pathlib import Path

from ..models.adb import (
    AdbConnectRequest,
    AdbDevice,
    AdbFileRequest,
    AdbInstallRequest,
    AdbKeyEvent,
    AdbShellRequest,
    AdbShellResult,
    LogcatLine,
    LogcatSession,
    STB_KEYCODES,
)
from ..services import adb_manager

router = APIRouter(prefix="/api/v1/adb", tags=["adb"])


# --- Device management ---

@router.get("/devices", response_model=List[AdbDevice])
async def list_devices():
    """List all known ADB devices."""
    return await adb_manager.list_devices()


@router.post("/connect", response_model=AdbDevice)
async def connect_device(req: AdbConnectRequest):
    """Connect to a device over network ADB."""
    return await adb_manager.connect(req.ip, req.port)


@router.post("/disconnect/{serial:path}", response_model=AdbDevice)
async def disconnect_device(serial: str):
    """Disconnect a device."""
    return await adb_manager.disconnect(serial)


# --- Shell ---

@router.post("/shell", response_model=AdbShellResult)
async def run_shell(req: AdbShellRequest):
    """Execute a shell command on a device."""
    return await adb_manager.shell(req.serial, req.command, req.timeout)


# --- Key events ---

@router.post("/key")
async def send_key(req: AdbKeyEvent):
    """Send a key event to a device."""
    result = await adb_manager.send_key(req.serial, req.keycode)
    return {"status": "ok", "keycode": req.keycode, "exit_code": result.exit_code}


@router.get("/keycodes")
async def get_keycodes():
    """Get available STB remote keycodes."""
    return STB_KEYCODES


# --- Logcat ---

@router.post("/logcat/start", response_model=LogcatSession)
async def start_logcat(
    serial: str,
    filters: Optional[List[str]] = Query(None),
    scenario_id: Optional[str] = None,
):
    """Start a logcat streaming session."""
    return await adb_manager.start_logcat(serial, filters, scenario_id)


@router.post("/logcat/{session_id}/stop", response_model=LogcatSession)
async def stop_logcat(session_id: str):
    """Stop a logcat session. Auto-links to active test session."""
    try:
        result = await adb_manager.stop_logcat(session_id)

        from ..services import session_manager
        from ..models.session import ArtifactType
        await session_manager.auto_add_artifact(
            ArtifactType.LOGCAT,
            name=f"Logcat: {result.serial}",
            data={"logcat_session_id": session_id, "line_count": result.line_count},
            tags=["logcat", "adb"],
        )

        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/logcat", response_model=List[LogcatSession])
async def list_logcat_sessions():
    """List all logcat sessions."""
    return adb_manager.list_logcat_sessions()


@router.get("/logcat/{session_id}/lines", response_model=List[LogcatLine])
async def get_logcat_lines(
    session_id: str,
    last_n: int = Query(200, ge=1, le=5000),
    level: Optional[str] = None,
    tag: Optional[str] = None,
):
    """Get recent logcat lines from a session."""
    return adb_manager.get_logcat_lines(session_id, last_n, level, tag)


# --- File operations ---

@router.post("/pull")
async def pull_file(req: AdbFileRequest):
    """Pull a file from a device."""
    try:
        local_path = await adb_manager.pull_file(req.serial, req.remote_path)
        return {"status": "ok", "local_path": local_path}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/push")
async def push_file(req: AdbFileRequest):
    """Push a file to a device."""
    try:
        remote_path = await adb_manager.push_file(req.serial, req.local_path, req.remote_path)
        return {"status": "ok", "remote_path": remote_path}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/install")
async def install_apk(req: AdbInstallRequest):
    """Install an APK on a device."""
    try:
        output = await adb_manager.install_apk(req.serial, req.apk_path)
        return {"status": "ok", "output": output}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# --- Screenshots / Bugreport ---

@router.post("/screencap/{serial:path}")
async def take_screencap(serial: str):
    """Capture a screenshot and save on RPi. Auto-links to active session."""
    try:
        path = await adb_manager.screencap(serial)
        size = Path(path).stat().st_size if Path(path).exists() else 0

        # Auto-link to active session
        from ..services import session_manager
        from ..models.session import ArtifactType
        await session_manager.auto_add_artifact(
            ArtifactType.SCREENSHOT,
            name=f"Screenshot ({serial})",
            file_path=path,
            tags=["adb", "screenshot"],
            metadata={"serial": serial},
        )

        return {
            "status": "ok",
            "path": path,
            "filename": Path(path).name,
            "size_bytes": size,
        }
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/bugreport/{serial:path}")
async def take_bugreport(serial: str):
    """Capture a bugreport and save on RPi. Auto-links to active session."""
    try:
        path = await adb_manager.bugreport(serial)
        size = Path(path).stat().st_size if Path(path).exists() else 0

        # Auto-link to active session
        from ..services import session_manager
        from ..models.session import ArtifactType
        await session_manager.auto_add_artifact(
            ArtifactType.BUGREPORT,
            name=f"Bugreport ({serial})",
            file_path=path,
            tags=["adb", "bugreport"],
            metadata={"serial": serial},
        )

        return {
            "status": "ok",
            "path": path,
            "filename": Path(path).name,
            "size_bytes": size,
        }
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/files")
async def list_adb_files():
    """List all saved ADB files (screenshots, bugreports, pulled files)."""
    from ..services import storage
    paths = storage.get_data_paths()
    adb_dir = Path(paths.get("adb_files", "/tmp/wifry-adb-files"))

    files = []
    if adb_dir.exists():
        for f in sorted(adb_dir.rglob("*"), key=lambda x: x.stat().st_mtime if x.is_file() else 0, reverse=True):
            if not f.is_file():
                continue
            ftype = "screenshot" if "screen" in f.name else "bugreport" if "bugreport" in f.name else "file"
            files.append({
                "filename": f.name,
                "path": str(f),
                "type": ftype,
                "size_bytes": f.stat().st_size,
                "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            })
    return files


@router.get("/files/download/{filename}")
async def download_adb_file(filename: str):
    """Download an ADB file."""
    from ..services import storage
    paths = storage.get_data_paths()
    adb_dir = Path(paths.get("adb_files", "/tmp/wifry-adb-files"))

    file_path = adb_dir / filename
    if not file_path.exists():
        # Search recursively
        matches = list(adb_dir.rglob(filename))
        if not matches:
            raise HTTPException(404, "File not found")
        file_path = matches[0]

    # Security check
    try:
        file_path.resolve().relative_to(adb_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    media = "image/png" if file_path.suffix == ".png" else "application/zip" if file_path.suffix == ".zip" else "application/octet-stream"
    return FileResponse(file_path, filename=file_path.name, media_type=media)


@router.delete("/files/{filename}")
async def delete_adb_file(filename: str):
    """Delete an ADB file."""
    from ..services import storage
    paths = storage.get_data_paths()
    adb_dir = Path(paths.get("adb_files", "/tmp/wifry-adb-files"))

    file_path = adb_dir / filename
    if not file_path.exists():
        matches = list(adb_dir.rglob(filename))
        if not matches:
            raise HTTPException(404, "File not found")
        file_path = matches[0]

    file_path.unlink()
    return {"status": "ok", "filename": filename}
