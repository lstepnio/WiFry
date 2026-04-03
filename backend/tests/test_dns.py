"""Tests for DNS simulation."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import dns_manager
from app.models.dns import DnsConfig, DnsOverride, DnsUpstreamConfig, DnsImpairments


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# --- API tests ---

async def test_get_dns_config(client: AsyncClient):
    resp = await client.get("/api/v1/dns/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "upstream" in data
    assert "impairments" in data


async def test_get_dns_status(client: AsyncClient):
    resp = await client.get("/api/v1/dns/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "running" in data
    assert "upstream_provider" in data


async def test_apply_dns_config(client: AsyncClient):
    resp = await client.put("/api/v1/dns/config", json={
        "enabled": True,
        "listen_port": 5053,
        "log_queries": True,
        "upstream": {"provider": "google", "custom_servers": [], "protocol": "doh"},
        "impairments": {"delay_ms": 100, "failure_rate_pct": 5, "nxdomain_domains": ["*.bad.com"], "servfail_rate_pct": 2, "ttl_override": 10},
        "overrides": [{"domain": "cdn.example.com", "record_type": "A", "value": "192.168.4.1"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"]
    assert data["upstream_provider"] == "google"


async def test_enable_disable_dns(client: AsyncClient):
    resp = await client.post("/api/v1/dns/enable")
    assert resp.status_code == 200
    assert resp.json()["enabled"]

    resp = await client.post("/api/v1/dns/disable")
    assert resp.status_code == 200
    assert not resp.json()["enabled"]


async def test_dns_overrides_crud(client: AsyncClient):
    # Add
    resp = await client.post("/api/v1/dns/overrides", json={
        "domain": "test.example.com", "record_type": "A", "value": "10.0.0.1"
    })
    assert resp.status_code == 200
    overrides = resp.json()
    assert any(o["domain"] == "test.example.com" for o in overrides)

    # List
    resp = await client.get("/api/v1/dns/overrides")
    assert resp.status_code == 200

    # Remove
    resp = await client.delete("/api/v1/dns/overrides/test.example.com")
    assert resp.status_code == 200


async def test_dns_query_log(client: AsyncClient):
    resp = await client.get("/api/v1/dns/query-log?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# --- Service-level tests ---

def test_corefile_generation():
    """Test that Corefile is generated correctly from config."""
    config = DnsConfig(
        enabled=True,
        listen_port=5053,
        upstream=DnsUpstreamConfig(provider="cloudflare", protocol="plain"),
        impairments=DnsImpairments(
            delay_ms=100,
            failure_rate_pct=5,
            nxdomain_domains=["*.blocked.com"],
            servfail_rate_pct=10,
            ttl_override=30,
        ),
        overrides=[DnsOverride(domain="cdn.test.com", record_type="A", value="192.168.1.1")],
        log_queries=True,
    )

    dns_manager._generate_corefile(config)
    dns_manager._generate_hosts_file(config.overrides)

    corefile = dns_manager.COREFILE_PATH.read_text()
    assert ".:5053" in corefile
    assert "log" in corefile
    assert "hosts" in corefile
    assert "template" in corefile
    assert "NXDOMAIN" in corefile
    assert "erratic" in corefile
    assert "cache 30" in corefile
    assert "forward" in corefile
    assert "1.1.1.1" in corefile

    hosts = dns_manager.HOSTS_PATH.read_text()
    assert "192.168.1.1 cdn.test.com" in hosts


def test_corefile_dot_protocol():
    """Test Corefile generation with DNS-over-TLS."""
    config = DnsConfig(
        enabled=True,
        upstream=DnsUpstreamConfig(provider="cloudflare", protocol="dot"),
    )
    dns_manager._generate_corefile(config)
    corefile = dns_manager.COREFILE_PATH.read_text()
    assert "tls://" in corefile
    assert "tls_servername cloudflare-dns.com" in corefile


def test_corefile_doh_protocol():
    """Test Corefile generation with DNS-over-HTTPS."""
    config = DnsConfig(
        enabled=True,
        upstream=DnsUpstreamConfig(provider="google", protocol="doh"),
    )
    dns_manager._generate_corefile(config)
    corefile = dns_manager.COREFILE_PATH.read_text()
    assert "dns.google" in corefile


def test_resolve_upstream_custom():
    config = DnsConfig(
        upstream=DnsUpstreamConfig(provider="custom", custom_servers=["10.0.0.1", "10.0.0.2"], protocol="plain"),
    )
    servers = dns_manager._resolve_upstream(config)
    assert servers == ["10.0.0.1", "10.0.0.2"]


def test_resolve_upstream_custom_dot():
    config = DnsConfig(
        upstream=DnsUpstreamConfig(provider="custom", custom_servers=["10.0.0.1"], protocol="dot"),
    )
    servers = dns_manager._resolve_upstream(config)
    assert servers == ["tls://10.0.0.1"]


def test_get_active_impairments():
    config = DnsConfig(
        impairments=DnsImpairments(delay_ms=200, failure_rate_pct=5, servfail_rate_pct=3, ttl_override=10, nxdomain_domains=["a.com"]),
    )
    active = dns_manager._get_active_impairments(config)
    assert "delay:200ms" in active
    assert "drop:5.0%" in active
    assert "servfail:3.0%" in active
    assert "ttl:10s" in active
    assert "nxdomain:1 patterns" in active


def test_get_active_impairments_none():
    config = DnsConfig()
    active = dns_manager._get_active_impairments(config)
    assert active == []


def test_parse_log_line():
    line = '[INFO] 192.168.4.10:12345 - 12345 "A IN cdn.example.com. udp 128 false 4096"'
    entry = dns_manager._parse_log_line(line)
    assert entry is not None
    assert entry.client_ip == "192.168.4.10"
    assert entry.query_type == "A"
    assert entry.domain == "cdn.example.com"


def test_parse_log_line_invalid():
    entry = dns_manager._parse_log_line("some random log output")
    assert entry is None


def test_mock_query_log():
    log = dns_manager._mock_query_log()
    assert len(log) == 5
    assert log[0].domain == "cdn.example.com"
    assert log[4].response_code == "NXDOMAIN"


def test_override_crud():
    """Test override add/remove."""
    config = dns_manager.get_config()
    original_count = len(config.overrides)

    # Add
    dns_manager.add_override(DnsOverride(domain="test123.com", record_type="A", value="1.2.3.4"))
    assert len(dns_manager.get_overrides()) == original_count + 1

    # Update same domain
    dns_manager.add_override(DnsOverride(domain="test123.com", record_type="A", value="5.6.7.8"))
    overrides = dns_manager.get_overrides()
    test_override = [o for o in overrides if o.domain == "test123.com"]
    assert len(test_override) == 1
    assert test_override[0].value == "5.6.7.8"

    # Remove
    dns_manager.remove_override("test123.com")
    assert not any(o.domain == "test123.com" for o in dns_manager.get_overrides())
