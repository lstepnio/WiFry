"""Hardware test fixtures and configuration.

HW tests hit the real running backend at http://localhost:8080.
They auto-skip on non-Linux systems and when WIFRY_MOCK_MODE is set.
"""

import platform

import httpx
import pytest
import pytest_asyncio

from .hw_capabilities import WifiCapabilities, detect_capabilities


def pytest_addoption(parser):
    parser.addoption(
        "--hw-client-ip",
        action="store",
        default=None,
        help="IP of a WiFi client connected to the AP (required for Tier 3 integration tests)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "hw_readiness: Tier 1 — system readiness checks")
    config.addinivalue_line("markers", "hw_smoke: Tier 2 — API smoke tests on real hardware")
    config.addinivalue_line("markers", "hw_integration: Tier 3 — full integration with connected client")


def pytest_collection_modifyitems(config, items):
    """Auto-skip all HW tests on non-Linux systems or when mock mode is set."""
    import os

    skip_reason = None
    if platform.system() != "Linux":
        skip_reason = f"HW tests require Linux (running on {platform.system()})"
    elif os.environ.get("WIFRY_MOCK_MODE", "").lower() in ("true", "1"):
        skip_reason = "HW tests skip when WIFRY_MOCK_MODE is set"

    if skip_reason:
        skip = pytest.mark.skip(reason=skip_reason)
        for item in items:
            if "tests/hw/" in str(item.fspath):
                item.add_marker(skip)


@pytest_asyncio.fixture(scope="session")
async def wifi_caps() -> WifiCapabilities:
    """Detect and cache WiFi driver capabilities for the session."""
    return await detect_capabilities()


@pytest.fixture
def client_ip(request) -> str:
    """Get the connected client IP from --hw-client-ip flag."""
    ip = request.config.getoption("--hw-client-ip")
    if not ip:
        pytest.skip("No --hw-client-ip provided (required for integration tests)")
    return ip


@pytest_asyncio.fixture
async def api() -> httpx.AsyncClient:
    """HTTP client pointing at the real running backend."""
    async with httpx.AsyncClient(
        base_url="http://localhost:8080",
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def cleanup_impairments(api: httpx.AsyncClient):
    """Clean up any impairments after each test."""
    yield
    # Clear tc netem impairments
    try:
        resp = await api.get("/api/v1/impairments")
        if resp.status_code == 200:
            for state in resp.json():
                if state.get("active"):
                    await api.delete(f"/api/v1/impairments/{state['interface']}")
    except Exception:
        pass

    # Clear WiFi impairments
    try:
        await api.delete("/api/v1/wifi-impairments")
    except Exception:
        pass
