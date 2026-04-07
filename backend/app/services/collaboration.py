"""Collaboration mode for WiFry.

Modes:
  - co-pilot: Anyone can drive — all users see the same state, anyone can interact
  - download: Download-only — tunnel exposes file share endpoints only
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class CollaborationMode:
    CO_PILOT = "co-pilot"    # Anyone can drive
    DOWNLOAD = "download"    # File share only


_mode: str = CollaborationMode.CO_PILOT
_connected_users: Dict[str, dict] = {}
_websockets: Dict[str, WebSocket] = {}
_shared_state: dict = {
    "active_tab": "sessions",
    "active_sub_tab": None,
    "last_action": None,
    "last_action_by": None,
    "last_action_at": None,
}
_heartbeat_task: Optional[asyncio.Task] = None
HEARTBEAT_INTERVAL = 15
INACTIVITY_TIMEOUT = 60


def get_mode() -> str:
    return _mode


def set_mode(mode: str) -> dict:
    global _mode
    if mode not in (CollaborationMode.CO_PILOT, CollaborationMode.DOWNLOAD):
        raise ValueError(f"Invalid mode: {mode}. Use: co-pilot, download")
    _mode = mode
    logger.info("Collaboration mode set to: %s", mode)
    asyncio.create_task(_broadcast({"type": "mode_change", "mode": mode}))
    return get_status()


def get_status() -> dict:
    return {
        "mode": _mode,
        "connected_users": list(_connected_users.values()),
        "user_count": len(_connected_users),
        "shared_state": _shared_state,
    }


# --- Heartbeat ---

async def _heartbeat_loop() -> None:
    """Ping to detect dead connections and remove stale users."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        now = datetime.now(timezone.utc)
        stale = []

        for uid, ws in list(_websockets.items()):
            user = _connected_users.get(uid)
            if not user:
                stale.append(uid)
                continue
            try:
                last = datetime.fromisoformat(user["last_activity"])
                if (now - last).total_seconds() > INACTIVITY_TIMEOUT:
                    stale.append(uid)
                    continue
            except (ValueError, KeyError):
                pass
            try:
                await ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                stale.append(uid)

        for uid in stale:
            logger.info("Removing stale user: %s", uid)
            await disconnect_user(uid)


def _ensure_heartbeat() -> None:
    global _heartbeat_task
    if _heartbeat_task is None or _heartbeat_task.done():
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())


# --- User management ---

async def connect_user(ws: WebSocket, name: str = "", ip: str = "") -> str:
    """Register a new connected user."""
    _ensure_heartbeat()
    user_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()

    display_name = name or f"User-{user_id[:4]}"
    if ip:
        display_name = f"{display_name} ({ip})"

    user = {
        "id": user_id,
        "name": display_name,
        "ip": ip,
        "connected_at": now,
        "last_activity": now,
    }

    _connected_users[user_id] = user
    _websockets[user_id] = ws

    logger.info("User connected: %s from %s", display_name, ip)

    await _broadcast({
        "type": "user_joined",
        "user": user,
        "user_count": len(_connected_users),
    }, exclude=user_id)

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


async def disconnect_all_users() -> None:
    """Disconnect all users. Called when tunnel stops."""
    for uid in list(_websockets.keys()):
        try:
            ws = _websockets.get(uid)
            if ws:
                await ws.send_text(json.dumps({
                    "type": "tunnel_closed",
                    "message": "Sharing tunnel has been stopped",
                }))
                await ws.close()
        except Exception:
            pass
        await disconnect_user(uid)
    logger.info("All collaboration users disconnected")


# --- Message handling ---

async def handle_message(user_id: str, data: dict) -> None:
    """Process a message from a connected user."""
    msg_type = data.get("type", "")
    user = _connected_users.get(user_id)

    if not user:
        return

    user["last_activity"] = datetime.now(timezone.utc).isoformat()

    if msg_type == "navigate":
        tab = data.get("tab", "sessions")
        sub_tab = data.get("subTab")
        _shared_state["active_tab"] = tab
        _shared_state["active_sub_tab"] = sub_tab
        _shared_state["last_action"] = f"Navigated to {tab}" + (f" > {sub_tab}" if sub_tab else "")
        _shared_state["last_action_by"] = user["name"]
        _shared_state["last_action_at"] = user["last_activity"]

        await _broadcast({
            "type": "navigate",
            "tab": tab,
            "subTab": sub_tab,
            "by": user["name"],
        }, exclude=user_id)

    elif msg_type == "action":
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

    elif msg_type == "pong":
        pass  # Updates last_activity (done above)


async def broadcast_state_update(action: str, detail: Optional[dict] = None) -> None:
    """Called by other services to broadcast state changes to all users."""
    _shared_state["last_action"] = action
    _shared_state["last_action_at"] = datetime.now(timezone.utc).isoformat()
    await _broadcast({"type": "state_update", "action": action, "detail": detail})


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
