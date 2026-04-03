"""Scenarios + reports router."""

from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

from ..models.scenario import ScenarioDefinition, ScenarioRun
from ..services import report_generator, scheduler

router = APIRouter(tags=["scenarios"])


# --- Scenario runs (fixed paths BEFORE parameterized) ---

@router.get("/api/v1/scenarios/runs", response_model=List[ScenarioRun])
async def list_runs():
    return scheduler.list_runs()


@router.get("/api/v1/scenarios/runs/{run_id}", response_model=ScenarioRun)
async def get_run(run_id: str):
    run = scheduler.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return run


@router.post("/api/v1/scenarios/runs/{run_id}/stop", response_model=ScenarioRun)
async def stop_scenario(run_id: str):
    try:
        return await scheduler.stop_scenario(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- Scenarios CRUD ---

@router.get("/api/v1/scenarios", response_model=List[ScenarioDefinition])
async def list_scenarios():
    return scheduler.list_scenarios()


@router.post("/api/v1/scenarios", response_model=ScenarioDefinition, status_code=201)
async def create_scenario(defn: ScenarioDefinition):
    return scheduler.create_scenario(defn)


@router.get("/api/v1/scenarios/{scenario_id}", response_model=ScenarioDefinition)
async def get_scenario(scenario_id: str):
    defn = scheduler.get_scenario(scenario_id)
    if not defn:
        raise HTTPException(404, f"Scenario '{scenario_id}' not found")
    return defn


@router.delete("/api/v1/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str):
    scheduler.delete_scenario(scenario_id)
    return {"status": "ok"}


@router.post("/api/v1/scenarios/{scenario_id}/run", response_model=ScenarioRun)
async def run_scenario(scenario_id: str):
    try:
        return await scheduler.run_scenario(scenario_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- Reports ---

@router.post("/api/v1/reports/generate")
async def generate_report(run_id: str):
    """Generate an HTML report for a scenario run."""
    run = scheduler.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")

    path = report_generator.generate_report(run)
    return {"status": "ok", "path": path}


@router.get("/api/v1/reports")
async def list_reports():
    return report_generator.list_reports()


@router.get("/api/v1/reports/{filename}")
async def download_report(filename: str):
    reports = report_generator.list_reports()
    for r in reports:
        if r["filename"] == filename:
            return FileResponse(r["path"], filename=filename, media_type="text/html")
    raise HTTPException(404, "Report not found")
