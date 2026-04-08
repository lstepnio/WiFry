"""STB_AUTOMATION — Automatic diagnostic collection.

When an anomaly is detected (or manually triggered), this module
collects a bundle of diagnostics from the STB:

  1. Logcat context window (lines around the event)
  2. ADB screenshot
  3. ADB bugreport (for critical/high severity)
  4. ``dumpsys media.player`` output
  5. ``dumpsys netstats`` output
  6. ``dumpsys meminfo`` output
  7. HDMI frame snapshot (if video capture is active)

All artifacts are stored via ``session_manager.auto_add_artifact()``
so they auto-link to the active test session.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from ...config import settings
from ...services import adb_manager, session_manager
from .models import DetectedAnomaly

logger = logging.getLogger("wifry.stb_automation.diagnostics")

# Artifact type imports — use string enum values to avoid tight coupling
try:
    from ...models.session import ArtifactType
except ImportError:
    ArtifactType = None  # type: ignore


async def collect_diagnostics(
    serial: str,
    reason: str = "manual",
    severity: str = "medium",
    anomaly: Optional[DetectedAnomaly] = None,
) -> dict:
    """Collect diagnostic artifacts from the STB.

    Parameters
    ----------
    serial:
        ADB device serial.
    reason:
        Why diagnostics are being collected (e.g. "anr", "crash", "manual").
    severity:
        Anomaly severity — controls which diagnostics are collected.
        "critical"/"high" → full collection including bugreport.
        "medium"/"low" → lightweight collection (skip bugreport).
    anomaly:
        Optional DetectedAnomaly that triggered the collection.

    Returns
    -------
    dict with collected artifact paths/IDs.
    """
    now = datetime.now(timezone.utc).isoformat()
    results: dict = {
        "collected_at": now,
        "reason": reason,
        "severity": severity,
        "artifacts": [],
    }

    # 1. ADB screenshot
    try:
        screenshot_path = await adb_manager.screencap(serial)
        results["screenshot"] = screenshot_path
        results["artifacts"].append("screenshot")
        await _auto_artifact(
            "screenshot",
            f"STB Diagnostic Screenshot ({reason})",
            file_path=screenshot_path,
            tags=["stb_automation", "diagnostic", reason],
        )
    except Exception as e:
        logger.warning("[STB_AUTOMATION] Screenshot failed: %s", e)
        results["screenshot_error"] = str(e)

    # 2. dumpsys media.player
    try:
        media_result = await adb_manager.shell(serial, "dumpsys media.player", timeout=10)
        results["artifacts"].append("media_player_state")
        await _auto_artifact(
            "shell_output",
            f"dumpsys media.player ({reason})",
            data={"command": "dumpsys media.player", "stdout": media_result.stdout[:10000]},
            tags=["stb_automation", "diagnostic", "media", reason],
        )
    except Exception as e:
        logger.warning("[STB_AUTOMATION] dumpsys media.player failed: %s", e)

    # 3. dumpsys netstats
    try:
        net_result = await adb_manager.shell(serial, "dumpsys netstats", timeout=10)
        results["artifacts"].append("netstats")
        await _auto_artifact(
            "shell_output",
            f"dumpsys netstats ({reason})",
            data={"command": "dumpsys netstats", "stdout": net_result.stdout[:10000]},
            tags=["stb_automation", "diagnostic", "network", reason],
        )
    except Exception as e:
        logger.warning("[STB_AUTOMATION] dumpsys netstats failed: %s", e)

    # 4. dumpsys meminfo
    try:
        mem_result = await adb_manager.shell(serial, "dumpsys meminfo", timeout=10)
        results["artifacts"].append("meminfo")
        await _auto_artifact(
            "shell_output",
            f"dumpsys meminfo ({reason})",
            data={"command": "dumpsys meminfo", "stdout": mem_result.stdout[:10000]},
            tags=["stb_automation", "diagnostic", "memory", reason],
        )
    except Exception as e:
        logger.warning("[STB_AUTOMATION] dumpsys meminfo failed: %s", e)

    # 5. Bugreport (critical/high only — takes ~60-120s)
    if severity in ("critical", "high"):
        try:
            bugreport_path = await adb_manager.bugreport(serial)
            results["bugreport"] = bugreport_path
            results["artifacts"].append("bugreport")
            await _auto_artifact(
                "bugreport",
                f"STB Bugreport ({reason})",
                file_path=bugreport_path,
                tags=["stb_automation", "diagnostic", reason],
            )
        except Exception as e:
            logger.warning("[STB_AUTOMATION] Bugreport failed: %s", e)
            results["bugreport_error"] = str(e)

    # 6. HDMI frame snapshot (if video capture is active)
    try:
        from ..video_capture import streamer
        if streamer.is_running():
            frame = streamer.get_latest_frame()
            if frame:
                results["artifacts"].append("hdmi_frame")
                await _auto_artifact(
                    "hdmi_frame",
                    f"HDMI Frame ({reason})",
                    data={"size_bytes": len(frame)},
                    tags=["stb_automation", "diagnostic", "hdmi", reason],
                )
    except (ImportError, Exception) as e:
        logger.debug("[STB_AUTOMATION] HDMI frame not available: %s", e)

    # 7. Logcat context (from anomaly if provided)
    if anomaly and anomaly.context_lines:
        await _auto_artifact(
            "logcat",
            f"Logcat Context ({reason})",
            data={
                "context_lines": anomaly.context_lines,
                "pattern": anomaly.pattern_name,
                "severity": anomaly.severity,
            },
            tags=["stb_automation", "diagnostic", "logcat", reason],
        )
        results["artifacts"].append("logcat_context")

    logger.info(
        "[STB_AUTOMATION] Diagnostics collected: reason=%s severity=%s artifacts=%s",
        reason, severity, results["artifacts"],
    )
    return results


async def _auto_artifact(
    artifact_type_str: str,
    name: str,
    file_path: Optional[str] = None,
    data: Optional[dict] = None,
    tags: Optional[List[str]] = None,
) -> None:
    """Add an artifact to the active session if available."""
    if ArtifactType is None:
        return

    type_map = {
        "screenshot": ArtifactType.SCREENSHOT,
        "bugreport": ArtifactType.BUGREPORT,
        "shell_output": ArtifactType.SHELL_OUTPUT,
        "logcat": ArtifactType.LOGCAT,
        "hdmi_frame": ArtifactType.HDMI_FRAME,
    }
    artifact_type = type_map.get(artifact_type_str)
    if artifact_type is None:
        return

    try:
        kwargs: dict = {"tags": tags or []}
        if file_path:
            kwargs["file_path"] = file_path
        if data:
            kwargs["data"] = data
        await session_manager.auto_add_artifact(artifact_type, name, **kwargs)
    except Exception as e:
        logger.debug("[STB_AUTOMATION] auto_add_artifact failed: %s", e)
