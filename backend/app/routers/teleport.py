"""Teleport (VPN) router — geo-shift STB traffic through remote networks."""

from typing import List

from fastapi import APIRouter, HTTPException

from ..models.teleport import CreateTeleportProfileRequest, TeleportProfile, TeleportStatus
from ..services import teleport

router = APIRouter(prefix="/api/v1/teleport", tags=["teleport"])


@router.get("/status", response_model=TeleportStatus)
async def get_status():
    """Get current teleport connection status."""
    return teleport.get_status()


@router.get("/profiles", response_model=List[TeleportProfile])
async def list_profiles():
    """List available teleport profiles."""
    return teleport.list_profiles()


@router.post("/profiles", response_model=TeleportProfile, status_code=201)
async def create_profile(req: CreateTeleportProfileRequest):
    """Create a teleport profile from VPN config (provided by secops)."""
    return teleport.create_profile(
        name=req.name,
        config_contents=req.config_contents,
        vpn_type=req.vpn_type,
        description=req.description,
        market=req.market,
        region=req.region,
        tags=req.tags,
        expected_ip=req.expected_ip,
        expected_country=req.expected_country,
    )


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a teleport profile."""
    teleport.delete_profile(profile_id)
    return {"status": "ok"}


@router.post("/connect/{profile_id}", response_model=TeleportStatus)
async def connect(profile_id: str):
    """Activate VPN to teleport STB traffic through a remote network."""
    try:
        return await teleport.connect(profile_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/disconnect", response_model=TeleportStatus)
async def disconnect():
    """Deactivate VPN and return to normal routing."""
    return await teleport.disconnect()


@router.get("/verify")
async def verify():
    """Verify the VPN connection by checking public IP and geo."""
    return await teleport.verify_connection()
