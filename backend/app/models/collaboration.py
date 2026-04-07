"""Pydantic models for collaboration state."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CollaborationMode(str, Enum):
    CO_PILOT = "co-pilot"
    DOWNLOAD = "download"


class CollaborationUser(BaseModel):
    id: str
    name: str
    ip: str = ""
    connected_at: str
    last_activity: str


class CollaborationSharedState(BaseModel):
    active_tab: str = "sessions"
    active_sub_tab: Optional[str] = None
    nav: Optional[Dict[str, Any]] = None
    last_action: Optional[str] = None
    last_action_by: Optional[str] = None
    last_action_at: Optional[str] = None


class CollaborationStatus(BaseModel):
    mode: CollaborationMode = CollaborationMode.CO_PILOT
    connected_users: List[CollaborationUser] = Field(default_factory=list)
    user_count: int = 0
    shared_state: CollaborationSharedState = Field(default_factory=CollaborationSharedState)


class CollaborationPersistentState(BaseModel):
    mode: CollaborationMode = CollaborationMode.CO_PILOT
