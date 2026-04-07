"""Test report generator.

Produces HTML reports combining impairment timelines, stream metrics,
capture analysis, ADB logcat excerpts, and screenshots.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..models.scenario import ScenarioRun
from . import storage

logger = logging.getLogger(__name__)

REPORTS_DIR = storage.get_data_path("reports")


def _ensure_dir() -> Path:
    global REPORTS_DIR
    REPORTS_DIR = storage.ensure_data_path("reports")
    return REPORTS_DIR


def generate_report(
    run: ScenarioRun,
    capture_analyses: Optional[List[dict]] = None,
    logcat_excerpts: Optional[List[dict]] = None,
    stream_metrics: Optional[dict] = None,
) -> str:
    """Generate an HTML test report. Returns the file path."""
    d = _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{run.scenario_name.replace(' ', '_')}_{ts}.html"
    path = d / filename

    html = _render_html(run, capture_analyses or [], logcat_excerpts or [], stream_metrics or {})
    path.write_text(html)

    logger.info("Report generated: %s", path)
    return str(path)


def list_reports() -> List[dict]:
    """List generated reports."""
    d = _ensure_dir()
    reports = []
    for f in sorted(d.glob("*.html"), reverse=True):
        reports.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return reports


def _render_html(
    run: ScenarioRun,
    analyses: List[dict],
    logcat_excerpts: List[dict],
    stream_metrics: dict,
) -> str:
    """Render the full HTML report."""

    steps_html = ""
    for step in run.step_results:
        status_class = "step-complete"
        steps_html += f"""
        <div class="step {status_class}">
            <div class="step-header">
                <span class="step-num">Step {step.step_index}</span>
                <strong>{step.label}</strong>
                {f'<span class="badge">Profile: {step.profile_applied}</span>' if step.profile_applied else ''}
            </div>
            <div class="step-meta">
                {step.started_at} &mdash; {step.completed_at}
                {f' | Capture: {step.capture_id}' if step.capture_id else ''}
                {f' | Logcat: {step.logcat_session_id}' if step.logcat_session_id else ''}
            </div>
        </div>"""

    analyses_html = ""
    for a in analyses:
        issues = a.get("issues", [])
        issues_items = "".join(
            f'<li class="issue-{i.get("severity", "low")}"><strong>[{i.get("severity", "").upper()}]</strong> {i.get("description", "")}</li>'
            for i in issues
        )
        analyses_html += f"""
        <div class="analysis-card">
            <h3>Capture Analysis: {a.get('capture_id', 'N/A')}</h3>
            <p>{a.get('summary', '')}</p>
            <ul>{issues_items}</ul>
        </div>"""

    logcat_html = ""
    for excerpt in logcat_excerpts:
        lines = excerpt.get("lines", [])
        lines_text = "\n".join(l.get("raw", "") for l in lines[:50])
        logcat_html += f"""
        <div class="logcat-card">
            <h3>Logcat: {excerpt.get('serial', 'N/A')} (session {excerpt.get('session_id', '')})</h3>
            <pre>{lines_text}</pre>
        </div>"""

    stream_html = ""
    if stream_metrics:
        stream_html = f"""
        <div class="metrics-card">
            <h3>Stream Metrics</h3>
            <table>
                <tr><td>Throughput Ratio</td><td>{stream_metrics.get('throughput_ratio', 'N/A')}</td></tr>
                <tr><td>Buffer Health</td><td>{stream_metrics.get('buffer_health_secs', 'N/A')}s</td></tr>
                <tr><td>Bitrate Switches</td><td>{stream_metrics.get('bitrate_switches', 'N/A')}</td></tr>
                <tr><td>Segment Errors</td><td>{stream_metrics.get('segment_errors', 'N/A')}</td></tr>
                <tr><td>Rebuffer Events</td><td>{stream_metrics.get('rebuffer_events', 'N/A')}</td></tr>
            </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WiFry Test Report &mdash; {run.scenario_name}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e5e7eb; padding: 2rem; line-height: 1.6; }}
  h1 {{ color: #60a5fa; margin-bottom: 0.5rem; }}
  h2 {{ color: #93c5fd; margin: 2rem 0 1rem; border-bottom: 1px solid #374151; padding-bottom: 0.5rem; }}
  h3 {{ color: #d1d5db; margin-bottom: 0.5rem; }}
  .header {{ margin-bottom: 2rem; }}
  .header p {{ color: #9ca3af; }}
  .badge {{ display: inline-block; background: #1e3a5f; color: #93c5fd; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-left: 0.5rem; }}
  .status {{ display: inline-block; padding: 4px 12px; border-radius: 6px; font-weight: 600; font-size: 0.85rem; }}
  .status-completed {{ background: #065f46; color: #6ee7b7; }}
  .status-stopped {{ background: #78350f; color: #fcd34d; }}
  .status-error {{ background: #7f1d1d; color: #fca5a5; }}
  .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .summary-card {{ background: #1f2937; border-radius: 8px; padding: 1rem; text-align: center; }}
  .summary-card .value {{ font-size: 1.5rem; font-weight: 700; color: #fff; }}
  .summary-card .label {{ font-size: 0.75rem; color: #9ca3af; text-transform: uppercase; }}
  .step {{ background: #1f2937; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem; border-left: 4px solid #3b82f6; }}
  .step-header {{ font-size: 0.95rem; }}
  .step-num {{ color: #60a5fa; margin-right: 0.5rem; }}
  .step-meta {{ font-size: 0.75rem; color: #6b7280; margin-top: 0.25rem; }}
  .analysis-card, .logcat-card, .metrics-card {{ background: #1f2937; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; }}
  .analysis-card ul {{ padding-left: 1.5rem; }}
  .issue-critical, .issue-high {{ color: #fca5a5; }}
  .issue-medium {{ color: #fcd34d; }}
  .issue-low {{ color: #6ee7b7; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 0.5rem; border-bottom: 1px solid #374151; }}
  td:first-child {{ color: #9ca3af; width: 200px; }}
  pre {{ background: #111827; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.75rem; color: #d1d5db; max-height: 300px; }}
  .footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #374151; font-size: 0.75rem; color: #6b7280; }}
</style>
</head>
<body>
<div class="header">
    <h1>WiFry Test Report</h1>
    <p><strong>{run.scenario_name}</strong> &mdash;
    <span class="status status-{run.status.value}">{run.status.value.upper()}</span></p>
    <p>Run ID: {run.id} | Started: {run.started_at} | Completed: {run.completed_at}</p>
</div>

<div class="summary">
    <div class="summary-card"><div class="value">{run.total_steps}</div><div class="label">Total Steps</div></div>
    <div class="summary-card"><div class="value">{len(run.step_results)}</div><div class="label">Completed</div></div>
    <div class="summary-card"><div class="value">{run.total_repeats}</div><div class="label">Repeats</div></div>
    <div class="summary-card"><div class="value">{run.status.value}</div><div class="label">Status</div></div>
</div>

<h2>Scenario Steps</h2>
{steps_html}

{f'<h2>Stream Metrics</h2>{stream_html}' if stream_html else ''}
{f'<h2>Capture Analysis</h2>{analyses_html}' if analyses_html else ''}
{f'<h2>ADB Logcat</h2>{logcat_html}' if logcat_html else ''}

<div class="footer">
    Generated by WiFry &mdash; {datetime.now(timezone.utc).isoformat()}
</div>
</body>
</html>"""
