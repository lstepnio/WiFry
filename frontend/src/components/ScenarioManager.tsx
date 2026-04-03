import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';

interface ScenarioStep {
  label: string;
  profile?: string;
  duration_secs: number;
  start_capture: boolean;
  start_logcat: boolean;
  take_screenshot: boolean;
}

interface ScenarioDefinition {
  id: string;
  name: string;
  description: string;
  interface: string;
  adb_serial: string;
  repeat: number;
  steps: ScenarioStep[];
}

interface ScenarioRun {
  id: string;
  scenario_id: string;
  scenario_name: string;
  status: string;
  current_step: number;
  total_steps: number;
  started_at: string;
  completed_at: string;
}

const PRESET_SCENARIOS: Omit<ScenarioDefinition, 'id'>[] = [
  {
    name: "Network Degradation Soak",
    description: "Cycles through network conditions to test STB resilience",
    interface: "wlan0",
    adb_serial: "",
    repeat: 3,
    steps: [
      { label: "Baseline", profile: "Good WiFi", duration_secs: 120, start_capture: true, start_logcat: true, take_screenshot: true },
      { label: "Degradation", profile: "Poor WiFi", duration_secs: 60, start_capture: false, start_logcat: false, take_screenshot: true },
      { label: "Severe", profile: "Worst Case", duration_secs: 30, start_capture: false, start_logcat: false, take_screenshot: true },
      { label: "Recovery", profile: "Good WiFi", duration_secs: 120, start_capture: false, start_logcat: false, take_screenshot: true },
    ],
  },
  {
    name: "Satellite Simulation",
    description: "Tests high-latency satellite-like conditions",
    interface: "wlan0",
    adb_serial: "",
    repeat: 1,
    steps: [
      { label: "Normal", profile: "Good WiFi", duration_secs: 60, start_capture: true, start_logcat: true, take_screenshot: false },
      { label: "Satellite", profile: "Satellite", duration_secs: 300, start_capture: false, start_logcat: false, take_screenshot: true },
      { label: "Recovery", profile: "Good WiFi", duration_secs: 60, start_capture: false, start_logcat: false, take_screenshot: true },
    ],
  },
  {
    name: "Mobile Network Transition",
    description: "Simulates moving from WiFi to 4G to 3G",
    interface: "wlan0",
    adb_serial: "",
    repeat: 1,
    steps: [
      { label: "WiFi", profile: "Good WiFi", duration_secs: 60, start_capture: true, start_logcat: true, take_screenshot: false },
      { label: "4G", profile: "4G Mobile", duration_secs: 120, start_capture: false, start_logcat: false, take_screenshot: true },
      { label: "3G", profile: "3G Mobile", duration_secs: 120, start_capture: false, start_logcat: false, take_screenshot: true },
      { label: "Recovery", profile: "Good WiFi", duration_secs: 60, start_capture: false, start_logcat: false, take_screenshot: true },
    ],
  },
];

export default function ScenarioManager() {
  const scenarioFetcher = useCallback(async () => {
    const res = await fetch('/api/v1/scenarios');
    return res.json();
  }, []);
  const { data: scenarios, refresh: refreshScenarios } = useApi<ScenarioDefinition[]>(scenarioFetcher);

  const runsFetcher = useCallback(async () => {
    const res = await fetch('/api/v1/scenarios/runs');
    return res.json();
  }, []);
  const { data: runs, refresh: refreshRuns } = useApi<ScenarioRun[]>(runsFetcher, 3000);

  const [creating, setCreating] = useState(false);

  const createPreset = async (preset: Omit<ScenarioDefinition, 'id'>) => {
    setCreating(true);
    try {
      await fetch('/api/v1/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(preset),
      });
      refreshScenarios();
    } catch (e) {
      alert('Failed to create scenario');
    } finally {
      setCreating(false);
    }
  };

  const runScenario = async (id: string) => {
    await fetch(`/api/v1/scenarios/${id}/run`, { method: 'POST' });
    refreshRuns();
  };

  const stopRun = async (runId: string) => {
    await fetch(`/api/v1/scenarios/runs/${runId}/stop`, { method: 'POST' });
    refreshRuns();
  };

  const generateReport = async (runId: string) => {
    const res = await fetch(`/api/v1/reports/generate?run_id=${runId}`, { method: 'POST' });
    const data = await res.json();
    if (data.path) {
      alert(`Report generated: ${data.path}`);
    }
  };

  const STATUS_COLORS: Record<string, string> = {
    running: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
    completed: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
    stopped: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
    error: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  };

  return (
    <div className="space-y-4">
      {/* Saved scenarios */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">Test Scenarios</h2>

        {(scenarios ?? []).length === 0 && (
          <div className="mb-4">
            <p className="mb-3 text-sm text-gray-500">No scenarios yet. Create one from a preset:</p>
            <div className="flex flex-wrap gap-2">
              {PRESET_SCENARIOS.map((p, i) => (
                <button
                  key={i}
                  onClick={() => createPreset(p)}
                  disabled={creating}
                  className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-300"
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {(scenarios ?? []).map((s) => (
          <div key={s.id} className="mb-2 rounded-lg border border-gray-100 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-white">{s.name}</div>
                <div className="text-xs text-gray-500">{s.description} &mdash; {s.steps.length} steps, {s.repeat}x repeat</div>
              </div>
              <button
                onClick={() => runScenario(s.id)}
                className="rounded bg-green-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-green-700"
              >
                Run
              </button>
            </div>
            <div className="mt-2 flex gap-1">
              {s.steps.map((step, i) => (
                <div key={i} className="rounded bg-gray-200 px-2 py-0.5 text-[10px] text-gray-600 dark:bg-gray-700 dark:text-gray-400" title={`${step.duration_secs}s`}>
                  {step.label || step.profile || `Step ${i+1}`}
                </div>
              ))}
            </div>
          </div>
        ))}

        {(scenarios ?? []).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {PRESET_SCENARIOS.map((p, i) => (
              <button
                key={i}
                onClick={() => createPreset(p)}
                disabled={creating}
                className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400"
              >
                + {p.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Recent runs */}
      {(runs ?? []).length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">Recent Runs</h2>
          <div className="space-y-2">
            {(runs ?? []).map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900 dark:text-white">{r.scenario_name}</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[r.status] || ''}`}>{r.status}</span>
                  </div>
                  <div className="text-xs text-gray-500">
                    Step {r.current_step}/{r.total_steps} &mdash; {new Date(r.started_at).toLocaleString()}
                  </div>
                </div>
                <div className="flex gap-2">
                  {r.status === 'running' && (
                    <button onClick={() => stopRun(r.id)} className="rounded border border-yellow-300 px-3 py-1 text-xs text-yellow-600 hover:bg-yellow-50 dark:border-yellow-700 dark:text-yellow-400">Stop</button>
                  )}
                  {(r.status === 'completed' || r.status === 'stopped') && (
                    <button onClick={() => generateReport(r.id)} className="rounded bg-purple-600 px-3 py-1 text-xs font-medium text-white hover:bg-purple-700">Report</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
