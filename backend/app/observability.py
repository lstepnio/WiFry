"""Lightweight structured logging and request correlation utilities."""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_REQUEST_CONTEXT: ContextVar[Optional[Dict[str, str]]] = ContextVar("wifry_request_context", default=None)
_RESERVED_LOG_FIELDS = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def bind_request_context(
    *,
    request_id: str,
    method: str,
    path: str,
    client_ip: str = "",
    user_agent: str = "",
) -> Token:
    return _REQUEST_CONTEXT.set(
        {
            "request_id": request_id,
            "method": method,
            "path": path,
            "client_ip": client_ip,
            "user_agent": user_agent,
        }
    )


def reset_request_context(token: Token) -> None:
    _REQUEST_CONTEXT.reset(token)


def get_request_context() -> Dict[str, str]:
    return dict(_REQUEST_CONTEXT.get() or {})


def get_request_id() -> Optional[str]:
    return get_request_context().get("request_id")


def configure_logging(debug: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(RequestContextFilter())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=[handler],
        force=True,
    )


class RequestContextFilter(logging.Filter):
    """Inject request correlation data into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        record.request_id = context.get("request_id")
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Render logs as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_FIELDS or key == "request_id":
                continue
            if value is None:
                continue
            payload[key] = _serialize(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _serialize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    if hasattr(value, "model_dump"):
        return _serialize(value.model_dump(mode="json"))
    return str(value)
