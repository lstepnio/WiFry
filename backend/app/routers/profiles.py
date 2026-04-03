"""Profiles router — save/load impairment profiles as JSON files."""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..models.profile import ApplyProfileRequest, Profile, ProfileList
from ..services import tc_manager, wifi_impairment
from ..services.network import get_managed_interfaces

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])
logger = logging.getLogger(__name__)


def _profile_path(name: str) -> Path:
    return settings.profiles_dir / f"{name}.json"


def _load_profile(name: str) -> Profile:
    path = _profile_path(name)
    if not path.exists():
        raise HTTPException(404, f"Profile '{name}' not found")
    data = json.loads(path.read_text())
    return Profile(**data)


def _save_profile(profile: Profile) -> None:
    settings.profiles_dir.mkdir(parents=True, exist_ok=True)
    path = _profile_path(profile.name)
    path.write_text(profile.model_dump_json(indent=2))


@router.get("", response_model=ProfileList)
async def list_profiles(category: Optional[str] = None, tag: Optional[str] = None):
    """List all saved profiles, optionally filtered by category or tag."""
    profiles = []
    if settings.profiles_dir.exists():
        for f in sorted(settings.profiles_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                p = Profile(**data)
                if category and p.category != category:
                    continue
                if tag and tag not in p.tags:
                    continue
                profiles.append(p)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to load profile %s: %s", f.name, e)
    return ProfileList(profiles=profiles)


@router.get("/{name}", response_model=Profile)
async def get_profile(name: str):
    """Get a single profile by name."""
    return _load_profile(name)


@router.post("", response_model=Profile, status_code=201)
async def create_profile(profile: Profile):
    """Create a new profile."""
    path = _profile_path(profile.name)
    if path.exists():
        raise HTTPException(409, f"Profile '{profile.name}' already exists")
    _save_profile(profile)
    return profile


@router.put("/{name}", response_model=Profile)
async def update_profile(name: str, profile: Profile):
    """Update an existing profile."""
    existing = _load_profile(name)
    if existing.builtin:
        raise HTTPException(403, "Cannot modify built-in profiles")

    if profile.name != name:
        _profile_path(name).unlink(missing_ok=True)

    _save_profile(profile)
    return profile


@router.delete("/{name}")
async def delete_profile(name: str):
    """Delete a profile."""
    profile = _load_profile(name)
    if profile.builtin:
        raise HTTPException(403, "Cannot delete built-in profiles")
    _profile_path(name).unlink()
    return {"status": "ok", "name": name}


@router.post("/{name}/apply")
async def apply_profile(name: str, request: ApplyProfileRequest):
    """Apply a profile (network + WiFi + DNS impairments) to interface(s)."""
    profile = _load_profile(name)

    interfaces = request.interfaces
    if not interfaces:
        interfaces = await get_managed_interfaces()

    # Apply network impairments (tc netem)
    if not profile.config.is_empty():
        for iface in interfaces:
            await tc_manager.apply_impairment(iface, profile.config)

    # Apply WiFi impairments
    if request.apply_wifi and profile.wifi_config:
        await wifi_impairment.apply(profile.wifi_config)

    # Apply DNS impairments
    if request.apply_dns and profile.dns_config:
        from ..services import dns_manager
        await dns_manager.apply_config(profile.dns_config)

    applied = []
    if not profile.config.is_empty():
        applied.append("network")
    if profile.wifi_config:
        applied.append("wifi")
    if profile.dns_config and profile.dns_config.enabled:
        applied.append("dns")

    # Log to active session
    from ..services import session_manager
    sid = session_manager.get_active_session_id()
    if sid:
        session_manager.log_impairment(
            sid,
            profile_name=name,
            network_config=profile.config.model_dump(exclude_none=True) if not profile.config.is_empty() else None,
            wifi_config=profile.wifi_config.model_dump(exclude_none=True) if profile.wifi_config else None,
            label=f"Profile applied: {name}",
        )

    return {
        "status": "ok",
        "profile": name,
        "interfaces": interfaces,
        "applied": applied,
    }
