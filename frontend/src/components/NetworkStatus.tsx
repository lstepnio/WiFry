import { useCallback } from 'react';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import type { ApStatus, InterfaceInfo, WifiClient } from '../types';

export default function NetworkStatus() {
  const ifaceFetcher = useCallback(() => api.getInterfaces(), []);
  const clientFetcher = useCallback(() => api.getClients(), []);
  const apFetcher = useCallback(() => api.getApStatus(), []);

  const { data: interfaces } = useApi<InterfaceInfo[]>(ifaceFetcher, 10000);
  const { data: clients } = useApi<WifiClient[]>(clientFetcher, 5000);
  const { data: apStatus } = useApi<ApStatus>(apFetcher, 10000);

  return (
    <div className="space-y-4">
      {/* AP Status */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">WiFi Access Point</h2>
        {apStatus && (
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Stat label="SSID" value={apStatus.ssid} />
            <Stat label="Channel" value={String(apStatus.channel)} />
            <Stat label="Band" value={apStatus.band} />
            <Stat label="Clients" value={String(apStatus.client_count)} />
          </div>
        )}
      </div>

      {/* Interfaces */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">Interfaces</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-200 text-xs uppercase text-gray-500 dark:border-gray-700">
              <tr>
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">State</th>
                <th className="py-2 pr-4">IPv4</th>
                <th className="py-2">MAC</th>
              </tr>
            </thead>
            <tbody>
              {(interfaces ?? []).map((i) => (
                <tr key={i.name} className="border-b border-gray-100 dark:border-gray-800">
                  <td className="py-2 pr-4 font-mono text-gray-900 dark:text-white">{i.name}</td>
                  <td className="py-2 pr-4 text-gray-600 dark:text-gray-400">{i.type}</td>
                  <td className="py-2 pr-4">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${i.state === 'UP' ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'}`}>
                      {i.state}
                    </span>
                  </td>
                  <td className="py-2 pr-4 font-mono text-gray-600 dark:text-gray-400">{i.ipv4 || '—'}</td>
                  <td className="py-2 font-mono text-xs text-gray-500">{i.mac}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Connected Clients */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">
          Connected Clients ({clients?.length ?? 0})
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-200 text-xs uppercase text-gray-500 dark:border-gray-700">
              <tr>
                <th className="py-2 pr-4">Hostname</th>
                <th className="py-2 pr-4">IP</th>
                <th className="py-2 pr-4">MAC</th>
                <th className="py-2">Signal</th>
              </tr>
            </thead>
            <tbody>
              {(clients ?? []).map((c) => (
                <tr key={c.mac} className="border-b border-gray-100 dark:border-gray-800">
                  <td className="py-2 pr-4 text-gray-900 dark:text-white">{c.hostname || '—'}</td>
                  <td className="py-2 pr-4 font-mono text-gray-600 dark:text-gray-400">{c.ip}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-gray-500">{c.mac}</td>
                  <td className="py-2 text-gray-600 dark:text-gray-400">{c.signal_dbm} dBm</td>
                </tr>
              ))}
              {(clients ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="py-4 text-center text-gray-500">No clients connected</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className="font-medium text-gray-900 dark:text-white">{value}</div>
    </div>
  );
}
