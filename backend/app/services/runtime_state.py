"""Small JSON-backed repository for durable runtime state.

This module is intentionally narrow: it persists small pieces of appliance
state that should survive a backend restart, without pretending that live
process handles or WebSocket connections are durable.
"""

import logging
from pathlib import Path
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from . import storage

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _state_dir() -> Path:
    return storage.ensure_data_path("runtime_state")


def _state_path(name: str) -> Path:
    return _state_dir() / f"{name}.json"


def load_model(name: str, model_type: Type[ModelT]) -> Optional[ModelT]:
    """Load a typed runtime-state record from disk."""
    path = _state_path(name)
    if not path.exists():
        return None

    try:
        return model_type.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        logger.warning("Failed to load runtime state '%s': %s", name, exc)
        return None


def save_model(name: str, model: BaseModel) -> None:
    """Persist a typed runtime-state record to disk."""
    path = _state_path(name)
    path.write_text(model.model_dump_json(indent=2))


def clear(name: str) -> None:
    """Remove a persisted runtime-state record."""
    _state_path(name).unlink(missing_ok=True)
