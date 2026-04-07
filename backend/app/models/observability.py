"""Pydantic models for audit and diagnostics responses."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    timestamp: str
    action: str
    outcome: str = "success"
    actor: str = "operator"
    request_id: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    client_ip: Optional[str] = None
    resource_type: str = ""
    resource_id: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
