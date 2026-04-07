"""Service-level tests for HTML report generation."""

from pathlib import Path

import pytest

from app.models.scenario import ScenarioRun, ScenarioStatus, ScenarioStepResult
from app.services import report_generator, storage


def _clear_reports() -> None:
    reports_dir = storage.ensure_data_path("reports")
    for report in reports_dir.glob("*.html"):
        report.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def reset_reports_dir():
    _clear_reports()
    yield
    _clear_reports()


def _build_run() -> ScenarioRun:
    return ScenarioRun(
        id="run-001",
        scenario_id="scenario-001",
        scenario_name="Release Confidence",
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
                profile_applied="slow-link",
            ),
        ],
    )


def test_generate_report_includes_steps_and_analysis():
    path = Path(report_generator.generate_report(
        _build_run(),
        capture_analyses=[
            {
                "capture_id": "cap-001",
                "summary": "Retransmissions detected",
                "issues": [{"severity": "high", "description": "Repeated TCP retransmissions"}],
            },
        ],
        stream_metrics={"throughput_ratio": 1.2, "segment_errors": 1},
    ))

    content = path.read_text()

    assert path.exists()
    assert "Release Confidence" in content
    assert "Baseline" in content
    assert "Retransmissions detected" in content
    assert "throughput_ratio" not in content
    assert "Throughput Ratio" in content


def test_list_reports_returns_generated_file():
    path = Path(report_generator.generate_report(_build_run()))
    reports = report_generator.list_reports()

    assert reports
    assert reports[0]["filename"] == path.name
    assert reports[0]["path"] == str(path)
