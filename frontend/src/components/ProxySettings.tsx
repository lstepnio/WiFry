import { useCallback, useState } from 'react';
import type { ProxyStatus } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import { useNotification } from '../hooks/useNotification';

export default function ProxySettings() {
  const { notify } = useNotification();
  const fetcher = useCallback(() => api.getProxyStatus(), []);
  const { data: status, refresh } = useApi<ProxyStatus>(fetcher, 5000);
  const [toggling, setToggling] = useState(false);

  const handleToggle = async () => {
    setToggling(true);
    try {
      if (status?.enabled) {
        await api.disableProxy();
      } else {
        await api.enableProxy();
      }
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to toggle proxy', 'error');
    } finally {
      setToggling(false);
    }
  };

  const handleSaveSegments = async (enabled: boolean) => {
    await api.updateProxySettings({ save_segments: enabled });
    refresh();
  };

  if (!status) return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">HTTPS Proxy</h2>
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`rounded-lg px-5 py-2 text-sm font-medium text-white disabled:opacity-50 ${
            status.enabled
              ? 'bg-red-600 hover:bg-red-700'
              : 'bg-green-600 hover:bg-green-700'
          }`}
        >
          {toggling ? '...' : status.enabled ? 'Disable Proxy' : 'Enable Proxy'}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Status</div>
          <div className={`font-medium ${status.running ? 'text-green-600' : 'text-gray-500'}`}>
            {status.running ? 'Running' : 'Stopped'}
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Port</div>
          <div className="font-mono font-medium text-gray-900 dark:text-white">{status.port}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Intercepted Flows</div>
          <div className="font-medium text-gray-900 dark:text-white">{status.intercepted_flows}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Segment Save</div>
          <label className="mt-1 flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={status.save_segments}
              onChange={(e) => handleSaveSegments(e.target.checked)}
              className="h-4 w-4 rounded accent-blue-600"
            />
            <span className="text-gray-700 dark:text-gray-300">{status.save_segments ? 'On' : 'Off'}</span>
          </label>
        </div>
      </div>

      {/* Certificate download */}
      <div className="mt-4 rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-950">
        <div className="text-sm font-medium text-yellow-800 dark:text-yellow-200">CA Certificate</div>
        <p className="mt-1 text-xs text-yellow-700 dark:text-yellow-300">
          To inspect HTTPS traffic, install the WiFry CA certificate on your STB/device.
        </p>
        <a
          href="/api/v1/proxy/cert"
          download="wifry-ca-cert.pem"
          className="mt-2 inline-block rounded bg-yellow-600 px-3 py-1 text-xs font-medium text-white hover:bg-yellow-700"
        >
          Download Certificate
        </a>
      </div>
    </div>
  );
}
