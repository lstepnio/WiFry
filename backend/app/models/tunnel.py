"""Pydantic models for tunnel state."""

from typing import Optional

from pydantic import BaseModel


class TunnelStatus(BaseModel):
    active: bool = False
    url: Optional[str] = None
    started_at: Optional[str] = None
    share_url: Optional[str] = None
    message: str = "Tunnel not active"
