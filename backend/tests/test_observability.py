"""Observability regression tests."""

import json
import logging
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.session import ArtifactType, CreateSessionRequest
from app.observability import RequestContextFilter, StructuredJsonFormatter, bind_request_context, reset_request_context
from app.services import bundle_generator, session_manager


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


def test_structured_log_formatter_includes_request_context():
    formatter = StructuredJsonFormatter()
    token = bind_request_context(
        request_id="req-123456",
        method="PUT",
        path="/api/v1/system/settings",
        client_ip="127.0.0.1",
    )

    try:
        record = logging.makeLogRecord(
            {
                "name": "wifry.test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "settings.updated",
                "args": (),
                "event": "settings_update",
                "changed_keys": ["ai_provider"],
            }
        )
        RequestContextFilter().filter(record)
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_context(token)

    assert payload["request_id"] == "req-123456"
    assert payload["event"] == "settings_update"
    assert payload["changed_keys"] == ["ai_provider"]
    assert payload["logger"] == "wifry.test"


async def test_system_logs_mock_returns_structured_lines(client: AsyncClient):
    resp = await client.get("/api/v1/system/logs")
    assert resp.status_code == 200
    data = resp.json()
    parsed = json.loads(data["lines"][0])
    assert parsed["ts"]
    assert parsed["level"]
    assert parsed["logger"]
    assert parsed["message"]


async def test_request_id_header_and_audit_event(client: AsyncClient):
    request_id = "req-observe-001"
    resp = await client.put(
        "/api/v1/system/settings",
        headers={"X-Request-ID": request_id},
        json={"ai_provider": "openai"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-request-id"] == request_id

    audit_resp = await client.get("/api/v1/system/audit", params={"limit": 50})
    assert audit_resp.status_code == 200
    events = audit_resp.json()
    event = next(
        item for item in events
        if item["action"] == "system.settings.update" and item["request_id"] == request_id
    )
    assert "ai_provider" in event["details"]["changed_keys"]


async def test_bundle_share_and_diagnostics_are_observable(client: AsyncClient, tmp_path):
    session = await session_manager.create_session(CreateSessionRequest(name="Observability Session"))
    existing = tmp_path / "capture.pcap"
    existing.write_text("pcap bytes")

    await session_manager.add_artifact(
        session.id,
        ArtifactType.CAPTURE,
        "Existing Capture",
        file_path=str(existing),
    )
    await session_manager.add_artifact(
        session.id,
        ArtifactType.SCREENSHOT,
        "Missing Screenshot",
        file_path=str(tmp_path / "missing.png"),
    )

    bundle = await bundle_generator.generate_bundle(session.id)
    assert bundle.diagnostics["artifact_count"] == 2
    assert len(bundle.diagnostics["artifact_files_missing"]) == 1

    with zipfile.ZipFile(bundle.bundle_path) as archive:
        names = archive.namelist()
        assert "diagnostics/bundle_diagnostics.json" in names
        assert "diagnostics/recent_audit_events.json" not in names
        diagnostics = json.loads(archive.read("diagnostics/bundle_diagnostics.json"))
        assert diagnostics["artifact_count"] == 2
        assert len(diagnostics["artifact_files_missing"]) == 1
        assert diagnostics["includes_appliance_diagnostics"] is False

    request_id = "req-bundle-share-001"
    share_resp = await client.post(
        f"/api/v1/sessions/{session.id}/bundle/share",
        headers={"X-Request-ID": request_id},
    )
    assert share_resp.status_code == 200
    payload = share_resp.json()
    assert payload["upload"]["success"] is True
    assert payload["upload"]["request_id"] == request_id

    audit_resp = await client.get("/api/v1/system/audit", params={"limit": 100})
    events = audit_resp.json()
    assert any(
        item["action"] == "session.bundle.share"
        and item["request_id"] == request_id
        and item["resource_id"] == session.id
        for item in events
    )
    assert any(
        item["action"] == "sharing.fileio.upload"
        and item["request_id"] == request_id
        for item in events
    )
