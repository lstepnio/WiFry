"""Impairments router — CRUD for tc netem rules."""

from fastapi import APIRouter, HTTPException

from ..models.impairment import ImpairmentConfig, InterfaceImpairmentState
from ..services import tc_manager
from ..services.network import get_managed_interfaces

router = APIRouter(prefix="/api/v1/impairments", tags=["impairments"])


@router.get("", response_model=list[InterfaceImpairmentState])
async def get_all_impairments():
    """Get current impairment state for all managed interfaces."""
    interfaces = await get_managed_interfaces()
    return await tc_manager.get_all_states(interfaces)


@router.get("/{interface}", response_model=InterfaceImpairmentState)
async def get_impairment(interface: str):
    """Get impairment state for a specific interface."""
    return await tc_manager.get_state(interface)


@router.put("/{interface}", response_model=InterfaceImpairmentState)
async def apply_impairment(interface: str, config: ImpairmentConfig):
    """Apply impairment settings to an interface."""
    interfaces = await get_managed_interfaces()
    if interface not in interfaces:
        raise HTTPException(404, f"Interface '{interface}' is not managed by WiFry")

    await tc_manager.apply_impairment(interface, config)

    # Log impairment change to active session
    from ..services import session_manager
    sid = session_manager.get_active_session_id()
    if sid:
        session_manager.log_impairment(
            sid,
            network_config=config.model_dump(exclude_none=True),
            label=f"Network impairment on {interface}",
        )
        await session_manager.auto_add_artifact(
            session_manager.ArtifactType.IMPAIRMENT_LOG,
            name=f"Impairment applied: {interface}",
            data=config.model_dump(exclude_none=True),
            tags=["impairment", "network"],
        )

    return await tc_manager.get_state(interface)


@router.put("/{interface}/client/{client_ip}")
async def apply_per_client_impairment(interface: str, client_ip: str, config: ImpairmentConfig):
    """Apply impairment to a specific client IP."""
    await tc_manager.apply_per_client(interface, client_ip, config)
    return {"status": "ok", "interface": interface, "client_ip": client_ip}


@router.delete("/{interface}/client/{client_ip}")
async def clear_per_client_impairment(interface: str, client_ip: str):
    """Clear impairment for a specific client IP."""
    await tc_manager.clear_per_client(interface, client_ip)
    return {"status": "ok", "interface": interface, "client_ip": client_ip}


@router.delete("/{interface}")
async def clear_impairment(interface: str):
    """Clear all impairments on an interface."""
    await tc_manager.clear_impairment(interface)
    return {"status": "ok", "interface": interface}


@router.delete("")
async def clear_all_impairments():
    """Clear all impairments on all managed interfaces."""
    interfaces = await get_managed_interfaces()
    await tc_manager.clear_all(interfaces)
    return {"status": "ok", "interfaces": interfaces}
