"""Support bundle generator.

Creates a self-contained zip archive containing all session artifacts
plus metadata (device info, impairment timeline, tags, notes).
The bundle can be shared via file.io or Cloudflare Tunnel.
"""

import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from ..config import settings
from ..models.session import SupportBundle, TestSession
from ..observability import get_request_id
from . import audit_log, session_manager

logger = logging.getLogger(__name__)

BUNDLES_DIR = Path("/var/lib/wifry/bundles") if not settings.mock_mode else Path("/tmp/wifry-bundles")


def _ensure_dir() -> Path:
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    return BUNDLES_DIR


async def generate_bundle(session_id: str) -> SupportBundle:
    """Generate a support bundle zip for a session."""
    session = session_manager.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    artifacts = session_manager.get_session_artifacts(session_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    generated_at = datetime.now(timezone.utc).isoformat()
    safe_name = session.name.replace(" ", "_").replace("/", "_")[:40]
    filename = f"wifry_bundle_{safe_name}_{ts}.zip"
    bundle_path = _ensure_dir() / filename
    diagnostics = _build_bundle_diagnostics(session, artifacts, generated_at)

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Session metadata
        meta = {
            "session": session.model_dump(),
            "generated_at": generated_at,
            "generator": "WiFry - IP Video Edition",
            "artifact_count": len(artifacts),
        }
        zf.writestr("metadata.json", json.dumps(meta, indent=2, default=str))

        # 2. Device info
        zf.writestr("device_info.json", session.device.model_dump_json(indent=2))

        # 3. Impairment timeline (history of all changes during session)
        if session.impairment_log:
            timeline = [snap.model_dump() for snap in session.impairment_log]
            zf.writestr("impairment_timeline.json", json.dumps(timeline, indent=2, default=str))

        # 3b. Current impairment state snapshot (what's active right now)
        try:
            from . import tc_manager, wifi_impairment, dns_manager
            from ..services.network import get_managed_interfaces
            current_state = {
                "snapshot_at": generated_at,
                "network": {},
                "wifi": wifi_impairment.get_state().model_dump(),
                "dns": dns_manager.get_status().model_dump(),
            }
            zf.writestr("current_impairment_state.json", json.dumps(current_state, indent=2, default=str))
            diagnostics["current_impairment_state_included"] = True
        except Exception:
            diagnostics["current_impairment_state_included"] = False

        # 4. Notes
        if session.notes:
            zf.writestr("notes.txt", session.notes)

        # 5. Tags
        if session.tags:
            zf.writestr("tags.txt", "\n".join(session.tags))

        # 6. Artifacts
        for artifact in artifacts:
            # Create artifact metadata
            art_meta = artifact.model_dump()
            art_dir = f"artifacts/{artifact.type.value}/{artifact.id}"

            zf.writestr(f"{art_dir}/metadata.json", json.dumps(art_meta, indent=2, default=str))

            # Include the actual file if it exists
            if artifact.file_path:
                fp = Path(artifact.file_path)
                if fp.exists() and fp.is_file():
                    zf.write(fp, f"{art_dir}/{fp.name}")
                    diagnostics["artifact_files_included"] += 1
                else:
                    diagnostics["artifact_files_missing"].append(
                        {
                            "artifact_id": artifact.id,
                            "name": artifact.name,
                            "type": artifact.type.value,
                            "file_path": artifact.file_path,
                        }
                    )

            # Include inline data
            if artifact.data:
                zf.writestr(f"{art_dir}/data.json", json.dumps(artifact.data, indent=2, default=str))
                diagnostics["inline_data_entries"] += 1

        # 7. Human-readable summary
        summary = _generate_summary(session, artifacts)
        zf.writestr("SUMMARY.md", summary)
        zf.writestr("diagnostics/bundle_diagnostics.json", json.dumps(diagnostics, indent=2, default=str))

    bundle_size = bundle_path.stat().st_size
    diagnostics["bundle_size_bytes"] = bundle_size

    bundle = SupportBundle(
        session_id=session_id,
        session_name=session.name,
        bundle_path=str(bundle_path),
        size_bytes=bundle_size,
        artifact_count=len(artifacts),
        created_at=generated_at,
        device=session.device,
        tags=session.tags,
        notes=session.notes,
        impairment_log=session.impairment_log,
        diagnostics=diagnostics,
    )

    # Auto-add the bundle as an artifact to the session
    await session_manager.add_artifact(
        session_id,
        session_manager.ArtifactType.REPORT,
        name=f"Support Bundle: {filename}",
        file_path=str(bundle_path),
        tags=["bundle", "support"],
    )

    logger.info(
        "bundle.generated",
        extra={
            "event": "support_bundle",
            "session_id": session_id,
            "bundle_name": filename,
            "artifact_count": len(artifacts),
            "size_bytes": bundle_size,
            "missing_artifact_files": len(diagnostics["artifact_files_missing"]),
        },
    )
    audit_log.record_event(
        "session.bundle.generate",
        resource_type="session",
        resource_id=session_id,
        details={
            "bundle_name": filename,
            "artifact_count": len(artifacts),
            "size_bytes": bundle_size,
            "missing_artifact_files": len(diagnostics["artifact_files_missing"]),
        },
    )
    return bundle


def list_bundles() -> list:
    """List generated bundles."""
    d = _ensure_dir()
    bundles = []
    for f in sorted(d.glob("*.zip"), reverse=True):
        bundles.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return bundles


def _generate_summary(session: TestSession, artifacts: list) -> str:
    """Generate a human-readable markdown summary for the bundle."""
    lines = [
        f"# WiFry Support Bundle",
        f"",
        f"**Session:** {session.name}",
        f"**ID:** {session.id}",
        f"**Status:** {session.status.value}",
        f"**Created:** {session.created_at}",
        f"**Completed:** {session.completed_at or 'N/A'}",
        f"",
    ]

    if session.device.model:
        lines.extend([
            f"## Device Under Test",
            f"- **Model:** {session.device.manufacturer} {session.device.model}",
            f"- **Serial:** {session.device.serial}",
            f"- **Android:** {session.device.android_version}",
            f"- **IP:** {session.device.ip_address}",
            f"",
        ])

    if session.tags:
        lines.extend([f"## Tags", f"", f"{', '.join(session.tags)}", f""])

    if session.notes:
        lines.extend([f"## Notes", f"", session.notes, f""])

    if session.description:
        lines.extend([f"## Description", f"", session.description, f""])

    # Artifact summary by type
    type_counts = {}
    for art in artifacts:
        type_counts[art.type.value] = type_counts.get(art.type.value, 0) + 1

    lines.extend([f"## Artifacts ({len(artifacts)} total)", f""])
    for atype, count in sorted(type_counts.items()):
        lines.append(f"- **{atype}:** {count}")
    lines.append("")

    # Artifact details
    lines.extend([f"## Artifact Details", f""])
    for art in sorted(artifacts, key=lambda a: a.created_at):
        lines.append(f"### [{art.type.value}] {art.name}")
        lines.append(f"- ID: {art.id}")
        lines.append(f"- Created: {art.created_at}")
        if art.file_path:
            lines.append(f"- File: {Path(art.file_path).name}")
        if art.size_bytes:
            lines.append(f"- Size: {art.size_bytes:,} bytes")
        if art.tags:
            lines.append(f"- Tags: {', '.join(art.tags)}")
        if art.description:
            lines.append(f"- {art.description}")
        lines.append("")

    # Impairment timeline
    if session.impairment_log:
        lines.extend([f"## Impairment Timeline", f""])
        for snap in session.impairment_log:
            label = snap.label or snap.profile_name or "Custom"
            lines.append(f"- **{snap.timestamp}** — {label}")
        lines.append("")

    lines.append(f"---")
    lines.append(f"*Generated by WiFry - IP Video Edition*")

    return "\n".join(lines)


def _build_bundle_diagnostics(session: TestSession, artifacts: list, generated_at: str) -> Dict[str, object]:
    artifact_counts: Dict[str, int] = {}
    for artifact in artifacts:
        artifact_counts[artifact.type.value] = artifact_counts.get(artifact.type.value, 0) + 1

    return {
        "generated_at": generated_at,
        "request_id": get_request_id(),
        "purpose": "Session-scoped packaging diagnostics for STB/test evidence handoff",
        "session_id": session.id,
        "session_name": session.name,
        "session_status": session.status.value,
        "artifact_count": len(artifacts),
        "artifact_files_included": 0,
        "artifact_files_missing": [],
        "artifacts_by_type": artifact_counts,
        "inline_data_entries": 0,
        "includes_appliance_diagnostics": False,
    }
