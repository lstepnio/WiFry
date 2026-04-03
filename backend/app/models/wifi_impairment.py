"""Pydantic models for WiFi-layer impairments."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ChannelInterferenceConfig(BaseModel):
    """Simulate co-channel interference by adjusting beacon interval and injecting noise."""

    enabled: bool = False
    beacon_interval_ms: int = Field(100, ge=15, le=2000, description="Beacon interval (default 100ms, higher = more contention)")
    rts_threshold: int = Field(2347, ge=1, le=2347, description="RTS threshold (lower = more overhead, simulates contention)")


class TxPowerConfig(BaseModel):
    """Reduce AP transmit power to simulate edge-of-coverage."""

    enabled: bool = False
    power_dbm: int = Field(20, ge=0, le=30, description="TX power in dBm (default ~20, lower = weaker signal)")


class BandSwitchConfig(BaseModel):
    """Force band/channel change to simulate band steering, roaming, or DFS events."""

    enabled: bool = False
    target_band: str = Field("2.4GHz", description="Target band: '2.4GHz' or '5GHz'")
    target_channel: int = Field(0, ge=0, le=165, description="Target channel (0 = auto)")

    # Periodic band bouncing
    bounce_enabled: bool = Field(False, description="Periodically switch between 2.4GHz and 5GHz")
    bounce_interval_secs: int = Field(60, ge=10, le=3600, description="Seconds between band switches")
    bounce_band_a: str = Field("2.4GHz", description="First band in bounce cycle")
    bounce_channel_a: int = Field(6, description="Channel for band A")
    bounce_band_b: str = Field("5GHz", description="Second band in bounce cycle")
    bounce_channel_b: int = Field(36, description="Channel for band B")

    # Periodic channel hopping (within same band)
    channel_hop_enabled: bool = Field(False, description="Periodically switch channels within the current band")
    channel_hop_interval_secs: int = Field(30, ge=5, le=600, description="Seconds between channel hops")
    channel_hop_list: str = Field("1,6,11", description="Comma-separated list of channels to cycle through")


class DeauthConfig(BaseModel):
    """Simulate authentication failures / WiFi drops."""

    enabled: bool = False
    target_mac: str = Field("", description="Target client MAC (empty = all clients)")
    reason_code: int = Field(3, description="Deauth reason code (3 = station leaving)")


class DhcpDisruptionConfig(BaseModel):
    """Disrupt DHCP to test IP address loss/renewal handling."""

    enabled: bool = False
    mode: str = Field("delay", description="'delay' (slow renewal), 'fail' (NAK), 'change_ip' (new IP on renewal)")
    delay_secs: int = Field(30, ge=1, le=300, description="Delay before DHCP response (delay mode)")


class BroadcastStormConfig(BaseModel):
    """Inject broadcast traffic to consume WiFi airtime."""

    enabled: bool = False
    packets_per_sec: int = Field(100, ge=1, le=10000, description="Broadcast packets per second")
    packet_size_bytes: int = Field(512, ge=64, le=1500, description="Broadcast packet size")


class RateLimitConfig(BaseModel):
    """Force lower WiFi PHY rates to simulate distance from AP."""

    enabled: bool = False
    legacy_rate_mbps: float = Field(54, description="Max legacy rate (1, 2, 5.5, 6, 9, 11, 12, 18, 24, 36, 48, 54)")
    ht_mcs: int = Field(-1, ge=-1, le=31, description="Max HT MCS index (-1 = no limit)")
    vht_mcs: int = Field(-1, ge=-1, le=9, description="Max VHT MCS index (-1 = no limit)")


class PeriodicDisconnectConfig(BaseModel):
    """Schedule periodic WiFi disconnects."""

    enabled: bool = False
    interval_secs: int = Field(300, ge=10, le=7200, description="Time between disconnects")
    disconnect_duration_secs: int = Field(5, ge=1, le=60, description="Duration of each disconnect")
    target_mac: str = Field("", description="Target client MAC (empty = all clients)")


class WifiImpairmentConfig(BaseModel):
    """All WiFi-layer impairment settings."""

    channel_interference: ChannelInterferenceConfig = Field(default_factory=ChannelInterferenceConfig)
    tx_power: TxPowerConfig = Field(default_factory=TxPowerConfig)
    band_switch: BandSwitchConfig = Field(default_factory=BandSwitchConfig)
    deauth: DeauthConfig = Field(default_factory=DeauthConfig)
    dhcp_disruption: DhcpDisruptionConfig = Field(default_factory=DhcpDisruptionConfig)
    broadcast_storm: BroadcastStormConfig = Field(default_factory=BroadcastStormConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    periodic_disconnect: PeriodicDisconnectConfig = Field(default_factory=PeriodicDisconnectConfig)


class WifiImpairmentState(BaseModel):
    """Current state of all WiFi impairments."""

    config: WifiImpairmentConfig = Field(default_factory=WifiImpairmentConfig)
    active_impairments: List[str] = Field(default_factory=list)
    disconnect_count: int = 0
    storm_active: bool = False
