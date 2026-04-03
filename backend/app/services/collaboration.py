"""Collaboration / Shadow mode.

Enables real-time synchronized viewing and co-control of WiFry
across multiple users connected via Cloudflare Tunnel.

Modes:
  - spectate:  View-only — remote users see everything but can't change anything
  - co-pilot:  Anyone can drive — all users see the same state, anyone can interact
  - download:  Download-only — tunnel only exposes the file share endpoints

State sync is done via WebSocket broadcast. When any user navigates,
applies impairments, starts a capture, etc., all connected clients
receive a state update and their UI reflects the change.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class CollaborationMode:
    SPECTATE = "spectate"    # View-only
    CO_PILOT = "co-pilot"    # Anyone can drive
    DOWNLOAD = "download"    # File share only


_mode: str = CollaborationMode.CO_PILOT
_connected_users: Dict[str, dict] = {}
_websockets: Dict[str, WebSocket] = {}
_shared_state: dict = {
    "active_tab": "sessions",
    "last_action": None,
    "last_action_by": None,
    "last_action_at": None,
}


def get_mode() -> str:
    return _mode


def set_mode(mode: str) -> dict:
    global _mode
    if mode not in (CollaborationMode.SPECTATE, CollaborationMode.CO_PILOT, CollaborationMode.DOWNLOAD):
        raise ValueError(f"Invalid mode: {mode}. Use: spectate, co-pilot, download")
    _mode = mode
    logger.info("Collaboration mode set to: %s", mode)

    # Notify all connected users
    asyncio.create_task(_broadcast({
        "type": "mode_change",
        "mode": mode,
    }))

    return get_status()


def get_status() -> dict:
    return {
        "mode": _mode,
        "connected_users": list(_connected_users.values()),
        "user_count": len(_connected_users),
        "shared_state": _shared_state,
    }


async def connect_user(ws: WebSocket, name: str = "") -> str:
    """Register a new connected user."""
    user_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()

    user = {
        "id": user_id,
        "name": name or f"User-{user_id[:4]}",
        "connected_at": now,
        "is_local": not name,  # Local user has no explicit name
        "last_activity": now,
    }

    _connected_users[user_id] = user
    _websockets[user_id] = ws

    logger.info("User connected: %s (%s)", user["name"], user_id)

    # Notify others
    await _broadcast({
        "type": "user_joined",
        "user": user,
        "user_count": len(_connected_users),
    }, exclude=user_id)

    # Send current state to the new user
    await _send(user_id, {
        "type": "init",
        "mode": _mode,
        "users": list(_connected_users.values()),
        "state": _shared_state,
    })

    return user_id


async def disconnect_user(user_id: str) -> None:
    """Remove a disconnected user."""
    user = _connected_users.pop(user_id, None)
    _websockets.pop(user_id, None)

    if user:
        logger.info("User disconnected: %s", user["name"])
        await _broadcast({
            "type": "user_left",
            "user_id": user_id,
            "user_name": user["name"],
            "user_count": len(_connected_users),
        })


async def handle_message(user_id: str, data: dict) -> None:
    """Process a message from a connected user."""
    msg_type = data.get("type", "")
    user = _connected_users.get(user_id)

    if not user:
        return

    user["last_activity"] = datetime.now(timezone.utc).isoformat()

    if msg_type == "navigate":
        # User changed tab — sync to all
        _shared_state["active_tab"] = data.get("tab", "sessions")
        _shared_state["last_action"] = f"Navigated to {data.get('tab')}"
        _shared_state["last_action_by"] = user["name"]
        _shared_state["last_action_at"] = user["last_activity"]

        await _broadcast({
            "type": "navigate",
            "tab": data.get("tab"),
            "by": user["name"],
        }, exclude=user_id if _mode == CollaborationMode.CO_PILOT else None)

    elif msg_type == "action":
        # User performed an action (apply impairment, start capture, etc.)
        if _mode == CollaborationMode.SPECTATE and not user.get("is_local"):
            # Remote spectators can't perform actions
            await _send(user_id, {
                "type": "error",
                "message": "View-only mode — actions are disabled for remote users",
            })
            return

        action = data.get("action", "")
        _shared_state["last_action"] = action
        _shared_state["last_action_by"] = user["name"]
        _shared_state["last_action_at"] = user["last_activity"]

        await _broadcast({
            "type": "action",
            "action": action,
            "detail": data.get("detail"),
            "by": user["name"],
        }, exclude=user_id)

    elif msg_type == "cursor":
        # Cursor position for co-pilot presence indicators
        await _broadcast({
            "type": "cursor",
            "user_id": user_id,
            "user_name": user["name"],
            "x": data.get("x", 0),
            "y": data.get("y", 0),
        }, exclude=user_id)

    elif msg_type == "chat":
        # Simple text chat between users
        await _broadcast({
            "type": "chat",
            "user_id": user_id,
            "user_name": user["name"],
            "message": data.get("message", ""),
            "timestamp": user["last_activity"],
        })


async def broadcast_state_update(action: str, detail: Optional[dict] = None) -> None:
    """Called by other services to broadcast state changes to all users.

    E.g., when impairments are applied, captures start, etc.
    """
    _shared_state["last_action"] = action
    _shared_state["last_action_at"] = datetime.now(timezone.utc).isoformat()

    await _broadcast({
        "type": "state_update",
        "action": action,
        "detail": detail,
    })


# --- Internal ---

async def _broadcast(msg: dict, exclude: Optional[str] = None) -> None:
    """Send a message to all connected WebSockets."""
    payload = json.dumps(msg)
    disconnected = []

    for uid, ws in _websockets.items():
        if uid == exclude:
            continue
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.append(uid)

    for uid in disconnected:
        await disconnect_user(uid)


async def _send(user_id: str, msg: dict) -> None:
    """Send a message to a specific user."""
    ws = _websockets.get(user_id)
    if ws:
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            await disconnect_user(user_id)
