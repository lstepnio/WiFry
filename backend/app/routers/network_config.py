"""Network configuration router — WiFi AP, Ethernet, fallback, profiles."""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models.network_config import FullNetworkConfig, NetworkConfigProfile
from ..services import network_config

router = APIRouter(prefix="/api/v1/network-config", tags=["network-config"])


@router.get("/current", response_model=FullNetworkConfig)
async def get_current():
    """Get current network configuration."""
    return network_config.get_current_config()


@router.get("/first-boot")
async def check_first_boot():
    """Check if this is first boot (no custom config saved)."""
    return {"first_boot": network_config.is_first_boot()}


@router.put("/apply", response_model=FullNetworkConfig)
async def apply_config(config: FullNetworkConfig):
    """Apply a new network configuration. Marks first_boot=False."""
    return await network_config.apply_config(config)


@router.post("/reset-defaults", response_model=FullNetworkConfig)
async def reset_defaults():
    """Reset to safe defaults."""
    return await network_config.apply_defaults()


# --- Profiles ---

@router.get("/profiles", response_model=List[NetworkConfigProfile])
async def list_profiles():
    """List saved network config profiles."""
    return network_config.list_profiles()


class SaveProfileRequest(BaseModel):
    name: str
    description: str = ""


@router.post("/profiles", response_model=NetworkConfigProfile, status_code=201)
async def save_profile(req: SaveProfileRequest):
    """Save current config as a named profile."""
    return network_config.save_profile(req.name, req.description)


@router.post("/profiles/{profile_id}/apply", response_model=FullNetworkConfig)
async def apply_profile(profile_id: str):
    """Load and apply a saved profile."""
    try:
        return await network_config.apply_profile(profile_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/profiles/{profile_id}/set-boot")
async def set_boot_profile(profile_id: str):
    """Set a profile to load on boot. Fallback IP always remains reachable."""
    try:
        profile = network_config.set_boot_profile(profile_id)
        return {"status": "ok", "boot_profile": profile.name,
                "warning": "If this profile has incorrect WiFi settings, use the fallback IP to access the app."}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/profiles/clear-boot")
async def clear_boot_profile():
    """Clear boot profile — use safe defaults on next boot."""
    network_config.clear_boot_profile()
    return {"status": "ok", "message": "Will use safe defaults on next boot."}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a saved profile."""
    network_config.delete_profile(profile_id)
    return {"status": "ok"}
