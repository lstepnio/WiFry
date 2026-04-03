"""Pydantic models for saved impairment profiles."""

from typing import List, Optional

from pydantic import BaseModel, Field

from .dns import DnsConfig
from .impairment import ImpairmentConfig
from .wifi_impairment import WifiImpairmentConfig


class Profile(BaseModel):
    """A saved impairment profile combining network + WiFi + DNS impairments."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[\w\s\-\.]+$")
    description: str = ""
    builtin: bool = False
    category: str = Field("network", description="Profile category: network, wifi, dns, combined, scenario")
    tags: List[str] = Field(default_factory=list, description="Searchable tags")
    config: ImpairmentConfig = Field(default_factory=ImpairmentConfig)
    wifi_config: Optional[WifiImpairmentConfig] = Field(None, description="WiFi-layer impairments")
    dns_config: Optional[DnsConfig] = Field(None, description="DNS simulation config")


class ProfileList(BaseModel):
    profiles: List[Profile]


class ApplyProfileRequest(BaseModel):
    interfaces: List[str] = Field(
        default_factory=list,
        description="Interfaces to apply the profile to. Empty = all managed interfaces.",
    )
    apply_wifi: bool = Field(True, description="Also apply WiFi impairments from the profile")
    apply_dns: bool = Field(True, description="Also apply DNS impairments from the profile")
