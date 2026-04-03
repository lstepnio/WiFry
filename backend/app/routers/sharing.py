"""Tunnel + sharing router.

Manages Cloudflare Quick Tunnel and provides read-only file sharing
endpoints for diagnostics (reports, captures, analysis, screenshots).
"""

import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse

from pydantic import BaseModel, Field

from ..services import tunnel, annotations, fileio, collaboration
from ..services import report_generator
from ..services import storage

router = APIRouter(tags=["sharing"])


# --- Tunnel control ---

@router.get("/api/v1/tunnel/status")
async def tunnel_status():
    """Get Cloudflare tunnel status and URL."""
    return tunnel.get_status()


@router.post("/api/v1/tunnel/start")
async def start_tunnel(port: int = 8080):
    """Start a Cloudflare Quick Tunnel for sharing."""
    return await tunnel.start_tunnel(port)


@router.post("/api/v1/tunnel/stop")
async def stop_tunnel():
    """Stop the Cloudflare tunnel."""
    return await tunnel.stop_tunnel()


@router.get("/api/v1/tunnel/check")
async def check_cloudflared():
    """Check if cloudflared is installed."""
    return await tunnel.check_cloudflared()


# --- Public sharing index (accessible via tunnel) ---

@router.get("/api/v1/share")
async def share_index():
    """List all shareable diagnostic files.

    This is the landing page when someone visits the tunnel URL.
    Returns categorized list of downloadable files.
    """
    paths = storage.get_data_paths()
    items = {}

    for category, dir_path in paths.items():
        if category.startswith("_"):
            continue
        p = Path(dir_path)
        if not p.exists():
            items[category] = []
            continue

        files = []
        for f in sorted(p.rglob("*"), key=lambda x: x.stat().st_mtime if x.is_file() else 0, reverse=True):
            if not f.is_file():
                continue
            files.append({
                "name": f.name,
                "path": str(f.relative_to(p)),
                "size_bytes": f.stat().st_size,
                "download_url": f"/api/v1/share/{category}/{f.relative_to(p)}",
            })
            if len(files) >= 50:  # Cap per category
                break

        items[category] = files

    # Include annotations
    notes = annotations.get_annotations()
    items["annotations"] = notes[:50]

    # Include reports
    items["reports"] = report_generator.list_reports()[:20]

    return {
        "title": "WiFry - IP Video Edition - Shared Diagnostics",
        "categories": items,
        "tunnel": tunnel.get_status(),
    }


@router.get("/api/v1/share/{category}/{file_path:path}")
async def download_shared_file(category: str, file_path: str):
    """Download a shared diagnostic file."""
    paths = storage.get_data_paths()
    base = paths.get(category)
    if not base:
        raise HTTPException(404, f"Unknown category: {category}")

    full_path = Path(base) / file_path
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(404, "File not found")

    # Security: ensure the path doesn't escape the base directory
    try:
        full_path.resolve().relative_to(Path(base).resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    # Determine media type
    suffix = full_path.suffix.lower()
    media_types = {
        ".html": "text/html",
        ".json": "application/json",
        ".pcap": "application/vnd.tcpdump.pcap",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".mp4": "video/mp4",
        ".ts": "video/mp2t",
        ".zip": "application/zip",
        ".log": "text/plain",
        ".txt": "text/plain",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(full_path, filename=full_path.name, media_type=media_type)


# --- File.io uploads ---

class FileUploadRequest(BaseModel):
    file_path: str = Field(..., description="Local file path to upload")
    expires: str = Field("15m", description="Expiry: 15m, 30m, 1h, 6h, 12h, 1d")


class BundleUploadRequest(BaseModel):
    file_paths: List[str] = Field(..., description="List of local file paths to bundle")
    bundle_name: str = ""
    expires: str = Field("15m", description="Expiry: 15m, 30m, 1h, 6h, 12h, 1d (max 1 day)")


class CategoryUploadRequest(BaseModel):
    category: str = Field(..., description="Data category: captures, reports, logs, etc.")
    expires: str = Field("15m", description="Expiry: 15m, 30m, 1h, 6h, 12h, 1d (max 1 day)")


@router.post("/api/v1/fileio/upload")
async def upload_file(req: FileUploadRequest):
    """Upload a single file to file.io and get a shareable link."""
    return await fileio.upload_file(req.file_path, req.expires)


@router.post("/api/v1/fileio/upload-bundle")
async def upload_bundle(req: BundleUploadRequest):
    """Bundle multiple files into a zip and upload to file.io."""
    return await fileio.upload_bundle(req.file_paths, req.bundle_name, req.expires)


@router.post("/api/v1/fileio/upload-category")
async def upload_category(req: CategoryUploadRequest):
    """Upload all files from a category (captures, reports, etc.) as a zip."""
    return await fileio.upload_category(req.category, req.expires)


@router.get("/api/v1/fileio/history")
async def upload_history():
    """Get file.io upload history."""
    return fileio.get_history()


# --- Collaboration / Shadow Mode ---

@router.get("/api/v1/collab/status")
async def collab_status():
    """Get collaboration mode status and connected users."""
    return collaboration.get_status()


class CollabModeRequest(BaseModel):
    mode: str = Field(..., description="spectate, co-pilot, or download")


@router.put("/api/v1/collab/mode")
async def set_collab_mode(req: CollabModeRequest):
    """Set collaboration mode: spectate (view-only), co-pilot (shared control), download (files only)."""
    try:
        return collaboration.set_mode(req.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.websocket("/api/v1/collab/ws")
async def collab_websocket(ws: WebSocket, name: str = ""):
    """WebSocket for real-time collaboration sync."""
    await ws.accept()
    user_id = await collaboration.connect_user(ws, name)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                await collaboration.handle_message(user_id, data)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await collaboration.disconnect_user(user_id)
    except Exception:
        await collaboration.disconnect_user(user_id)
