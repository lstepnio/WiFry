/**
 * Hardware Validation Panel — runs system readiness, smoke, and integration tests.
 * Shown in System > Tools tab.
 */

import { useState } from 'react';

interface TestResult {
  name: string;
  tier: number;
  category: string;
  status: 'pass' | 'fail' | 'skip';
  message: string;
  duration_ms: number;
}

interface ValidationReport {
  results: TestResult[];
  passed: number;
  failed: number;
  skipped: number;
  duration_ms: number;
}

const TIER_LABELS: Record<number, { name: string; desc: string }> = {
  1: { name: 'System Readiness', desc: 'Binaries, services, permissions, WiFi config' },
  2: { name: 'API Smoke Tests', desc: 'All endpoints respond correctly on real hardware' },
  3: { name: 'Integration', desc: 'Full end-to-end with connected WiFi client' },
};

function StatusBadge({ status }: { status: string }) {
  if (status === 'pass') return <span className="rounded-full bg-green-500/20 px-2 py-0.5 text-xs font-medium text-green-400">PASS</span>;
  if (status === 'fail') return <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-medium text-red-400">FAIL</span>;
  return <span className="rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs font-medium text-yellow-400">SKIP</span>;
}

export default function HwValidationPanel() {
  const [tiers, setTiers] = useState<number[]>([1, 2, 3]);
  const [clientIp, setClientIp] = useState('');
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [error, setError] = useState('');

  const toggleTier = (tier: number) => {
    setTiers(prev => prev.includes(tier) ? prev.filter(t => t !== tier) : [...prev, tier].sort());
  };

  const runTests = async () => {
    setRunning(true);
    setError('');
    setReport(null);
    try {
      const res = await fetch('/api/v1/hw-tests/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tiers,
          client_ip: clientIp || null,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ValidationReport = await res.json();
      setReport(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run tests');
    } finally {
      setRunning(false);
    }
  };

  // Group results by tier
  const grouped = report ? Object.entries(
    report.results.reduce<Record<number, TestResult[]>>((acc, r) => {
      (acc[r.tier] = acc[r.tier] || []).push(r);
      return acc;
    }, {})
  ).sort(([a], [b]) => Number(a) - Number(b)) : [];

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Hardware Validation</h2>
      <p className="mt-1 text-sm text-gray-500">
        Validate the RPi hardware setup, API endpoints, and end-to-end functionality.
      </p>

      {/* Tier selection */}
      <div className="mt-4 flex flex-wrap items-center gap-4">
        {Object.entries(TIER_LABELS).map(([tier, { name, desc }]) => (
          <label key={tier} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={tiers.includes(Number(tier))}
              onChange={() => toggleTier(Number(tier))}
              className="h-4 w-4 accent-blue-600"
            />
            <span className="font-medium text-gray-900 dark:text-white">Tier {tier}: {name}</span>
            <span className="text-xs text-gray-500">({desc})</span>
          </label>
        ))}
      </div>

      {/* Client IP for Tier 3 */}
      {tiers.includes(3) && (
        <div className="mt-3 flex items-center gap-2">
          <label className="text-sm text-gray-600 dark:text-gray-400">Client IP (optional):</label>
          <input
            type="text"
            value={clientIp}
            onChange={e => setClientIp(e.target.value)}
            placeholder="Auto-detect from connected clients"
            className="w-64 rounded border border-gray-300 bg-white px-3 py-1 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />
        </div>
      )}

      {/* Run button */}
      <div className="mt-4">
        <button
          onClick={runTests}
          disabled={running || tiers.length === 0}
          className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? 'Running Tests...' : 'Run Hardware Tests'}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Results */}
      {report && (
        <div className="mt-6">
          {/* Summary bar */}
          <div className="mb-4 flex items-center gap-4 rounded-lg border border-gray-700 bg-gray-800 px-4 py-3">
            <span className="text-sm font-medium text-white">
              {report.passed + report.failed + report.skipped} tests in {(report.duration_ms / 1000).toFixed(1)}s
            </span>
            <span className="text-sm text-green-400">{report.passed} passed</span>
            {report.failed > 0 && <span className="text-sm text-red-400">{report.failed} failed</span>}
            {report.skipped > 0 && <span className="text-sm text-yellow-400">{report.skipped} skipped</span>}
          </div>

          {/* Results by tier */}
          {grouped.map(([tier, results]) => {
            const tierInfo = TIER_LABELS[Number(tier)] || { name: `Tier ${tier}`, desc: '' };
            const tierFailed = results.some(r => r.status === 'fail');
            return (
              <div key={tier} className="mb-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-300">
                  <span className={tierFailed ? 'text-red-400' : 'text-green-400'}>
                    {tierFailed ? '\u2717' : '\u2713'}
                  </span>
                  Tier {tier}: {tierInfo.name}
                </h3>
                <div className="space-y-1">
                  {results.map((r, i) => (
                    <div
                      key={i}
                      className={`flex items-center justify-between rounded px-3 py-1.5 text-sm ${
                        r.status === 'fail'
                          ? 'bg-red-500/5 border border-red-500/20'
                          : 'bg-gray-800/50'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <StatusBadge status={r.status} />
                        <span className="text-gray-300">{r.name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        {r.message && r.status !== 'pass' && (
                          <span className="max-w-md truncate text-xs text-gray-500">{r.message}</span>
                        )}
                        <span className="text-xs text-gray-600">{r.duration_ms.toFixed(0)}ms</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
