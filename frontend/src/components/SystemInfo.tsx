import { useCallback } from 'react';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import type { SystemInfo as SystemInfoType } from '../types';

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
    </div>
  );
}
