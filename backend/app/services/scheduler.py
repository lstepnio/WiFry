"""Automated test scenario scheduler.

Executes multi-step impairment scenarios with correlated
ADB logcat, packet captures, and screenshots.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.impairment import ImpairmentConfig
from ..models.scenario import (
    ScenarioDefinition,
    ScenarioRun,
    ScenarioStatus,
    ScenarioStepResult,
)
from . import adb_manager, capture, tc_manager

logger = logging.getLogger(__name__)

_scenarios: Dict[str, ScenarioDefinition] = {}
_runs: Dict[str, ScenarioRun] = {}
_run_tasks: Dict[str, asyncio.Task] = {}

SCENARIOS_DIR = Path("/var/lib/wifry/scenarios") if not settings.mock_mode else Path("/tmp/wifry-scenarios")


def _ensure_dir() -> Path:
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    return SCENARIOS_DIR


# --- Scenario CRUD ---

def create_scenario(defn: ScenarioDefinition) -> ScenarioDefinition:
    if not defn.id:
        defn.id = uuid.uuid4().hex[:12]
    _scenarios[defn.id] = defn
    _save_scenario(defn)
    return defn


def get_scenario(scenario_id: str) -> Optional[ScenarioDefinition]:
    if scenario_id in _scenarios:
        return _scenarios[scenario_id]
    return _load_scenario(scenario_id)


def list_scenarios() -> List[ScenarioDefinition]:
    _load_all_scenarios()
    return list(_scenarios.values())


def delete_scenario(scenario_id: str) -> None:
    _scenarios.pop(scenario_id, None)
    path = _ensure_dir() / f"{scenario_id}.json"
    path.unlink(missing_ok=True)


def _save_scenario(defn: ScenarioDefinition) -> None:
    path = _ensure_dir() / f"{defn.id}.json"
    path.write_text(defn.model_dump_json(indent=2))


def _load_scenario(scenario_id: str) -> Optional[ScenarioDefinition]:
    path = _ensure_dir() / f"{scenario_id}.json"
    if path.exists():
        defn = ScenarioDefinition.model_validate_json(path.read_text())
        _scenarios[defn.id] = defn
        return defn
    return None


def _load_all_scenarios() -> None:
    for f in _ensure_dir().glob("*.json"):
        sid = f.stem
        if sid not in _scenarios:
            _load_scenario(sid)


# --- Scenario execution ---

async def run_scenario(scenario_id: str) -> ScenarioRun:
    """Start executing a scenario."""
    defn = get_scenario(scenario_id)
    if not defn:
        raise ValueError(f"Scenario {scenario_id} not found")

    run_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    run_state = ScenarioRun(
        id=run_id,
        scenario_id=defn.id,
        scenario_name=defn.name,
        status=ScenarioStatus.RUNNING,
        total_steps=len(defn.steps) * defn.repeat,
        total_repeats=defn.repeat,
        started_at=now,
    )
    _runs[run_id] = run_state

    task = asyncio.create_task(_execute_scenario(run_id, defn))
    _run_tasks[run_id] = task

    logger.info("Started scenario run %s (%s)", run_id, defn.name)
    return run_state


async def stop_scenario(run_id: str) -> ScenarioRun:
    """Stop a running scenario."""
    run_state = _runs.get(run_id)
    if not run_state:
        raise ValueError(f"Run {run_id} not found")

    task = _run_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    run_state.status = ScenarioStatus.STOPPED
    run_state.completed_at = datetime.now(timezone.utc).isoformat()
    return run_state


def get_run(run_id: str) -> Optional[ScenarioRun]:
    return _runs.get(run_id)


def list_runs() -> List[ScenarioRun]:
    return sorted(_runs.values(), key=lambda r: r.started_at, reverse=True)


async def _execute_scenario(run_id: str, defn: ScenarioDefinition) -> None:
    """Execute all steps of a scenario."""
    run_state = _runs[run_id]

    try:
        for repeat in range(defn.repeat):
            run_state.current_repeat = repeat + 1

            for i, step in enumerate(defn.steps):
                if run_state.status != ScenarioStatus.RUNNING:
                    return

                run_state.current_step = (repeat * len(defn.steps)) + i + 1
                step_start = datetime.now(timezone.utc).isoformat()

                step_result = ScenarioStepResult(
                    step_index=run_state.current_step,
                    label=step.label or f"Step {i + 1}",
                    started_at=step_start,
                    completed_at="",
                )

                logger.info(
                    "Scenario %s: step %d/%d — %s",
                    run_id, run_state.current_step, run_state.total_steps, step.label,
                )

                # Apply impairment
                if step.profile:
                    from .._profile_helper import load_and_apply_profile
                    await _apply_profile(defn.interface, step.profile)
                    step_result.profile_applied = step.profile
                elif step.impairment:
                    await tc_manager.apply_impairment(defn.interface, step.impairment)

                # Start capture if requested
                if step.start_capture:
                    from ..models.capture import StartCaptureRequest
                    req = StartCaptureRequest(
                        interface=defn.interface,
                        name=f"{defn.name}-step{i+1}",
                    )
                    cap_info = await capture.start_capture(req)
                    step_result.capture_id = cap_info.id

                # Start logcat if requested
                if step.start_logcat and defn.adb_serial:
                    session = await adb_manager.start_logcat(
                        defn.adb_serial,
                        scenario_id=run_id,
                    )
                    step_result.logcat_session_id = session.id

                # Take screenshot if requested
                if step.take_screenshot and defn.adb_serial:
                    try:
                        path = await adb_manager.screencap(defn.adb_serial)
                        step_result.screenshot_path = path
                    except Exception as e:
                        logger.warning("Screenshot failed: %s", e)

                # Wait for step duration
                try:
                    await asyncio.sleep(step.duration_secs)
                except asyncio.CancelledError:
                    run_state.status = ScenarioStatus.STOPPED
                    raise

                step_result.completed_at = datetime.now(timezone.utc).isoformat()
                run_state.step_results.append(step_result)

                # Stop capture at end of step
                if step_result.capture_id:
                    await capture.stop_capture(step_result.capture_id)

        # All done
        run_state.status = ScenarioStatus.COMPLETED
        run_state.completed_at = datetime.now(timezone.utc).isoformat()

        # Clear impairments
        await tc_manager.clear_impairment(defn.interface)

        logger.info("Scenario %s completed", run_id)

    except asyncio.CancelledError:
        run_state.status = ScenarioStatus.STOPPED
        run_state.completed_at = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        run_state.status = ScenarioStatus.ERROR
        run_state.error = str(e)
        run_state.completed_at = datetime.now(timezone.utc).isoformat()
        logger.error("Scenario %s failed: %s", run_id, e)
    finally:
        _run_tasks.pop(run_id, None)


async def _apply_profile(interface: str, profile_name: str) -> None:
    """Load and apply a named profile."""
    from ..routers.profiles import _load_profile
    try:
        profile = _load_profile(profile_name)
        await tc_manager.apply_impairment(interface, profile.config)
    except Exception as e:
        logger.warning("Failed to apply profile %s: %s", profile_name, e)
