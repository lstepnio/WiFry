"""STB_AUTOMATION — Navigation model persistence and pathfinding.

The navigation model is a directed graph of ``ScreenNode`` objects
connected by ``TransitionEdge`` objects.  It is persisted to disk as
JSON and can be reloaded across restarts.

Pathfinding uses BFS on the edge list to find the shortest action
sequence between any two nodes.
"""

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ...services import storage
from .models import NavigationModel, ScreenNode, TransitionEdge

logger = logging.getLogger("wifry.stb_automation.nav_model")

# In-memory model — one per device
_models: Dict[str, NavigationModel] = {}


def _store_dir() -> Path:
    return storage.ensure_data_path("stb_nav_models")


def _model_path(device_id: str) -> Path:
    safe_id = device_id.replace(":", "_").replace("/", "_")
    return _store_dir() / f"{safe_id}.json"


# ── CRUD ────────────────────────────────────────────────────────────


def get_model(device_id: str) -> Optional[NavigationModel]:
    """Get the navigation model for a device, loading from disk if needed."""
    if device_id in _models:
        return _models[device_id]
    return _load(device_id)


def get_or_create_model(device_id: str, device_model: str = "") -> NavigationModel:
    """Get existing model or create a new empty one."""
    model = get_model(device_id)
    if model is not None:
        return model

    now = datetime.now(timezone.utc).isoformat()
    model = NavigationModel(
        device_id=device_id,
        device_model=device_model,
        created_at=now,
        updated_at=now,
    )
    _models[device_id] = model
    return model


def save_model(device_id: str) -> None:
    """Persist the model to disk."""
    model = _models.get(device_id)
    if model is None:
        return

    model.updated_at = datetime.now(timezone.utc).isoformat()
    path = _model_path(device_id)
    path.write_text(json.dumps(model.model_dump(), indent=2))
    logger.debug("[STB_AUTOMATION] Model saved: %s (%d nodes, %d edges)",
                 device_id, len(model.nodes), len(model.edges))


def delete_model(device_id: str) -> bool:
    """Delete the model from memory and disk."""
    _models.pop(device_id, None)
    path = _model_path(device_id)
    if path.exists():
        path.unlink()
        logger.info("[STB_AUTOMATION] Model deleted: %s", device_id)
        return True
    return False


def _load(device_id: str) -> Optional[NavigationModel]:
    """Load a model from disk."""
    path = _model_path(device_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        model = NavigationModel(**data)
        _models[device_id] = model
        logger.info("[STB_AUTOMATION] Model loaded: %s (%d nodes, %d edges)",
                    device_id, len(model.nodes), len(model.edges))
        return model
    except (json.JSONDecodeError, Exception) as e:
        logger.error("[STB_AUTOMATION] Failed to load model %s: %s", device_id, e)
        return None


# ── Graph mutation ──────────────────────────────────────────────────


def upsert_node(model: NavigationModel, node: ScreenNode) -> None:
    """Add or update a node in the model."""
    existing = model.nodes.get(node.id)
    if existing:
        existing.visit_count += 1
        existing.last_visited = node.last_visited or datetime.now(timezone.utc).isoformat()
        # Update elements if we have fresh data
        if node.elements:
            existing.elements = node.elements
        if node.vision_analysis:
            existing.vision_analysis = node.vision_analysis
    else:
        node.visit_count = 1
        node.last_visited = node.last_visited or datetime.now(timezone.utc).isoformat()
        model.nodes[node.id] = node


def record_transition(
    model: NavigationModel,
    from_id: str,
    to_id: str,
    action: str,
    transition_ms: float,
    settle_method: str,
) -> None:
    """Record a transition between two nodes."""
    no_effect = from_id == to_id

    # Find existing edge
    for edge in model.edges:
        if edge.from_node == from_id and edge.to_node == to_id and edge.action == action:
            if no_effect:
                edge.no_effect_count += 1
            else:
                edge.success_count += 1
                # Running average
                total = edge.success_count
                edge.avg_transition_ms = (
                    (edge.avg_transition_ms * (total - 1) + transition_ms) / total
                )
            edge.settle_method = settle_method
            return

    # New edge
    model.edges.append(
        TransitionEdge(
            from_node=from_id,
            to_node=to_id,
            action=action,
            success_count=0 if no_effect else 1,
            no_effect_count=1 if no_effect else 0,
            avg_transition_ms=transition_ms if not no_effect else 0.0,
            settle_method=settle_method,
        )
    )


# ── Pathfinding ─────────────────────────────────────────────────────


def find_path(model: NavigationModel, from_id: str, to_id: str) -> Optional[List[str]]:
    """Find the shortest action sequence from one node to another.

    Returns a list of action names (keycodes), or None if no path
    exists.  Uses BFS on successful edges (ignoring no-effect edges).
    """
    if from_id == to_id:
        return []

    if from_id not in model.nodes or to_id not in model.nodes:
        return None

    # Build adjacency list from edges with at least one success
    adj: Dict[str, List[tuple[str, str]]] = {}  # node_id -> [(target_id, action)]
    for edge in model.edges:
        if edge.success_count > 0:
            adj.setdefault(edge.from_node, []).append((edge.to_node, edge.action))

    # BFS
    queue: deque[tuple[str, List[str]]] = deque([(from_id, [])])
    visited = {from_id}

    while queue:
        current, actions = queue.popleft()
        for target, action in adj.get(current, []):
            if target == to_id:
                return actions + [action]
            if target not in visited:
                visited.add(target)
                queue.append((target, actions + [action]))

    return None  # No path found


def get_node(model: NavigationModel, node_id: str) -> Optional[ScreenNode]:
    """Get a specific node by ID."""
    return model.nodes.get(node_id)
