"""Collaboration mode for WiFry.

Modes:
  - co-pilot: Anyone can drive — all users see the same state, anyone can interact
  - download: Download-only — live access is limited to file sharing

Only the selected mode survives a backend restart. Live users, WebSocket
connections, and shared navigation state are intentionally ephemeral.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import WebSocket

from ..models.collaboration import (
    CollaborationMode,
    CollaborationPersistentState,
    CollaborationSharedState,
    CollaborationStatus,
    CollaborationUser,
)
from . import audit_log
from . import runtime_state

logger = logging.getLogger(__name__)

_mode: CollaborationMode = CollaborationMode.CO_PILOT
_mode_loaded = False
_connected_users: Dict[str, CollaborationUser] = {}
_websockets: Dict[str, WebSocket] = {}
_shared_state = CollaborationSharedState().model_dump(mode="json")
_heartbeat_task: Optional[asyncio.Task] = None
HEARTBEAT_INTERVAL = 15
INACTIVITY_TIMEOUT = 60
_COLLAB_STATE_KEY = "collaboration"


def _load_mode() -> None:
    global _mode, _mode_loaded

    if _mode_loaded:
        return

    _mode_loaded = True
    state = runtime_state.load_model(_COLLAB_STATE_KEY, CollaborationPersistentState)
    if state:
        _mode = state.mode


def _save_mode(mode: CollaborationMode) -> None:
    global _mode, _mode_loaded
    _mode = mode
    _mode_loaded = True
    runtime_state.save_model(_COLLAB_STATE_KEY, CollaborationPersistentState(mode=mode))


def get_mode() -> str:
    _load_mode()
    return _mode.value


def set_mode(mode: str) -> dict:
    _load_mode()
    try:
        resolved_mode = CollaborationMode(mode)
    except ValueError as exc:
        raise ValueError(f"Invalid mode: {mode}. Use: co-pilot, download") from exc

    _save_mode(resolved_mode)
    logger.info(
        "collaboration.mode_set",
        extra={"event": "collaboration_mode", "mode": resolved_mode.value},
    )
    audit_log.record_event(
        "sharing.collaboration.mode",
        resource_type="collaboration",
        details={"mode": resolved_mode.value},
    )
    asyncio.create_task(_broadcast({"type": "mode_change", "mode": resolved_mode.value}))
    return get_status()


def get_status() -> dict:
    _load_mode()
    return CollaborationStatus(
        mode=_mode,
        connected_users=list(_connected_users.values()),
        user_count=len(_connected_users),
        shared_state=_shared_state,
    ).model_dump(mode="json")


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
                last = datetime.fromisoformat(user.last_activity)
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
    _load_mode()
    _ensure_heartbeat()
    user_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()

    display_name = name or f"User-{user_id[:4]}"
    if ip:
        display_name = f"{display_name} ({ip})"

    user = CollaborationUser(
        id=user_id,
        name=display_name,
        ip=ip,
        connected_at=now,
        last_activity=now,
    )

    _connected_users[user_id] = user
    _websockets[user_id] = ws

    logger.info(
        "collaboration.user_connected",
        extra={"event": "collaboration_user", "user_id": user_id, "user_name": display_name, "client_ip": ip},
    )

    await _broadcast({
        "type": "user_joined",
        "user": user.model_dump(mode="json"),
        "user_count": len(_connected_users),
    }, exclude=user_id)

    await _send(user_id, {
        "type": "init",
        "mode": _mode.value,
        "users": [u.model_dump(mode="json") for u in _connected_users.values()],
        "state": _shared_state,
    })

    return user_id


async def disconnect_user(user_id: str) -> None:
    """Remove a disconnected user."""
    user = _connected_users.pop(user_id, None)
    _websockets.pop(user_id, None)

    if user:
        logger.info(
            "collaboration.user_disconnected",
            extra={"event": "collaboration_user", "user_id": user_id, "user_name": user.name},
        )
        await _broadcast({
            "type": "user_left",
            "user_id": user_id,
            "user_name": user.name,
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
    logger.info("collaboration.all_users_disconnected", extra={"event": "collaboration_disconnect_all"})


# --- Message handling ---

async def handle_message(user_id: str, data: dict) -> None:
    """Process a message from a connected user."""
    msg_type = data.get("type", "")
    user = _connected_users.get(user_id)

    if not user:
        return

    user.last_activity = datetime.now(timezone.utc).isoformat()

    if msg_type == "navigate":
        # Forward full navigation state to all other users
        nav_state = data.get("state", {})
        _shared_state["nav"] = nav_state
        _shared_state["last_action"] = f"Navigated to {nav_state.get('tab', '?')}"
        _shared_state["last_action_by"] = user.name
        _shared_state["last_action_at"] = user.last_activity

        await _broadcast({
            "type": "navigate",
            "state": nav_state,
            "by": user.name,
        }, exclude=user_id)

    elif msg_type == "action":
        action = data.get("action", "")
        _shared_state["last_action"] = action
        _shared_state["last_action_by"] = user.name
        _shared_state["last_action_at"] = user.last_activity

        await _broadcast({
            "type": "action",
            "action": action,
            "detail": data.get("detail"),
            "by": user.name,
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
