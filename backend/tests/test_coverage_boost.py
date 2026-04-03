"""Coverage boost tests for under-tested service modules.

Targets: bundle_generator, teleport, hdmi_capture, fileio, tunnel,
collaboration, network_config, storage, report_generator, capture,
shell, settings_manager.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from app.config import settings

assert settings.mock_mode, "These tests require mock_mode=True"


# ---------------------------------------------------------------------------
# 1. bundle_generator.py
# ---------------------------------------------------------------------------

class TestBundleGenerator:
    async def test_generate_bundle(self):
        from app.services import session_manager, bundle_generator
        from app.models.session import CreateSessionRequest, ArtifactType

        req = CreateSessionRequest(name="Bundle-Test", tags=["bundle"])
        session = await session_manager.create_session(req)
        await session_manager.add_artifact(
            session.id, ArtifactType.NOTE, "Note-1", data={"text": "hello"},
        )

        bundle = await bundle_generator.generate_bundle(session.id)
        assert bundle.session_id == session.id
        assert bundle.session_name == "Bundle-Test"
        assert bundle.size_bytes > 0
        assert bundle.artifact_count >= 1
        assert bundle.bundle_path.endswith(".zip")
        assert Path(bundle.bundle_path).exists()

        # cleanup
        Path(bundle.bundle_path).unlink(missing_ok=True)
        await session_manager.delete_session(session.id)

    async def test_generate_bundle_nonexistent_session(self):
        from app.services.bundle_generator import generate_bundle

        with pytest.raises(ValueError, match="not found"):
            await generate_bundle("nonexistent-session-xyz")

    async def test_list_bundles(self):
        from app.services.bundle_generator import list_bundles

        bundles = list_bundles()
        assert isinstance(bundles, list)


# ---------------------------------------------------------------------------
# 2. teleport.py
# ---------------------------------------------------------------------------

class TestTeleport:
    def setup_method(self):
        from app.services import teleport
        teleport._profiles.clear()
        teleport._active_profile_id = None
        teleport._connected_at = None

    def test_create_profile(self):
        from app.services.teleport import create_profile

        profile = create_profile(
            name="US East",
            config_contents="[Interface]\nPrivateKey=abc\n",
            vpn_type="wireguard",
            market="us-east",
            region="North America",
            expected_ip="1.2.3.4",
        )
        assert profile.name == "US East"
        assert profile.vpn_type == "wireguard"
        assert profile.market == "us-east"
        assert profile.id

    def test_list_profiles(self):
        from app.services.teleport import create_profile, list_profiles

        create_profile(name="Profile-A", config_contents="cfg-a")
        create_profile(name="Profile-B", config_contents="cfg-b")
        profiles = list_profiles()
        names = [p.name for p in profiles]
        assert "Profile-A" in names
        assert "Profile-B" in names

    def test_get_profile(self):
        from app.services.teleport import create_profile, get_profile

        p = create_profile(name="Get-Me", config_contents="cfg")
        found = get_profile(p.id)
        assert found is not None
        assert found.name == "Get-Me"

    def test_get_profile_not_found(self):
        from app.services.teleport import get_profile

        assert get_profile("no-such-id") is None

    def test_delete_profile(self):
        from app.services.teleport import create_profile, delete_profile, get_profile, _profiles

        p = create_profile(name="Delete-Me", config_contents="cfg")
        delete_profile(p.id)
        assert p.id not in _profiles

    async def test_connect_and_disconnect(self):
        from app.services.teleport import create_profile, connect, disconnect, get_status

        p = create_profile(
            name="Connect-Test",
            config_contents="[Interface]\nKey=test\n",
            market="test-market",
            expected_ip="5.6.7.8",
        )
        status = await connect(p.id)
        assert status.connected is True
        assert status.active_profile == p.id
        assert status.market == "test-market"

        status = await disconnect()
        assert status.connected is False
        assert status.active_profile is None

    async def test_connect_nonexistent_profile(self):
        from app.services.teleport import connect

        with pytest.raises(ValueError, match="not found"):
            await connect("no-such-profile")

    def test_get_status_disconnected(self):
        from app.services.teleport import get_status

        status = get_status()
        assert status.connected is False

    async def test_verify_connection_disconnected(self):
        from app.services.teleport import verify_connection

        result = await verify_connection()
        assert result["connected"] is False

    async def test_verify_connection_connected(self):
        from app.services.teleport import create_profile, connect, verify_connection

        p = create_profile(
            name="Verify-Test", config_contents="cfg",
            expected_ip="9.8.7.6", expected_country="US",
        )
        await connect(p.id)
        result = await verify_connection()
        assert result["connected"] is True
        assert result["verified"] is True
        assert result["public_ip"] == "9.8.7.6"


# ---------------------------------------------------------------------------
# 3. hdmi_capture.py
# ---------------------------------------------------------------------------

class TestHdmiCapture:
    def setup_method(self):
        from app.services.hdmi_capture import _recordings
        _recordings.clear()

    async def test_detect_devices(self):
        from app.services.hdmi_capture import detect_devices

        devices = await detect_devices()
        assert len(devices) == 1
        assert devices[0]["name"] == "Elgato Cam Link 4K"
        assert devices[0]["connected"] is True

    async def test_capture_frame(self):
        from app.services.hdmi_capture import capture_frame

        path = await capture_frame()
        assert path.endswith(".png")
        assert Path(path).exists()
        Path(path).unlink(missing_ok=True)

    async def test_start_recording(self):
        from app.services.hdmi_capture import start_recording

        rec = await start_recording()
        assert rec["id"]
        assert rec["status"] == "recording"
        assert rec["device"] == "/dev/video0"

    async def test_stop_recording(self):
        from app.services.hdmi_capture import start_recording, stop_recording

        rec = await start_recording()
        stopped = await stop_recording(rec["id"])
        assert stopped["status"] == "stopped"

    async def test_stop_recording_nonexistent(self):
        from app.services.hdmi_capture import stop_recording

        result = await stop_recording("no-such-id")
        assert result.get("status") == "stopped"

    def test_list_recordings_empty(self):
        from app.services.hdmi_capture import list_recordings

        recs = list_recordings()
        assert isinstance(recs, list)

    async def test_list_recordings_after_start(self):
        from app.services.hdmi_capture import start_recording, list_recordings

        await start_recording()
        recs = list_recordings()
        assert len(recs) >= 1

    def test_list_frames(self):
        from app.services.hdmi_capture import list_frames

        frames = list_frames()
        assert isinstance(frames, list)


# ---------------------------------------------------------------------------
# 4. fileio.py
# ---------------------------------------------------------------------------

class TestFileIO:
    async def test_upload_file_mock(self):
        from app.services.fileio import upload_file

        # Create a temp file to upload
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test data for fileio")
            tmp_path = f.name

        try:
            result = await upload_file(tmp_path)
            assert result["success"] is True
            assert result["link"].startswith("https://file.io/")
            assert result["filename"].endswith(".txt")
        finally:
            os.unlink(tmp_path)

    async def test_upload_file_not_found(self):
        from app.services.fileio import upload_file

        result = await upload_file("/nonexistent/file.txt")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    async def test_upload_bundle_mock(self):
        from app.services.fileio import upload_bundle

        files = []
        for i in range(2):
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                f.write(f"bundle file {i}".encode())
                files.append(f.name)

        try:
            result = await upload_bundle(files, bundle_name="test_bundle.zip")
            assert result["success"] is True
            assert result["files_bundled"] == 2
            assert result["link"].startswith("https://file.io/")
        finally:
            for f in files:
                os.unlink(f)

    async def test_upload_bundle_empty(self):
        from app.services.fileio import upload_bundle

        result = await upload_bundle([])
        assert result["success"] is False

    async def test_upload_category_unknown(self):
        from app.services.fileio import upload_category

        result = await upload_category("nonexistent_category")
        assert result["success"] is False

    def test_get_history(self):
        from app.services.fileio import get_history

        history = get_history()
        assert isinstance(history, list)


# ---------------------------------------------------------------------------
# 5. tunnel.py
# ---------------------------------------------------------------------------

class TestTunnel:
    def setup_method(self):
        from app.services import tunnel
        tunnel._tunnel_url = None
        tunnel._started_at = None
        tunnel._tunnel_process = None

    async def test_start_tunnel(self):
        from app.services.tunnel import start_tunnel

        status = await start_tunnel()
        assert status["active"] is True
        assert "trycloudflare.com" in status["url"]
        assert status["started_at"] is not None
        assert status["share_url"] is not None

    async def test_stop_tunnel(self):
        from app.services.tunnel import start_tunnel, stop_tunnel

        await start_tunnel()
        status = await stop_tunnel()
        assert status["active"] is False
        assert status["url"] is None

    def test_get_status_inactive(self):
        from app.services.tunnel import get_status

        status = get_status()
        assert status["active"] is False
        assert status["url"] is None
        assert status["share_url"] is None

    async def test_check_cloudflared(self):
        from app.services.tunnel import check_cloudflared

        result = await check_cloudflared()
        assert result["installed"] is True
        assert "mock" in result["version"]

    async def test_start_tunnel_idempotent(self):
        from app.services.tunnel import start_tunnel

        status1 = await start_tunnel()
        # In mock mode calling again should still return active status
        status2 = await start_tunnel()
        assert status2["active"] is True


# ---------------------------------------------------------------------------
# 6. collaboration.py
# ---------------------------------------------------------------------------

class TestCollaboration:
    def setup_method(self):
        from app.services import collaboration
        collaboration._mode = collaboration.CollaborationMode.CO_PILOT
        collaboration._connected_users.clear()
        collaboration._websockets.clear()

    def test_get_mode(self):
        from app.services.collaboration import get_mode

        assert get_mode() in ("spectate", "co-pilot", "download")

    async def test_set_mode_valid(self):
        from app.services.collaboration import set_mode, get_mode

        result = set_mode("spectate")
        assert get_mode() == "spectate"
        assert result["mode"] == "spectate"

    async def test_set_mode_co_pilot(self):
        from app.services.collaboration import set_mode, get_mode

        set_mode("co-pilot")
        assert get_mode() == "co-pilot"

    async def test_set_mode_download(self):
        from app.services.collaboration import set_mode, get_mode

        set_mode("download")
        assert get_mode() == "download"

    def test_set_mode_invalid(self):
        from app.services.collaboration import set_mode

        with pytest.raises(ValueError, match="Invalid mode"):
            set_mode("invalid-mode")

    def test_get_status(self):
        from app.services.collaboration import get_status

        status = get_status()
        assert "mode" in status
        assert "connected_users" in status
        assert "user_count" in status
        assert "shared_state" in status

    async def test_broadcast_state_update(self):
        from app.services.collaboration import broadcast_state_update, _shared_state

        await broadcast_state_update("test_action", {"key": "value"})
        assert _shared_state["last_action"] == "test_action"
        assert _shared_state["last_action_at"] is not None


# ---------------------------------------------------------------------------
# 7. network_config.py
# ---------------------------------------------------------------------------

class TestNetworkConfig:
    def setup_method(self):
        from app.services import network_config
        network_config._current_config = None
        network_config._profiles.clear()

    def test_get_current_config(self):
        from app.services.network_config import get_current_config

        config = get_current_config()
        assert config is not None
        assert config.wifi_ap.ssid  # has a default SSID
        assert config.fallback.enabled is True

    def test_is_first_boot(self):
        from app.services.network_config import is_first_boot

        # Default config has first_boot=True
        result = is_first_boot()
        assert isinstance(result, bool)

    async def test_apply_config(self):
        from app.services.network_config import apply_config, get_current_config
        from app.models.network_config import FullNetworkConfig

        config = FullNetworkConfig()
        config.wifi_ap.ssid = "TestSSID"
        config.wifi_ap.channel = 11

        result = await apply_config(config)
        assert result.wifi_ap.ssid == "TestSSID"
        assert result.first_boot is False

    async def test_apply_defaults(self):
        from app.services.network_config import apply_defaults

        config = await apply_defaults()
        assert config.first_boot is False
        assert config.wifi_ap.ssid  # has default SSID

    def test_save_and_list_profiles(self):
        from app.services.network_config import save_profile, list_profiles

        profile = save_profile("Test-Profile", description="A test profile")
        assert profile.name == "Test-Profile"
        assert profile.id

        profiles = list_profiles()
        names = [p.name for p in profiles]
        assert "Test-Profile" in names

    def test_load_profile(self):
        from app.services.network_config import save_profile, load_profile

        p = save_profile("Load-Me")
        loaded = load_profile(p.id)
        assert loaded is not None
        assert loaded.name == "Load-Me"

    def test_load_profile_not_found(self):
        from app.services.network_config import load_profile

        assert load_profile("nonexistent") is None

    def test_delete_profile(self):
        from app.services.network_config import save_profile, delete_profile, _profiles

        p = save_profile("Delete-Me")
        delete_profile(p.id)
        assert p.id not in _profiles

    def test_set_boot_profile(self):
        from app.services.network_config import save_profile, set_boot_profile

        p = save_profile("Boot-Profile")
        result = set_boot_profile(p.id)
        assert result.is_boot_profile is True

    def test_set_boot_profile_not_found(self):
        from app.services.network_config import set_boot_profile

        with pytest.raises(ValueError, match="not found"):
            set_boot_profile("nonexistent-id")

    def test_clear_boot_profile(self):
        from app.services.network_config import save_profile, set_boot_profile, clear_boot_profile, _profiles

        p = save_profile("Boot-Clear")
        set_boot_profile(p.id)
        clear_boot_profile()
        # After clearing, no profile should be marked as boot
        assert _profiles[p.id].is_boot_profile is False

    async def test_apply_profile(self):
        from app.services.network_config import save_profile, apply_profile

        p = save_profile("Apply-Profile")
        config = await apply_profile(p.id)
        assert config.first_boot is False

    async def test_apply_profile_not_found(self):
        from app.services.network_config import apply_profile

        with pytest.raises(ValueError, match="not found"):
            await apply_profile("nonexistent-profile")


# ---------------------------------------------------------------------------
# 8. storage.py
# ---------------------------------------------------------------------------

class TestStorage:
    def test_get_data_paths(self):
        from app.services.storage import get_data_paths

        paths = get_data_paths()
        assert "captures" in paths
        assert "logs" in paths
        assert "reports" in paths
        assert "hdmi" in paths

    def test_get_status(self):
        from app.services.storage import get_status

        status = get_status()
        assert "external_active" in status
        assert "paths" in status
        assert isinstance(status["paths"], dict)

    async def test_detect_devices(self):
        from app.services.storage import detect_devices

        devices = await detect_devices()
        assert len(devices) == 1
        assert devices[0]["device"] == "/dev/sda1"
        assert devices[0]["label"] == "WIFRY_USB"

    async def test_get_usage(self):
        from app.services.storage import get_usage

        usage = await get_usage()
        assert "_total" in usage
        assert "size_bytes" in usage["_total"]
        assert "file_count" in usage["_total"]


# ---------------------------------------------------------------------------
# 9. report_generator.py
# ---------------------------------------------------------------------------

class TestReportGenerator:
    def test_generate_report(self):
        from app.services.report_generator import generate_report, REPORTS_DIR
        from app.models.scenario import ScenarioRun, ScenarioStepResult, ScenarioStatus

        run = ScenarioRun(
            id="run-001",
            scenario_id="scenario-001",
            scenario_name="Stress Test",
            status=ScenarioStatus.COMPLETED,
            total_steps=2,
            total_repeats=1,
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:10:00Z",
            step_results=[
                ScenarioStepResult(
                    step_index=0,
                    label="Baseline",
                    started_at="2025-01-01T00:00:00Z",
                    completed_at="2025-01-01T00:05:00Z",
                    profile_applied="clean",
                    capture_id="cap-001",
                ),
                ScenarioStepResult(
                    step_index=1,
                    label="Impaired",
                    started_at="2025-01-01T00:05:00Z",
                    completed_at="2025-01-01T00:10:00Z",
                    profile_applied="3G-Slow",
                ),
            ],
        )

        path = generate_report(run)
        assert path.endswith(".html")
        p = Path(path)
        assert p.exists()
        content = p.read_text()
        assert "Stress Test" in content
        assert "Baseline" in content
        assert "Impaired" in content
        p.unlink(missing_ok=True)

    def test_generate_report_with_analyses(self):
        from app.services.report_generator import generate_report
        from app.models.scenario import ScenarioRun, ScenarioStatus

        run = ScenarioRun(
            id="run-002",
            scenario_id="s-002",
            scenario_name="Analysis Test",
            status=ScenarioStatus.COMPLETED,
            total_steps=0,
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:01:00Z",
        )

        analyses = [
            {
                "capture_id": "cap-x",
                "summary": "Found retransmissions",
                "issues": [
                    {"severity": "high", "description": "Many retransmissions"},
                ],
            }
        ]
        path = generate_report(run, capture_analyses=analyses)
        content = Path(path).read_text()
        assert "Found retransmissions" in content
        Path(path).unlink(missing_ok=True)

    def test_list_reports(self):
        from app.services.report_generator import list_reports

        reports = list_reports()
        assert isinstance(reports, list)


# ---------------------------------------------------------------------------
# 10. capture.py
# ---------------------------------------------------------------------------

class TestCapture:
    async def test_get_capture_stats_mock(self):
        from app.services import capture as capture_service
        from app.models.capture import StartCaptureRequest

        req = StartCaptureRequest(interface="wlan0", name="stats-test")
        cap = await capture_service.start_capture(req)

        stats = await capture_service.get_capture_stats(cap.id)
        assert "protocol_hierarchy" in stats
        assert "tcp_conversations" in stats
        assert "io_stats" in stats
        assert "expert_info" in stats
        assert "dns_queries" in stats

    async def test_get_capture_stats_nonexistent(self):
        from app.services.capture import get_capture_stats

        stats = await get_capture_stats("nonexistent-capture-id")
        assert stats == {}

    def test_get_pcap_path_nonexistent(self):
        from app.services.capture import get_pcap_path

        result = get_pcap_path("nonexistent-capture-999")
        assert result is None


# ---------------------------------------------------------------------------
# 11. shell.py (actual run function)
# ---------------------------------------------------------------------------

class TestShellRun:
    async def test_run_echo(self):
        from app.utils.shell import run

        result = await run("echo", "hello")
        assert result.success is True
        assert result.stdout == "hello"

    async def test_run_false_no_check(self):
        from app.utils.shell import run

        result = await run("false", check=False)
        assert result.success is False
        assert result.returncode != 0

    async def test_run_false_with_check(self):
        from app.utils.shell import run

        with pytest.raises(RuntimeError, match="Command failed"):
            await run("false", check=True)

    async def test_run_timeout(self):
        from app.utils.shell import run

        with pytest.raises(asyncio.TimeoutError):
            await run("sleep", "10", timeout=0.1)

    async def test_run_stderr(self):
        from app.utils.shell import run

        result = await run("sh", "-c", "echo err >&2", check=False)
        assert "err" in result.stderr


# ---------------------------------------------------------------------------
# 12. settings_manager.py
# ---------------------------------------------------------------------------

class TestSettingsManager:
    def setup_method(self):
        from app.services import settings_manager
        settings_manager._user_settings.clear()
        if settings_manager.SETTINGS_PATH.exists():
            settings_manager.SETTINGS_PATH.unlink()

    def test_get_all(self):
        from app.services.settings_manager import get_all

        s = get_all()
        assert "ai_provider" in s
        assert "anthropic_api_key_set" in s
        assert "web_password_set" in s
        assert "ap_ssid" in s

    def test_update(self):
        from app.services.settings_manager import update, get_all

        result = update({"ai_provider": "openai", "ap_channel": 11})
        assert result["ai_provider"] == "openai"
        assert result["ap_channel"] == 11

    def test_update_ignores_masked_values(self):
        from app.services.settings_manager import update, get_all

        update({"anthropic_api_key": "sk-real-key-12345678"})
        # Now try updating with a masked value -- should not overwrite
        update({"anthropic_api_key": "****"})
        s = get_all()
        assert s["anthropic_api_key_set"] is True

    async def test_change_password_first_time(self):
        from app.services.settings_manager import change_password

        result = await change_password("", "newpass123")
        assert result["status"] == "ok"

    async def test_change_password_wrong_current(self):
        from app.services.settings_manager import change_password

        await change_password("", "first-pass")
        result = await change_password("wrong-pass", "new-pass")
        assert result["status"] == "error"

    async def test_set_git_repo(self):
        from app.services.settings_manager import set_git_repo

        result = await set_git_repo("https://github.com/example/repo.git")
        assert result["status"] == "ok"
        assert result["git_repo_url"] == "https://github.com/example/repo.git"
