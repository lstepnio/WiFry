"""Shared test fixtures and cleanup.

Ensures all test data is cleaned up after the test suite completes
so we don't accumulate stale data in /tmp/wifry-* directories.
"""

import shutil
from pathlib import Path

import pytest


# All tmp directories that WiFry services create in mock mode
WIFRY_TMP_DIRS = [
    "/tmp/wifry-captures",
    "/tmp/wifry-segments",
    "/tmp/wifry-sessions",
    "/tmp/wifry-adb-files",
    "/tmp/wifry-hdmi",
    "/tmp/wifry-bundles",
    "/tmp/wifry-reports",
    "/tmp/wifry-annotations",
    "/tmp/wifry-scenarios",
    "/tmp/wifry-teleport",
    "/tmp/wifry-coredns",
    "/tmp/wifry-network-profiles",
]

WIFRY_TMP_FILES = [
    "/tmp/wifry-settings.json",
    "/tmp/wifry-storage.json",
    "/tmp/wifry-network-config.json",
    "/tmp/wifry-feature-flags.json",
]


def _cleanup():
    """Remove all WiFry temp directories and files."""
    for d in WIFRY_TMP_DIRS:
        p = Path(d)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for f in WIFRY_TMP_FILES:
        p = Path(f)
        if p.exists():
            p.unlink(missing_ok=True)


@pytest.fixture(autouse=True, scope="session")
def cleanup_after_all_tests():
    """Run cleanup after the entire test suite finishes."""
    yield
    _cleanup()
