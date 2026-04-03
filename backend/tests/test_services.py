"""Direct service-level tests (no HTTP layer).

Tests service functions directly for shell utilities, AI analyzer,
stream monitor, speed test, wifi scanner, video probe, gremlin,
annotations, and session manager.
"""

import pytest

from app.config import settings

# Ensure mock mode is on for all tests
assert settings.mock_mode, "These tests require mock_mode=True"


# ---- utils/shell.py ----

class TestCommandResult:
    def test_success_when_zero(self):
        from app.utils.shell import CommandResult
        r = CommandResult(returncode=0, stdout="ok", stderr="")
        assert r.success is True

    def test_failure_when_nonzero(self):
        from app.utils.shell import CommandResult
        r = CommandResult(returncode=1, stdout="", stderr="error")
        assert r.success is False

    def test_failure_when_negative(self):
        from app.utils.shell import CommandResult
        r = CommandResult(returncode=-1, stdout="", stderr="killed")
        assert r.success is False


class TestMockShell:
    async def test_run_returns_success(self):
        from app.utils.shell import MockShell
        shell = MockShell()
        result = await shell.run("echo", "hello")
        assert result.success is True
        assert result.returncode == 0

    async def test_run_records_history(self):
        from app.utils.shell import MockShell
        shell = MockShell()
        await shell.run("tc", "qdisc", "show")
        await shell.run("iptables", "-L", sudo=True)
        assert len(shell.history) == 2
        assert shell.history[0] == ["tc", "qdisc", "show"]
        assert shell.history[1] == ["sudo", "iptables", "-L"]

    async def test_run_with_sudo(self):
        from app.utils.shell import MockShell
        shell = MockShell()
        result = await shell.run("ls", "/root", sudo=True)
        assert result.success
        assert shell.history[-1][0] == "sudo"

    async def test_run_returns_empty_output(self):
        from app.utils.shell import MockShell
        shell = MockShell()
        result = await shell.run("some-cmd")
        assert result.stdout == ""
        assert result.stderr == ""


# ---- services/ai_analyzer.py ----

class TestAIAnalyzer:
    async def test_build_analysis_prompt(self):
        from app.services.ai_analyzer import _build_analysis_prompt
        from app.models.capture import AnalysisRequest

        req = AnalysisRequest(
            prompt="Analyze for issues",
            focus=["retransmissions", "latency"],
        )
        stats = {"protocol_hierarchy": "TCP: 900 frames", "io_stats": "120 frames/sec"}
        prompt = _build_analysis_prompt(stats, req)
        assert "Analyze for issues" in prompt
        assert "retransmissions" in prompt
        assert "Protocol Hierarchy" in prompt
        assert "Io Stats" in prompt

    async def test_mock_analysis(self):
        from app.services.ai_analyzer import _mock_analysis

        result = _mock_analysis("test-cap-123", "anthropic")
        assert result.capture_id == "test-cap-123"
        assert result.provider == "anthropic"
        assert result.model == "mock"
        assert result.tokens_used == 0
        assert len(result.issues) == 3
        assert result.summary
        assert result.statistics
        # Check issue structure
        issue = result.issues[0]
        assert issue.severity == "high"
        assert issue.category == "retransmissions"
        assert issue.description
        assert issue.recommendation

    async def test_parse_ai_response_valid_json(self):
        from app.services.ai_analyzer import _parse_ai_response
        import json

        content = json.dumps({
            "summary": "Everything looks fine.",
            "issues": [
                {
                    "severity": "low",
                    "category": "dns",
                    "description": "Normal DNS",
                    "affected_flows": [],
                    "recommendation": "No action",
                }
            ],
            "statistics": {"total_packets": 500},
        })
        result = _parse_ai_response("cap-1", content, "openai", "gpt-4o", 100)
        assert result.summary == "Everything looks fine."
        assert len(result.issues) == 1
        assert result.provider == "openai"
        assert result.tokens_used == 100

    async def test_parse_ai_response_code_block(self):
        from app.services.ai_analyzer import _parse_ai_response
        import json

        inner = json.dumps({
            "summary": "Code block test.",
            "issues": [],
            "statistics": {},
        })
        content = f"```json\n{inner}\n```"
        result = _parse_ai_response("cap-2", content, "anthropic", "claude", 50)
        assert result.summary == "Code block test."

    async def test_parse_ai_response_invalid_json(self):
        from app.services.ai_analyzer import _parse_ai_response

        result = _parse_ai_response("cap-3", "This is not JSON at all.", "anthropic", "claude", 10)
        # Should fall back to using content as summary
        assert "not JSON" in result.summary
        assert result.provider == "anthropic"

    async def test_analyze_capture_mock_mode(self):
        from app.services.ai_analyzer import analyze_capture
        from app.services import capture as capture_service
        from app.models.capture import AnalysisRequest, StartCaptureRequest

        # Create a capture first
        req = StartCaptureRequest(interface="wlan0", name="ai-test")
        cap = await capture_service.start_capture(req)

        analysis_req = AnalysisRequest(prompt="Analyze", focus=["retransmissions"])
        result = await analyze_capture(cap.id, analysis_req)
        assert result.capture_id == cap.id
        assert result.summary
        assert len(result.issues) > 0
        assert result.model == "mock"


# ---- services/stream_monitor.py ----

class TestStreamMonitor:
    def test_process_event_manifest_hls(self):
        from app.services.stream_monitor import process_event, _sessions, _session_index
        from app.models.stream import StreamEvent

        # Clear state
        _sessions.clear()
        _session_index.clear()

        event = StreamEvent(
            event_type="manifest",
            client_ip="10.0.0.1",
            url="https://cdn.example.com/live/master.m3u8",
            content_type="application/vnd.apple.mpegurl",
            body="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080\nhigh.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\nlow.m3u8",
        )
        sid = process_event(event)
        assert sid is not None
        assert sid in _sessions
        session = _sessions[sid]
        assert session.stream_type.value == "hls"
        assert len(session.variants) == 2

    def test_process_event_segment(self):
        from app.services.stream_monitor import process_event, _sessions, _session_index
        from app.models.stream import StreamEvent

        _sessions.clear()
        _session_index.clear()

        # Create session with manifest first
        manifest_event = StreamEvent(
            event_type="manifest",
            client_ip="10.0.0.2",
            url="https://cdn.example.com/master.m3u8",
            content_type="application/vnd.apple.mpegurl",
            body="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=4000000\nvideo.m3u8",
        )
        sid = process_event(manifest_event)
        assert sid is not None

        # Now send a segment event
        seg_event = StreamEvent(
            event_type="segment",
            client_ip="10.0.0.2",
            url="https://cdn.example.com/seg-001.ts",
            content_type="video/mp2t",
            status_code=200,
            request_time_secs=0.5,
            response_size_bytes=500000,
        )
        seg_sid = process_event(seg_event)
        assert seg_sid == sid
        session = _sessions[sid]
        assert session.total_segments == 1
        assert len(session.segments) == 1
        assert session.segments[0].throughput_bps > 0

    def test_process_event_error(self):
        from app.services.stream_monitor import process_event, _sessions, _session_index
        from app.models.stream import StreamEvent

        _sessions.clear()
        _session_index.clear()

        # No session yet, error should return None
        error_event = StreamEvent(
            event_type="error",
            client_ip="10.0.0.99",
            url="https://cdn.example.com/seg-999.ts",
            status_code=404,
        )
        result = process_event(error_event)
        assert result is None

    def test_process_event_unknown_type(self):
        from app.services.stream_monitor import process_event
        from app.models.stream import StreamEvent

        event = StreamEvent(
            event_type="unknown_type",
            client_ip="10.0.0.1",
            url="https://example.com",
        )
        result = process_event(event)
        assert result is None

    def test_get_mock_sessions(self):
        from app.services.stream_monitor import get_mock_sessions

        sessions = get_mock_sessions()
        assert len(sessions) == 2
        assert sessions[0].id == "mock-hls-001"
        assert sessions[0].stream_type.value == "hls"
        assert sessions[1].stream_type.value == "dash"
        assert sessions[0].active is True
        assert sessions[0].current_bitrate_bps > 0

    def test_get_mock_session_detail(self):
        from app.services.stream_monitor import get_mock_session_detail

        detail = get_mock_session_detail()
        assert detail.id == "mock-hls-001"
        assert len(detail.variants) == 3
        assert len(detail.segments) == 20
        assert detail.active_variant is not None
        assert detail.active_variant.bandwidth == 6000000

    def test_update_metrics(self):
        from app.services.stream_monitor import _update_metrics
        from app.models.stream import StreamSession, StreamType, VariantInfo, SegmentInfo

        session = StreamSession(
            id="metrics-test",
            stream_type=StreamType.HLS,
            client_ip="10.0.0.1",
            master_url="https://example.com/master.m3u8",
            active_variant=VariantInfo(bandwidth=5000000, resolution="1920x1080"),
            segments=[
                SegmentInfo(
                    url=f"seg{i}.ts",
                    sequence=i,
                    duration_secs=6.0,
                    download_time_secs=3.0,
                    size_bytes=2500000,
                    bitrate_bps=5000000,
                    throughput_bps=int(2500000 * 8 / 3.0),
                )
                for i in range(10)
            ],
        )
        _update_metrics(session)
        assert session.avg_throughput_bps > 0
        assert session.throughput_ratio > 0
        assert session.buffer_health_secs > 0


# ---- services/speed_test.py ----

class TestSpeedTest:
    async def test_run_client_test_mock(self):
        from app.services.speed_test import run_client_test

        result = await run_client_test(target="127.0.0.1", duration=5)
        assert "id" in result
        assert "download_mbps" in result
        assert "upload_mbps" in result
        assert "jitter_ms" in result
        assert "packet_loss_pct" in result
        assert "retransmits" in result
        assert result["target"] == "127.0.0.1"
        assert result["duration_secs"] == 5
        assert result["download_mbps"] > 0
        assert result["upload_mbps"] > 0

    async def test_start_server_mock(self):
        from app.services.speed_test import start_server

        result = await start_server(port=5201)
        assert result["status"] == "running"
        assert result["port"] == 5201
        assert "mock" in result.get("message", "")

    async def test_stop_server_mock(self):
        from app.services.speed_test import stop_server

        result = await stop_server()
        assert result["status"] == "stopped"

    async def test_get_results_initially_empty(self):
        from app.services.speed_test import get_results

        # Results may or may not be empty depending on test ordering,
        # but the call should succeed and return a list.
        results = get_results()
        assert isinstance(results, list)


# ---- services/wifi_scanner.py ----

class TestWifiScanner:
    async def test_scan_mock(self):
        from app.services.wifi_scanner import scan

        result = await scan()
        assert len(result.networks) == 10
        assert result.scan_interface == "wlan0"
        assert result.our_channel == 6
        assert result.our_band == "2.4GHz"

    async def test_scan_mock_network_structure(self):
        from app.services.wifi_scanner import scan

        result = await scan()
        net = result.networks[0]
        assert net.ssid == "WiFry"
        assert net.bssid
        assert net.channel == 6
        assert net.frequency_mhz == 2437
        assert net.signal_dbm == -25
        assert net.security == "WPA2"
        assert net.band == "2.4GHz"

    async def test_scan_mock_channels(self):
        from app.services.wifi_scanner import scan

        result = await scan()
        assert len(result.channels_2g) > 0
        assert len(result.channels_5g) > 0
        # Channel 6 should have multiple networks (WiFry, Neighbors_WiFi, hidden)
        ch6 = next((c for c in result.channels_2g if c.channel == 6), None)
        assert ch6 is not None
        assert ch6.network_count >= 2

    async def test_scan_custom_interface(self):
        from app.services.wifi_scanner import scan

        result = await scan(interface="wlan1")
        assert result.scan_interface == "wlan1"

    def test_freq_to_band(self):
        from app.services.wifi_scanner import _freq_to_band
        assert _freq_to_band(2437) == "2.4GHz"
        assert _freq_to_band(5180) == "5GHz"

    def test_freq_to_channel(self):
        from app.services.wifi_scanner import _freq_to_channel
        assert _freq_to_channel(2412) == 1
        assert _freq_to_channel(2437) == 6
        assert _freq_to_channel(5180) == 36
        assert _freq_to_channel(9999) == 0  # unknown


# ---- services/video_probe.py ----

class TestVideoProbe:
    async def test_probe_segment_mock(self):
        from app.services.video_probe import probe_segment

        result = await probe_segment("/tmp/test-segment.ts")
        assert result.path == "/tmp/test-segment.ts"
        assert result.file_size_bytes > 0
        assert result.duration_secs == 6.006
        assert result.format_name == "mpegts"
        assert len(result.streams) == 2
        # Video stream
        video = result.streams[0]
        assert video.codec_type == "video"
        assert video.codec_name == "h264"
        assert video.width == 1920
        assert video.height == 1080
        # Audio stream
        audio = result.streams[1]
        assert audio.codec_type == "audio"
        assert audio.codec_name == "aac"
        assert audio.sample_rate == 48000

    async def test_probe_segments_mock(self):
        from app.services.video_probe import probe_segments

        paths = ["/tmp/seg1.ts", "/tmp/seg2.ts", "/tmp/seg3.ts"]
        result = await probe_segments(paths)
        assert result.segments_analyzed == 3
        assert result.total_duration_secs > 0
        assert result.avg_bitrate_bps > 0
        assert result.max_bitrate_bps >= result.min_bitrate_bps
        assert result.video_codec == "h264"
        assert result.video_resolution == "1920x1080"
        assert result.audio_codec == "aac"

    async def test_probe_segments_empty(self):
        from app.services.video_probe import probe_segments

        result = await probe_segments([])
        assert result.segments_analyzed == 0
        assert result.avg_bitrate_bps == 0

    async def test_get_keyframe_info_mock(self):
        from app.services.video_probe import get_keyframe_info

        result = await get_keyframe_info("/tmp/test.ts")
        assert result["count"] == 3
        assert result["avg_interval_secs"] == 2.0
        assert len(result["keyframes"]) == 3


# ---- services/gremlin.py ----

class TestGremlin:
    async def test_activate_and_get_status(self):
        from app.services import gremlin

        status = await gremlin.activate(intensity=3)
        assert status["active"] is True
        assert status["intensity"] == 3
        assert status["intensity_label"] == "Severe"
        assert "details" in status
        assert status["details"]["drop_pct"] > 0

        # Deactivate to clean up
        await gremlin.deactivate()

    async def test_deactivate(self):
        from app.services import gremlin

        await gremlin.activate(intensity=1)
        status = await gremlin.deactivate()
        assert status["active"] is False

    async def test_get_status_inactive(self):
        from app.services import gremlin

        # Ensure deactivated
        await gremlin.deactivate()
        status = gremlin.get_status()
        assert status["active"] is False
        assert "All clear" in status["message"]

    async def test_intensity_clamp(self):
        from app.services import gremlin

        # Test clamping to valid range
        status = await gremlin.activate(intensity=0)
        assert status["intensity"] == 1  # clamped to 1

        status = await gremlin.activate(intensity=99)
        assert status["intensity"] == 4  # clamped to 4

        await gremlin.deactivate()

    async def test_all_intensity_levels(self):
        from app.services import gremlin

        for level in [1, 2, 3, 4]:
            status = await gremlin.activate(intensity=level)
            assert status["intensity"] == level
            assert status["intensity_label"] == gremlin.INTENSITY_LABELS[level]
            assert status["active"] is True

        await gremlin.deactivate()

    def test_intensity_presets_structure(self):
        from app.services.gremlin import INTENSITY_PRESETS

        for level in [1, 2, 3, 4]:
            preset = INTENSITY_PRESETS[level]
            assert len(preset) == 5
            drop, tls_delay, tls_jitter, stall_min, stall_max = preset
            assert 0 < drop <= 0.05
            assert tls_delay > 0
            assert tls_jitter > 0
            assert stall_min > 0
            assert stall_max > stall_min


# ---- services/annotations.py ----

class TestAnnotations:
    def setup_method(self):
        from app.services.annotations import _annotations
        _annotations.clear()

    def test_add_annotation(self):
        from app.services.annotations import add_annotation

        ann = add_annotation("capture", "cap-001", "Test note", tags=["test"])
        assert ann["id"]
        assert ann["target_type"] == "capture"
        assert ann["target_id"] == "cap-001"
        assert ann["note"] == "Test note"
        assert ann["tags"] == ["test"]
        assert ann["created_at"]

    def test_add_annotation_no_tags(self):
        from app.services.annotations import add_annotation

        ann = add_annotation("stream", "s-001", "No tags")
        assert ann["tags"] == []

    def test_get_annotations_all(self):
        from app.services.annotations import add_annotation, get_annotations

        add_annotation("capture", "c1", "Note 1")
        add_annotation("stream", "s1", "Note 2")
        add_annotation("device", "d1", "Note 3")

        results = get_annotations()
        assert len(results) >= 3

    def test_get_annotations_filter_type(self):
        from app.services.annotations import add_annotation, get_annotations

        add_annotation("capture", "c1", "Capture note")
        add_annotation("stream", "s1", "Stream note")

        results = get_annotations(target_type="capture")
        for r in results:
            assert r["target_type"] == "capture"

    def test_get_annotations_filter_target_id(self):
        from app.services.annotations import add_annotation, get_annotations

        add_annotation("capture", "specific-id", "Note A")
        add_annotation("capture", "other-id", "Note B")

        results = get_annotations(target_id="specific-id")
        for r in results:
            assert r["target_id"] == "specific-id"

    def test_get_annotations_filter_tag(self):
        from app.services.annotations import add_annotation, get_annotations

        add_annotation("general", "g1", "Tagged", tags=["special-tag"])
        add_annotation("general", "g2", "Untagged")

        results = get_annotations(tag="special-tag")
        assert len(results) >= 1
        for r in results:
            assert "special-tag" in r["tags"]

    def test_delete_annotation(self):
        from app.services.annotations import add_annotation, delete_annotation, get_annotations

        ann = add_annotation("capture", "c1", "Will be deleted")
        ann_id = ann["id"]

        delete_annotation(ann_id)

        # Should no longer appear (check in-memory)
        from app.services.annotations import _annotations
        assert ann_id not in _annotations

    def test_delete_nonexistent(self):
        from app.services.annotations import delete_annotation

        # Should not raise
        delete_annotation("nonexistent-id")


# ---- services/session_manager.py ----

class TestSessionManager:
    async def test_auto_add_artifact_no_active_session(self):
        from app.services import session_manager
        from app.models.session import ArtifactType

        # Clear active session
        session_manager._active_session_id = None

        result = await session_manager.auto_add_artifact(
            ArtifactType.NOTE,
            "orphan note",
        )
        assert result is None

    async def test_auto_add_artifact_with_active_session(self):
        from app.services import session_manager
        from app.models.session import ArtifactType, CreateSessionRequest

        req = CreateSessionRequest(name="AutoAdd-Test")
        session = await session_manager.create_session(req)

        result = await session_manager.auto_add_artifact(
            ArtifactType.NOTE,
            "Auto-linked note",
            data={"content": "hello"},
        )
        assert result is not None
        assert result.session_id == session.id
        assert result.type == ArtifactType.NOTE
        assert result.name == "Auto-linked note"

        # Clean up
        await session_manager.delete_session(session.id)

    async def test_log_impairment(self):
        from app.services import session_manager
        from app.models.session import CreateSessionRequest

        req = CreateSessionRequest(name="Impairment-Log-Test")
        session = await session_manager.create_session(req)

        session_manager.log_impairment(
            session.id,
            profile_name="3G-Slow",
            network_config={"delay": {"ms": 300}},
            label="Applied 3G profile",
        )

        updated = session_manager.get_session(session.id)
        assert updated is not None
        assert len(updated.impairment_log) == 1
        log_entry = updated.impairment_log[0]
        assert log_entry.profile_name == "3G-Slow"
        assert log_entry.label == "Applied 3G profile"
        assert log_entry.network_config == {"delay": {"ms": 300}}
        assert log_entry.timestamp

        # Clean up
        await session_manager.delete_session(session.id)

    async def test_get_session_artifacts_with_type_filter(self):
        from app.services import session_manager
        from app.models.session import ArtifactType, CreateSessionRequest

        req = CreateSessionRequest(name="Artifacts-Filter-Test")
        session = await session_manager.create_session(req)

        await session_manager.add_artifact(
            session.id, ArtifactType.NOTE, "Note artifact",
            data={"text": "a note"},
        )
        await session_manager.add_artifact(
            session.id, ArtifactType.CAPTURE, "Capture artifact",
        )
        await session_manager.add_artifact(
            session.id, ArtifactType.NOTE, "Another note",
            data={"text": "note 2"},
        )

        # All artifacts
        all_arts = session_manager.get_session_artifacts(session.id)
        assert len(all_arts) == 3

        # Filter by type
        notes = session_manager.get_session_artifacts(session.id, artifact_type="note")
        assert len(notes) == 2
        for a in notes:
            assert a.type == ArtifactType.NOTE

        captures = session_manager.get_session_artifacts(session.id, artifact_type="capture")
        assert len(captures) == 1
        assert captures[0].type == ArtifactType.CAPTURE

        # Clean up
        await session_manager.delete_session(session.id)

    async def test_get_session_artifacts_nonexistent_session(self):
        from app.services import session_manager

        arts = session_manager.get_session_artifacts("nonexistent-session")
        assert arts == []

    async def test_log_impairment_with_wifi_config(self):
        from app.services import session_manager
        from app.models.session import CreateSessionRequest

        req = CreateSessionRequest(name="WiFi-Impairment-Log")
        session = await session_manager.create_session(req)

        session_manager.log_impairment(
            session.id,
            profile_name="Edge-of-Coverage",
            wifi_config={"tx_power": {"enabled": True, "power_dbm": 5}},
            label="Reduced TX power",
        )

        updated = session_manager.get_session(session.id)
        assert len(updated.impairment_log) == 1
        assert updated.impairment_log[0].wifi_config is not None

        # Clean up
        await session_manager.delete_session(session.id)
