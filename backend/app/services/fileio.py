"""File.io upload service for one-click diagnostic sharing.

Uploads files to file.io (free, no account needed) which provides
a single-use download link that auto-expires. Alternative to
Cloudflare Tunnel for quick one-off file sharing.

Supports:
  - Single file upload (capture, report, screenshot)
  - Bundle upload (zip multiple files together)
  - Configurable expiry (default 14 days)
"""

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from ..config import settings
from ..observability import get_request_id
from ..services import storage
from . import audit_log

logger = logging.getLogger(__name__)

FILEIO_API = "https://www.file.io"

# History of uploads
_upload_history: List[dict] = []


async def upload_file(
    file_path: str,
    expires: str = "15m",
) -> dict:
    """Upload a single file to file.io.

    Args:
        file_path: Local path to the file.
        expires: Expiry duration (e.g., "14d", "1w", "6h").

    Returns:
        dict with success, link, expires, etc.
    """
    p = Path(file_path)
    if not p.exists():
        audit_log.record_event(
            "sharing.fileio.upload",
            outcome="error",
            resource_type="file",
            resource_id=Path(file_path).name,
            details={"filename": Path(file_path).name, "error": "File not found"},
        )
        return {"success": False, "error": f"File not found: {file_path}"}

    if settings.mock_mode:
        result = _mock_upload(p.name, p.stat().st_size, expires)
        _upload_history.append(result)
        audit_log.record_event(
            "sharing.fileio.upload",
            resource_type="file",
            resource_id=p.name,
            details={
                "filename": p.name,
                "size_bytes": p.stat().st_size,
                "expires": expires,
                "mock_mode": True,
            },
        )
        return result

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            with open(p, "rb") as f:
                resp = await client.post(
                    FILEIO_API,
                    files={"file": (p.name, f)},
                    data={"expires": expires, "autoDelete": "true", "maxDownloads": "1"},
                )

            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "success": data.get("success", False),
                    "link": data.get("link", ""),
                    "key": data.get("key", ""),
                    "filename": p.name,
                    "size_bytes": p.stat().st_size,
                    "expires": expires,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "request_id": get_request_id(),
                }
                _upload_history.append(result)
                logger.info(
                    "fileio.uploaded",
                    extra={
                        "event": "fileio_upload",
                        "filename": p.name,
                        "size_bytes": p.stat().st_size,
                        "expires": expires,
                        "share_key": result["key"],
                    },
                )
                audit_log.record_event(
                    "sharing.fileio.upload",
                    resource_type="file",
                    resource_id=p.name,
                    details={
                        "filename": p.name,
                        "size_bytes": p.stat().st_size,
                        "expires": expires,
                        "share_key": result["key"],
                    },
                )
                return result
            else:
                audit_log.record_event(
                    "sharing.fileio.upload",
                    outcome="error",
                    resource_type="file",
                    resource_id=p.name,
                    details={"filename": p.name, "status_code": resp.status_code},
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    except Exception as e:
        logger.error("fileio.upload_failed", extra={"event": "fileio_upload", "filename": p.name, "error": str(e)})
        audit_log.record_event(
            "sharing.fileio.upload",
            outcome="error",
            resource_type="file",
            resource_id=p.name,
            details={"filename": p.name, "error": str(e)},
        )
        return {"success": False, "error": str(e)}


async def upload_bundle(
    file_paths: List[str],
    bundle_name: str = "",
    expires: str = "15m",
) -> dict:
    """Bundle multiple files into a zip and upload to file.io."""
    if not file_paths:
        audit_log.record_event(
            "sharing.fileio.upload_bundle",
            outcome="error",
            resource_type="bundle",
            details={"error": "No files provided"},
        )
        return {"success": False, "error": "No files provided"}

    if not bundle_name:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle_name = f"wifry_diagnostics_{ts}.zip"

    # Create zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in file_paths:
            p = Path(fp)
            if p.exists() and p.is_file():
                zf.write(p, p.name)

    zip_buffer.seek(0)
    zip_size = zip_buffer.getbuffer().nbytes

    if settings.mock_mode:
        result = _mock_upload(bundle_name, zip_size, expires)
        result["files_bundled"] = len(file_paths)
        _upload_history.append(result)
        audit_log.record_event(
            "sharing.fileio.upload_bundle",
            resource_type="bundle",
            resource_id=bundle_name,
            details={
                "bundle_name": bundle_name,
                "files_bundled": len(file_paths),
                "size_bytes": zip_size,
                "expires": expires,
                "mock_mode": True,
            },
        )
        return result

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.post(
                FILEIO_API,
                files={"file": (bundle_name, zip_buffer, "application/zip")},
                data={"expires": expires, "autoDelete": "true", "maxDownloads": "1"},
            )

            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "success": data.get("success", False),
                    "link": data.get("link", ""),
                    "key": data.get("key", ""),
                    "filename": bundle_name,
                    "size_bytes": zip_size,
                    "files_bundled": len(file_paths),
                    "expires": expires,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "request_id": get_request_id(),
                }
                _upload_history.append(result)
                logger.info(
                    "fileio.bundle_uploaded",
                    extra={
                        "event": "fileio_bundle_upload",
                        "bundle_name": bundle_name,
                        "files_bundled": len(file_paths),
                        "size_bytes": zip_size,
                        "expires": expires,
                        "share_key": result["key"],
                    },
                )
                audit_log.record_event(
                    "sharing.fileio.upload_bundle",
                    resource_type="bundle",
                    resource_id=bundle_name,
                    details={
                        "bundle_name": bundle_name,
                        "files_bundled": len(file_paths),
                        "size_bytes": zip_size,
                        "expires": expires,
                        "share_key": result["key"],
                    },
                )
                return result
            else:
                audit_log.record_event(
                    "sharing.fileio.upload_bundle",
                    outcome="error",
                    resource_type="bundle",
                    resource_id=bundle_name,
                    details={"bundle_name": bundle_name, "status_code": resp.status_code},
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    except Exception as e:
        logger.error("fileio.bundle_upload_failed", extra={"event": "fileio_bundle_upload", "bundle_name": bundle_name, "error": str(e)})
        audit_log.record_event(
            "sharing.fileio.upload_bundle",
            outcome="error",
            resource_type="bundle",
            resource_id=bundle_name,
            details={"bundle_name": bundle_name, "error": str(e)},
        )
        return {"success": False, "error": str(e)}


async def upload_category(category: str, expires: str = "14d") -> dict:
    """Upload all files from a data category (captures, reports, etc.) as a bundle."""
    paths = storage.get_data_paths()
    dir_path = paths.get(category)
    if not dir_path:
        audit_log.record_event(
            "sharing.fileio.upload_category",
            outcome="error",
            resource_type="category",
            resource_id=category,
            details={"error": "Unknown category"},
        )
        return {"success": False, "error": f"Unknown category: {category}"}

    p = Path(dir_path)
    if not p.exists():
        audit_log.record_event(
            "sharing.fileio.upload_category",
            outcome="error",
            resource_type="category",
            resource_id=category,
            details={"error": "No files in category"},
        )
        return {"success": False, "error": f"No files in {category}"}

    files = [str(f) for f in p.rglob("*") if f.is_file()]
    if not files:
        audit_log.record_event(
            "sharing.fileio.upload_category",
            outcome="error",
            resource_type="category",
            resource_id=category,
            details={"error": "No files in category"},
        )
        return {"success": False, "error": f"No files in {category}"}

    audit_log.record_event(
        "sharing.fileio.upload_category",
        resource_type="category",
        resource_id=category,
        details={"file_count": len(files), "expires": expires},
    )
    return await upload_bundle(files, bundle_name=f"wifry_{category}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip", expires=expires)


def get_history() -> List[dict]:
    """Get upload history."""
    return list(reversed(_upload_history))


def _mock_upload(filename: str, size: int, expires: str) -> dict:
    import random
    key = f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))}"
    return {
        "success": True,
        "link": f"https://file.io/{key}",
        "key": key,
        "filename": filename,
        "size_bytes": size,
        "expires": expires,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "request_id": get_request_id(),
    }
