"""Regression tests for shared storage resolution and scenario execution."""

from pathlib import Path

from app.config import settings
from app.models.impairment import DelayConfig, ImpairmentConfig
from app.models.profile import Profile
from app.models.scenario import (
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioStep,
    ScenarioStepResult,
    ScenarioRun,
)
from app.models.session import CreateSessionRequest
from app.services import adb_manager, report_generator, scheduler, session_manager, storage


def test_storage_paths_match_mock_service_layout():
    paths = storage.get_data_paths()

    assert paths["captures"] == "/tmp/wifry-captures"
    assert paths["adb_files"] == "/tmp/wifry-adb-files"
    assert paths["reports"] == "/tmp/wifry-reports"
    assert paths["sessions"] == "/tmp/wifry-sessions"
    assert paths["scenarios"] == "/tmp/wifry-scenarios"


async def test_session_manager_uses_storage_sessions_path():
    session = await session_manager.create_session(CreateSessionRequest(name="Storage-Session-Test"))

    session_path = storage.get_data_path("sessions") / f"{session.id}.json"
    assert session_path.exists()

    await session_manager.delete_session(session.id)


async def test_adb_manager_uses_storage_adb_path():
    screenshot_path = Path(await adb_manager.screencap("192.168.4.10:5555"))

    assert screenshot_path.parent == storage.get_data_path("adb_files")
    assert screenshot_path.exists()


def test_report_generator_uses_storage_reports_path():
    run = ScenarioRun(
        id="run-storage-001",
        scenario_id="scenario-storage-001",
        scenario_name="Storage Report",
        status=ScenarioStatus.COMPLETED,
        total_steps=1,
        total_repeats=1,
        started_at="2025-01-01T00:00:00Z",
        completed_at="2025-01-01T00:01:00Z",
        step_results=[
            ScenarioStepResult(
                step_index=1,
                label="Baseline",
                started_at="2025-01-01T00:00:00Z",
                completed_at="2025-01-01T00:01:00Z",
            ),
        ],
    )

    path = Path(report_generator.generate_report(run))

    assert path.parent == storage.get_data_path("reports")
    assert path.exists()

    path.unlink(missing_ok=True)


async def test_scheduler_runs_named_profile_step():
    profile_name = "Scheduler-Profile-Test"
    profile_path = settings.profiles_dir / f"{profile_name}.json"
    profile = Profile(
        name=profile_name,
        category="scenario",
        config=ImpairmentConfig(delay=DelayConfig(ms=50)),
    )
    profile_path.write_text(profile.model_dump_json(indent=2))

    scenario = None
    run = None
    try:
        scenario = scheduler.create_scenario(
            ScenarioDefinition(
                name="Scenario Uses Profile",
                interface="wlan0",
                steps=[ScenarioStep(label="Apply Profile", profile=profile_name, duration_secs=1)],
            )
        )
        run = await scheduler.run_scenario(scenario.id)
        await scheduler._run_tasks[run.id]
        completed = scheduler.get_run(run.id)

        assert completed is not None
        assert completed.status == ScenarioStatus.COMPLETED
        assert completed.step_results[0].profile_applied == profile_name
    finally:
        profile_path.unlink(missing_ok=True)
        if scenario is not None:
            scheduler.delete_scenario(scenario.id)
        if run is not None:
            scheduler._runs.pop(run.id, None)


async def test_scheduler_marks_missing_profile_as_error():
    scenario = None
    run = None
    try:
        scenario = scheduler.create_scenario(
            ScenarioDefinition(
                name="Scenario Missing Profile",
                interface="wlan0",
                steps=[ScenarioStep(label="Missing Profile", profile="does-not-exist", duration_secs=1)],
            )
        )
        run = await scheduler.run_scenario(scenario.id)
        await scheduler._run_tasks[run.id]
        completed = scheduler.get_run(run.id)

        assert completed is not None
        assert completed.status == ScenarioStatus.ERROR
        assert completed.error is not None
        assert "Profile 'does-not-exist'" in completed.error
    finally:
        if scenario is not None:
            scheduler.delete_scenario(scenario.id)
        if run is not None:
            scheduler._runs.pop(run.id, None)
