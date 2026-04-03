"""Pydantic models for Teleport (VPN geo-shifting)."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TeleportProfile(BaseModel):
    """A VPN connection profile for teleporting to a specific network/market."""

    id: str = ""
    name: str = Field(..., min_length=1, description="e.g. 'US East - NYC', 'UK - London', 'Japan - Tokyo'")
    description: str = ""
    market: str = Field("", description="Market identifier (e.g. 'us-east', 'uk', 'jp')")
    region: str = Field("", description="Geographic region")
    vpn_type: str = Field("wireguard", description="VPN technology: wireguard, openvpn, ipsec, custom")

    # VPN config (provided by network/secops team)
    wireguard_config: str = Field("", description="WireGuard .conf contents")
    openvpn_config: str = Field("", description="OpenVPN .ovpn contents")
    ipsec_config: str = Field("", description="strongSwan/IPsec config contents")
    custom_connect_cmd: str = Field("", description="Custom shell command to establish VPN (for 'custom' vpn_type)")
    custom_disconnect_cmd: str = Field("", description="Custom shell command to tear down VPN")

    # Metadata
    tags: List[str] = Field(default_factory=list)
    expected_ip: str = Field("", description="Expected public IP after connection (for verification)")
    expected_country: str = Field("", description="Expected country code (for verification)")


class TeleportStatus(BaseModel):
    """Current teleport connection state."""

    connected: bool = False
    active_profile: Optional[str] = None
    active_profile_name: str = ""
    market: str = ""
    region: str = ""
    vpn_type: str = ""
    interface: str = ""
    public_ip: str = ""
    connected_at: Optional[str] = None
    handshake_at: Optional[str] = None
    transfer_rx_bytes: int = 0
    transfer_tx_bytes: int = 0


class CreateTeleportProfileRequest(BaseModel):
    name: str
    description: str = ""
    market: str = ""
    region: str = ""
    vpn_type: str = "wireguard"
    config_contents: str = Field(..., description="WireGuard .conf or OpenVPN .ovpn file contents")
    tags: List[str] = Field(default_factory=list)
    expected_ip: str = ""
    expected_country: str = ""
