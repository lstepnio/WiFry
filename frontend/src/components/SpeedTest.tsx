import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';

interface SpeedResult {
  id: string;
  type?: string;
  target?: string;
  started_at: string;
  duration_secs?: number;
  download_mbps: number;
  upload_mbps: number;
  ping_ms?: number;
  jitter_ms: number;
  packet_loss_pct: number;
  retransmits?: number;
  server_name?: string;
  server_location?: string;
  isp?: string;
  result_url?: string;
  error?: string;
}

export default function SpeedTest() {
  const [target, setTarget] = useState('127.0.0.1');
  const [duration, setDuration] = useState(10);
  const [running, setRunning] = useState<string | null>(null);

  const fetcher = useCallback(async () => {
    const res = await fetch('/api/v1/speedtest/results');
    return res.ok ? res.json() : [];
  }, []);
  const { data: results, refresh } = useApi<SpeedResult[]>(fetcher);

  const runIperf = async () => {
    setRunning('iperf');
    try {
      const params = new URLSearchParams({ target, duration: String(duration) });
      await fetch(`/api/v1/speedtest/run?${params}`, { method: 'POST' });
      refresh();
    } catch { alert('iperf3 test failed'); }
    finally { setRunning(null); }
  };

  const runOokla = async () => {
    setRunning('ookla');
    try {
      await fetch('/api/v1/speedtest/ookla', { method: 'POST' });
      refresh();
    } catch { alert('Ookla test failed'); }
    finally { setRunning(null); }
  };

  const deleteResult = async (id: string) => {
    await fetch(`/api/v1/speedtest/results/${id}`, { method: 'DELETE' });
    refresh();
  };

  const deleteAll = async () => {
    if (!confirm(`Delete all ${(results ?? []).length} result(s)?`)) return;
    await fetch('/api/v1/speedtest/results', { method: 'DELETE' });
    refresh();
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Speed Test</h2>
        {(results ?? []).length > 0 && (
          <button onClick={deleteAll}
            className="rounded-lg border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400">
            Delete All
          </button>
        )}
      </div>
      <p className="mb-4 text-xs text-gray-500">Measure throughput through the impairment path (iperf3) or real internet speed (Ookla). Results are saved automatically.</p>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <button onClick={runOokla} disabled={running !== null}
          className="rounded-lg bg-purple-600 px-5 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50">
          {running === 'ookla' ? 'Testing...' : 'Ookla Internet Speed'}
        </button>

        <div className="flex items-end gap-2">
          <div>
            <label className="mb-1 block text-xs text-gray-500">iperf3 Target</label>
            <input value={target} onChange={(e) => setTarget(e.target.value)}
              className="w-36 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">Duration</label>
            <input type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value))} min={1} max={60}
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
          </div>
          <button onClick={runIperf} disabled={running !== null}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50">
            {running === 'iperf' ? 'Testing...' : 'Run iperf3'}
          </button>
        </div>
      </div>

      {/* Results */}
      {(results ?? []).length > 0 && (
        <div className="space-y-3">
          {(results ?? []).map((r) => (
            <div key={r.id} className="rounded-lg border border-gray-100 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800">
              {r.error ? (
                <div className="flex items-center justify-between">
                  <div className="text-sm text-red-500">{r.error}</div>
                  <button onClick={() => deleteResult(r.id)}
                    className="rounded border border-red-300 px-2 py-0.5 text-[10px] text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400">
                    Delete
                  </button>
                </div>
              ) : (
                <>
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase ${r.type === 'ookla' ? 'bg-purple-900 text-purple-300' : 'bg-green-900 text-green-300'}`}>
                        {r.type === 'ookla' ? 'Ookla' : 'iperf3'}
                      </span>
                      {r.server_name && <span className="text-xs text-gray-400">{r.server_name}</span>}
                      {r.isp && <span className="text-xs text-gray-500">({r.isp})</span>}
                      {r.target && r.type !== 'ookla' && <span className="font-mono text-xs text-gray-500">{r.target}</span>}
                    </div>
                    <button onClick={() => deleteResult(r.id)}
                      className="rounded border border-red-300 px-2 py-0.5 text-[10px] text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400">
                      Delete
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-center sm:grid-cols-6">
                    <div>
                      <div className="text-2xl font-bold text-green-500">{r.download_mbps}</div>
                      <div className="text-[10px] uppercase text-gray-500">Download Mbps</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-blue-500">{r.upload_mbps}</div>
                      <div className="text-[10px] uppercase text-gray-500">Upload Mbps</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-gray-900 dark:text-white">{r.ping_ms ?? r.jitter_ms}</div>
                      <div className="text-[10px] uppercase text-gray-500">{r.ping_ms != null ? 'Ping ms' : 'Jitter ms'}</div>
                    </div>
                    <div>
                      <div className={`text-2xl font-bold ${r.packet_loss_pct > 0.1 ? 'text-red-500' : 'text-gray-900 dark:text-white'}`}>{r.packet_loss_pct}%</div>
                      <div className="text-[10px] uppercase text-gray-500">Loss</div>
                    </div>
                    {r.retransmits != null && (
                      <div>
                        <div className={`text-2xl font-bold ${(r.retransmits ?? 0) > 10 ? 'text-yellow-500' : 'text-gray-900 dark:text-white'}`}>{r.retransmits}</div>
                        <div className="text-[10px] uppercase text-gray-500">Retransmits</div>
                      </div>
                    )}
                    {r.jitter_ms != null && r.ping_ms != null && (
                      <div>
                        <div className="text-2xl font-bold text-gray-900 dark:text-white">{r.jitter_ms}</div>
                        <div className="text-[10px] uppercase text-gray-500">Jitter ms</div>
                      </div>
                    )}
                  </div>
                  {r.result_url && (
                    <div className="mt-2 text-xs">
                      <a href={r.result_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 underline hover:text-blue-300">
                        View on Speedtest.net &rarr;
                      </a>
                    </div>
                  )}
                </>
              )}
              <div className="mt-1 text-xs text-gray-500">{new Date(r.started_at).toLocaleString()}</div>
            </div>
          ))}
        </div>
      )}

      {(results ?? []).length === 0 && (
        <p className="py-4 text-center text-sm text-gray-500">
          Run Ookla for internet speed or iperf3 for LAN throughput through the impairment path.
        </p>
      )}
    </div>
  );
}
