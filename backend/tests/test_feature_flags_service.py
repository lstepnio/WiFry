"""Service-level tests for feature flag persistence and defaults."""

import importlib
import json

import pytest

from app.services import feature_flags


@pytest.fixture(autouse=True)
def reset_feature_flags_module():
    """Start each test from a clean feature-flag module state."""
    feature_flags.FLAGS_PATH.unlink(missing_ok=True)
    feature_flags._flags = {}
    feature_flags._loaded = False
    yield
    feature_flags.FLAGS_PATH.unlink(missing_ok=True)
    feature_flags._flags = {}
    feature_flags._loaded = False


def test_get_all_returns_defaults():
    flags = feature_flags.get_all()

    assert flags["sessions"]["enabled"] is True
    assert flags["sharing_fileio"]["enabled"] is True
    assert flags["sharing_tunnel"]["enabled"] is False
    assert flags["collaboration"]["enabled"] is False


def test_set_flag_persists_only_override():
    feature_flags.set_flag("sharing_tunnel", True)

    saved = json.loads(feature_flags.FLAGS_PATH.read_text())
    assert saved == {"sharing_tunnel": {"enabled": True}}


def test_reload_reads_saved_overrides():
    feature_flags.set_flag("sharing_tunnel", True)

    reloaded = importlib.reload(feature_flags)
    flags = reloaded.get_all()

    assert flags["sharing_tunnel"]["enabled"] is True
    assert flags["sharing_fileio"]["enabled"] is True


def test_reset_defaults_clears_saved_overrides():
    feature_flags.set_flag("sharing_tunnel", True)

    flags = feature_flags.reset_defaults()

    assert flags["sharing_tunnel"]["enabled"] is False
    assert json.loads(feature_flags.FLAGS_PATH.read_text()) == {}


def test_set_flag_rejects_unknown_flag():
    with pytest.raises(ValueError, match="Unknown feature flag"):
        feature_flags.set_flag("not-a-real-flag", True)
