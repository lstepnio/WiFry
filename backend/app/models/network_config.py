"""Pydantic models for WiFi AP and Ethernet network configuration.

Design principles:
  - Always boot with safe defaults (can't lock yourself out)
  - Fallback IP always reachable on Ethernet regardless of config
  - Saved config profiles for different environments
  - First-boot encourages changing from defaults
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# --- Safe defaults (always boot into these) ---

DEFAULTS = {
    "ap_ssid": "WiFry",
    "ap_password": "wifry1234",
    "ap_channel": 6,
    "ap_band": "2.4GHz",
    "ap_ip": "192.168.4.1",
    "ap_netmask": "255.255.255.0",
    "dhcp_start": "192.168.4.10",
    "dhcp_end": "192.168.4.200",
    "eth_mode": "dhcp",
    "eth_static_ip": "",
    "eth_static_netmask": "255.255.255.0",
    "eth_static_gateway": "",
    "eth_static_dns": "8.8.8.8",
    "fallback_ip": "169.254.42.1",  # Link-local fallback — always reachable
    "fallback_netmask": "255.255.0.0",
    "country_code": "US",
}


class WifiApConfig(BaseModel):
    """WiFi Access Point configuration."""

    ssid: str = Field(DEFAULTS["ap_ssid"], min_length=1, max_length=32)
    password: str = Field(DEFAULTS["ap_password"], min_length=8, max_length=63)
    channel: int = Field(DEFAULTS["ap_channel"], ge=0, le=165)
    band: str = Field(DEFAULTS["ap_band"], description="'2.4GHz' or '5GHz'")
    channel_width: int = Field(20, description="Channel width in MHz: 20, 40, or 80")
    hidden: bool = Field(False, description="Hide SSID from broadcast")
    ip: str = Field(DEFAULTS["ap_ip"])
    netmask: str = Field(DEFAULTS["ap_netmask"])
    dhcp_start: str = Field(DEFAULTS["dhcp_start"])
    dhcp_end: str = Field(DEFAULTS["dhcp_end"])
    country_code: str = Field(DEFAULTS["country_code"])


class EthernetConfig(BaseModel):
    """Ethernet port configuration."""

    mode: str = Field("dhcp", description="'dhcp' or 'static'")
    static_ip: str = Field("")
    static_netmask: str = Field("255.255.255.0")
    static_gateway: str = Field("")
    static_dns: str = Field("8.8.8.8")


class FallbackConfig(BaseModel):
    """Fallback IP that's always reachable on eth0 regardless of other config.
    This prevents lockout — you can always reach the app at this address.
    """

    enabled: bool = Field(True, description="Always keep fallback IP active")
    ip: str = Field(DEFAULTS["fallback_ip"])
    netmask: str = Field(DEFAULTS["fallback_netmask"])


class FullNetworkConfig(BaseModel):
    """Complete network configuration."""

    wifi_ap: WifiApConfig = Field(default_factory=WifiApConfig)
    ethernet: EthernetConfig = Field(default_factory=EthernetConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    first_boot: bool = Field(True, description="True until user saves custom config")


class NetworkConfigProfile(BaseModel):
    """A saved network configuration profile for different environments."""

    id: str = ""
    name: str = Field(..., min_length=1)
    description: str = ""
    config: FullNetworkConfig
    is_boot_profile: bool = Field(False, description="If True, loaded on boot instead of defaults. Use with caution.")
