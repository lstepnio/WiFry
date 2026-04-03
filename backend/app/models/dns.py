"""Pydantic models for DNS simulation via CoreDNS."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# Well-known upstream providers
UPSTREAM_PROVIDERS = {
    "dhcp": {"plain": []},
    "cloudflare": {"plain": ["1.1.1.1", "1.0.0.1"], "doh": ["https://cloudflare-dns.com/dns-query"], "dot": ["tls://1.1.1.1"]},
    "google": {"plain": ["8.8.8.8", "8.8.4.4"], "doh": ["https://dns.google/dns-query"], "dot": ["tls://8.8.8.8"]},
    "quad9": {"plain": ["9.9.9.9", "149.112.112.112"], "doh": ["https://dns.quad9.net/dns-query"], "dot": ["tls://9.9.9.9"]},
    "opendns": {"plain": ["208.67.222.222", "208.67.220.220"], "doh": ["https://doh.opendns.com/dns-query"]},
}


class DnsResolver(BaseModel):
    """A single upstream DNS resolver with optional per-resolver failure simulation."""

    address: str = Field(..., description="Server address (IP, tls://IP, or https://URL)")
    label: str = Field("", description="Human label (e.g. 'Primary', 'Secondary')")
    healthy: bool = Field(True, description="If False, CoreDNS won't forward to this resolver (simulates failure)")
    delay_ms: int = Field(0, ge=0, le=10000, description="Per-resolver added latency")


class DnsUpstreamConfig(BaseModel):
    """Upstream DNS resolver configuration.

    Supports both simple provider-based config (provider + protocol)
    and advanced multi-resolver config (resolvers list).
    """

    provider: str = Field("cloudflare", description="dhcp, cloudflare, google, quad9, opendns, custom, or multi")
    custom_servers: List[str] = Field(default_factory=list, description="Custom DNS servers (for provider='custom')")
    protocol: str = Field("plain", description="plain, doh, dot")

    # Advanced: explicit resolver list with per-resolver health/failure
    resolvers: List[DnsResolver] = Field(
        default_factory=list,
        description="Explicit resolver list (for provider='multi'). Each resolver can be independently failed.",
    )


class DnsImpairments(BaseModel):
    """DNS-specific impairments to simulate adverse conditions."""

    delay_ms: int = Field(0, ge=0, le=10000, description="Add latency to DNS responses (ms)")
    failure_rate_pct: float = Field(0, ge=0, le=100, description="Drop this % of queries (no response)")
    nxdomain_domains: List[str] = Field(default_factory=list, description="Domains/patterns to force NXDOMAIN")
    servfail_rate_pct: float = Field(0, ge=0, le=100, description="Return SERVFAIL for this % of queries")
    ttl_override: int = Field(0, ge=0, le=86400, description="Force this TTL on all responses (0 = don't override)")


class DnsOverride(BaseModel):
    """A custom DNS record override."""

    domain: str = Field(..., min_length=1, description="Domain name (e.g. 'cdn.example.com')")
    record_type: str = Field("A", description="A, AAAA, or CNAME")
    value: str = Field(..., min_length=1, description="IP address or target domain")


class DnsConfig(BaseModel):
    """Complete DNS simulation configuration."""

    enabled: bool = False
    listen_port: int = Field(5053, ge=1024, le=65535, description="CoreDNS listen port (internal)")
    upstream: DnsUpstreamConfig = Field(default_factory=DnsUpstreamConfig)
    impairments: DnsImpairments = Field(default_factory=DnsImpairments)
    overrides: List[DnsOverride] = Field(default_factory=list)
    log_queries: bool = Field(True, description="Log DNS queries for the query log viewer")


class DnsStatus(BaseModel):
    """Current DNS simulation status."""

    enabled: bool = False
    running: bool = False
    listen_port: int = 5053
    upstream_provider: str = ""
    upstream_protocol: str = ""
    resolver_count: int = 0
    healthy_resolvers: int = 0
    override_count: int = 0
    impairments_active: List[str] = Field(default_factory=list)
    query_count: int = 0


class DnsQueryLogEntry(BaseModel):
    """A single DNS query log entry."""

    timestamp: str = ""
    client_ip: str = ""
    domain: str = ""
    query_type: str = ""
    response_code: str = ""
    latency_ms: float = 0
    resolver_used: str = ""
