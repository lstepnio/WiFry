"""Append-only audit events for destructive or external actions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.observability import AuditEvent
from ..observability import get_request_context
from . import storage

logger = logging.getLogger(__name__)
AUDIT_LOG_NAME = "audit.log.jsonl"


def _audit_log_path() -> Path:
    return storage.ensure_data_path("logs") / AUDIT_LOG_NAME


def record_event(
    action: str,
    *,
    outcome: str = "success",
    actor: str = "",
    resource_type: str = "",
    resource_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> dict:
    context = get_request_context()
    event = AuditEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        action=action,
        outcome=outcome,
        actor=actor or context.get("client_ip") or "operator",
        request_id=context.get("request_id"),
        method=context.get("method"),
        path=context.get("path"),
        client_ip=context.get("client_ip"),
        resource_type=resource_type,
        resource_id=resource_id,
        details=_sanitize(details or {}),
    )

    path = _audit_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json())
        handle.write("\n")

    logger.info(
        "audit.event",
        extra={
            "event": "audit",
            "action": event.action,
            "outcome": event.outcome,
            "actor": event.actor,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "details": event.details,
        },
    )
    return event.model_dump(mode="json")


def list_events(limit: int = 100, action: Optional[str] = None) -> List[dict]:
    path = _audit_log_path()
    if not path.exists():
        return []

    events: List[AuditEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = AuditEvent.model_validate_json(line)
        except Exception:
            continue
        if action and event.action != action:
            continue
        events.append(event)

    return [event.model_dump(mode="json") for event in reversed(events[-max(1, min(limit, 500)):])]


def _sanitize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    return str(value)
