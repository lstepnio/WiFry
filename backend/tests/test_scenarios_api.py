"""Integration tests for scenario CRUD and run endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


async def _create_scenario(client: AsyncClient, name: str = "Test Scenario") -> dict:
    """Helper to create a scenario and return its JSON."""
    resp = await client.post("/api/v1/scenarios", json={
        "name": name,
        "description": "Automated test scenario",
        "interface": "wlan0",
        "steps": [
            {"label": "Baseline", "duration_secs": 1},
            {"label": "Add delay", "duration_secs": 1,
             "impairment": {"delay": {"ms": 100}}},
        ],
    })
    assert resp.status_code == 201
    return resp.json()


# --- CRUD ---

async def test_create_scenario(client: AsyncClient):
    data = await _create_scenario(client)
    assert data["name"] == "Test Scenario"
    assert data["id"]
    assert len(data["steps"]) == 2


async def test_list_scenarios(client: AsyncClient):
    await _create_scenario(client, "List-A")
    await _create_scenario(client, "List-B")
    resp = await client.get("/api/v1/scenarios")
    assert resp.status_code == 200
    scenarios = resp.json()
    assert isinstance(scenarios, list)
    names = [s["name"] for s in scenarios]
    assert "List-A" in names
    assert "List-B" in names


async def test_get_scenario(client: AsyncClient):
    created = await _create_scenario(client, "Get-Me")
    sid = created["id"]

    resp = await client.get(f"/api/v1/scenarios/{sid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid
    assert resp.json()["name"] == "Get-Me"


async def test_get_scenario_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/scenarios/nonexistent-id")
    assert resp.status_code == 404


async def test_delete_scenario(client: AsyncClient):
    created = await _create_scenario(client, "Delete-Me")
    sid = created["id"]

    resp = await client.delete(f"/api/v1/scenarios/{sid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify it's gone
    resp = await client.get(f"/api/v1/scenarios/{sid}")
    assert resp.status_code == 404


# --- Runs ---

async def test_run_scenario(client: AsyncClient):
    created = await _create_scenario(client, "Run-Me")
    sid = created["id"]

    resp = await client.post(f"/api/v1/scenarios/{sid}/run")
    assert resp.status_code == 200
    run = resp.json()
    assert run["scenario_id"] == sid
    assert run["scenario_name"] == "Run-Me"
    assert run["status"] == "running"
    assert run["total_steps"] == 2
    assert run["id"]


async def test_run_scenario_not_found(client: AsyncClient):
    resp = await client.post("/api/v1/scenarios/nonexistent/run")
    assert resp.status_code == 404


async def test_list_runs(client: AsyncClient):
    resp = await client.get("/api/v1/scenarios/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_run(client: AsyncClient):
    created = await _create_scenario(client, "Run-Detail")
    sid = created["id"]

    run_resp = await client.post(f"/api/v1/scenarios/{sid}/run")
    run_id = run_resp.json()["id"]

    resp = await client.get(f"/api/v1/scenarios/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == run_id


async def test_get_run_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/scenarios/runs/nonexistent-run")
    assert resp.status_code == 404


async def test_stop_run(client: AsyncClient):
    created = await _create_scenario(client, "Stop-Me")
    sid = created["id"]

    run_resp = await client.post(f"/api/v1/scenarios/{sid}/run")
    run_id = run_resp.json()["id"]

    resp = await client.post(f"/api/v1/scenarios/runs/{run_id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


async def test_stop_run_not_found(client: AsyncClient):
    resp = await client.post("/api/v1/scenarios/runs/nonexistent/stop")
    assert resp.status_code == 404


# --- Scenario with repeat ---

async def test_create_scenario_with_repeat(client: AsyncClient):
    resp = await client.post("/api/v1/scenarios", json={
        "name": "Repeat Scenario",
        "steps": [{"label": "Step 1", "duration_secs": 1}],
        "repeat": 3,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["repeat"] == 3


# --- Scenario with capture flag ---

async def test_create_scenario_with_capture(client: AsyncClient):
    resp = await client.post("/api/v1/scenarios", json={
        "name": "Capture Scenario",
        "steps": [
            {
                "label": "With Capture",
                "duration_secs": 1,
                "start_capture": True,
            },
        ],
    })
    assert resp.status_code == 201
    step = resp.json()["steps"][0]
    assert step["start_capture"] is True
