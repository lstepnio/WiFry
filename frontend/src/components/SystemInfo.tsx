import { useCallback, useState } from 'react';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import type { SystemInfo as SystemInfoType } from '../types';

function RebootButton() {
  const [confirming, setConfirming] = useState(false);
  const [rebooting, setRebooting] = useState(false);

  const handleReboot = async () => {
    setRebooting(true);
    try {
      await fetch('/api/v1/system/reboot', { method: 'POST' });
    } catch { /* expected — connection drops */ }
    // Don't reset state — page will become unreachable
  };

  if (rebooting) {
    return <div className="text-sm text-yellow-400">Rebooting... The device will be back in ~30 seconds.</div>;
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-400">Reboot the RPi?</span>
        <button onClick={handleReboot}
          className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700">
          Yes, Reboot
        </button>
        <button onClick={() => setConfirming(false)}
          className="rounded border border-gray-600 px-3 py-1 text-xs text-gray-400 hover:bg-gray-800">
          Cancel
        </button>
      </div>
    );
  }

  return (
    <button onClick={() => setConfirming(true)}
      className="rounded border border-gray-600 px-4 py-1.5 text-xs font-medium text-gray-400 hover:bg-gray-800 hover:text-white">
      Reboot Device
    </button>
  );
}

export default function SystemInfo() {
  const fetcher = useCallback(() => api.getSystemInfo(), []);
  const { data: info } = useApi<SystemInfoType>(fetcher, 10000);

  if (!info) {
    return <div className="text-sm text-gray-500">Loading system info...</div>;
  }

  const memPct = info.memory_total_mb && info.memory_used_mb
    ? Math.round((info.memory_used_mb / info.memory_total_mb) * 100)
    : null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">System</h2>

      <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Model</div>
          <div className="font-medium text-gray-900 dark:text-white">{info.model}</div>
        </div>

        {info.temperature_c != null && (
          <div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Temperature</div>
            <div className={`font-medium ${info.temperature_c > 70 ? 'text-red-600' : info.temperature_c > 55 ? 'text-yellow-600' : 'text-green-600'}`}>
              {info.temperature_c}°C
            </div>
          </div>
        )}

        {info.load_avg && (
          <div>
            <div className="text-xs text-gray-500 dark:text-gray-400">CPU ({info.cpu_cores} cores)</div>
            <div className={`font-medium ${(info.cpu_usage_pct ?? 0) > 80 ? 'text-red-600' : (info.cpu_usage_pct ?? 0) > 50 ? 'text-yellow-600' : 'text-gray-900 dark:text-white'}`}>
              {info.cpu_usage_pct}% utilization
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
              <div
                className={`h-full rounded-full ${
                  (info.cpu_usage_pct ?? 0) > 80 ? 'bg-red-500' : (info.cpu_usage_pct ?? 0) > 50 ? 'bg-yellow-500' : 'bg-blue-500'
                }`}
                style={{ width: `${Math.min(info.cpu_usage_pct ?? 0, 100)}%` }}
              />
            </div>
            <div className="mt-0.5 text-[10px] text-gray-500">Load: {info.load_avg.join(' / ')}</div>
          </div>
        )}

        {info.memory_total_mb && (
          <div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Memory</div>
            <div className="font-medium text-gray-900 dark:text-white">
              {info.memory_used_mb} / {info.memory_total_mb} MB ({memPct}%)
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
              <div
                className={`h-full rounded-full ${
                  (memPct ?? 0) > 85 ? 'bg-red-500' : (memPct ?? 0) > 60 ? 'bg-yellow-500' : 'bg-green-500'
                }`}
                style={{ width: `${memPct ?? 0}%` }}
              />
            </div>
          </div>
        )}

        {info.uptime && (
          <div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Uptime</div>
            <div className="font-medium text-gray-900 dark:text-white">{info.uptime}</div>
          </div>
        )}

        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Platform</div>
          <div className="text-gray-600 dark:text-gray-400">{info.platform}</div>
        </div>
      </div>

      <div className="mt-4 border-t border-gray-200 pt-4 dark:border-gray-700">
        <RebootButton />
      </div>
    </div>
  );
}
