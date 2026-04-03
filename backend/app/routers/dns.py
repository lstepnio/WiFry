"""DNS simulation router — CoreDNS configuration, overrides, impairments, query log."""

from typing import List

from fastapi import APIRouter, HTTPException

from ..models.dns import DnsConfig, DnsOverride, DnsQueryLogEntry, DnsStatus
from ..services import dns_manager

router = APIRouter(prefix="/api/v1/dns", tags=["dns"])


@router.get("/config", response_model=DnsConfig)
async def get_config():
    """Get current DNS simulation configuration."""
    return dns_manager.get_config()


@router.put("/config", response_model=DnsStatus)
async def apply_config(config: DnsConfig):
    """Apply DNS configuration. Generates Corefile, restarts CoreDNS, updates dnsmasq."""
    try:
        return await dns_manager.apply_config(config)
    except Exception as e:
        raise HTTPException(500, f"Failed to apply DNS config: {e}")


@router.get("/status", response_model=DnsStatus)
async def get_status():
    """Get DNS simulation status."""
    return dns_manager.get_status()


@router.post("/enable", response_model=DnsStatus)
async def enable():
    """Enable DNS simulation with current config."""
    return await dns_manager.enable()


@router.post("/disable", response_model=DnsStatus)
async def disable():
    """Disable DNS simulation, revert to direct upstream."""
    return await dns_manager.disable()


# --- Overrides ---

@router.get("/overrides", response_model=List[DnsOverride])
async def list_overrides():
    """List DNS record overrides."""
    return dns_manager.get_overrides()


@router.post("/overrides", response_model=List[DnsOverride])
async def add_override(override: DnsOverride):
    """Add or update a DNS record override."""
    return dns_manager.add_override(override)


@router.delete("/overrides/{domain}")
async def remove_override(domain: str):
    """Remove all DNS overrides for a domain."""
    overrides = dns_manager.remove_override(domain)
    return {"status": "ok", "remaining": len(overrides)}


# --- Query log ---

@router.get("/query-log", response_model=List[DnsQueryLogEntry])
async def get_query_log(limit: int = 100):
    """Get recent DNS queries."""
    return dns_manager.get_query_log(limit)
