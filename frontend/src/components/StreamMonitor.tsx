import { useCallback } from 'react';
import type { StreamSessionSummary } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';

function formatBitrate(bps: number): string {
  if (bps >= 1000000) return `${(bps / 1000000).toFixed(1)} Mbps`;
  if (bps >= 1000) return `${(bps / 1000).toFixed(0)} kbps`;
  return `${bps} bps`;
}

function ratioColor(ratio: number): string {
  if (ratio >= 1.33) return 'text-green-500';
  if (ratio >= 1.0) return 'text-yellow-500';
  return 'text-red-500';
}

function bufferColor(secs: number): string {
  if (secs >= 15) return 'bg-green-500';
  if (secs >= 5) return 'bg-yellow-500';
  return 'bg-red-500';
}

export default function StreamMonitor({
  onSelect,
}: {
  onSelect: (id: string) => void;
}) {
  const fetcher = useCallback(() => api.getStreams(), []);
  const { data: streams } = useApi<StreamSessionSummary[]>(fetcher, 3000);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">Active Streams</h2>

      <div className="space-y-3">
        {(streams ?? []).map((s) => (
          <div
            key={s.id}
            onClick={() => onSelect(s.id)}
            className="cursor-pointer rounded-lg border border-gray-100 bg-gray-50 p-4 transition-colors hover:border-blue-300 hover:bg-blue-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-blue-700 dark:hover:bg-blue-950"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${s.stream_type === 'hls' ? 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300' : 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300'}`}>
                  {s.stream_type}
                </span>
                <span className="font-mono text-sm text-gray-600 dark:text-gray-400">{s.client_ip}</span>
                {s.active && (
                  <span className="inline-block h-2 w-2 rounded-full bg-green-500" title="Active" />
                )}
              </div>
              <span className="text-sm font-medium text-gray-900 dark:text-white">
                {s.resolution || '—'} @ {formatBitrate(s.current_bitrate_bps)}
              </span>
            </div>

            <div className="grid grid-cols-5 gap-3 text-center text-xs">
              {/* Throughput ratio */}
              <div>
                <div className="text-gray-500 dark:text-gray-400">Throughput</div>
                <div className={`text-lg font-bold ${ratioColor(s.throughput_ratio)}`}>
                  {s.throughput_ratio > 0 ? `${s.throughput_ratio}x` : '—'}
                </div>
                <div className="text-gray-400">{s.throughput_ratio >= 1.33 ? 'Good' : s.throughput_ratio >= 1.0 ? 'Marginal' : 'Low'}</div>
              </div>

              {/* Buffer */}
              <div>
                <div className="text-gray-500 dark:text-gray-400">Buffer</div>
                <div className="text-lg font-bold text-gray-900 dark:text-white">{s.buffer_health_secs}s</div>
                <div className="mx-auto mt-1 h-1.5 w-12 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                  <div
                    className={`h-full rounded-full ${bufferColor(s.buffer_health_secs)}`}
                    style={{ width: `${Math.min(100, (s.buffer_health_secs / 30) * 100)}%` }}
                  />
                </div>
              </div>

              {/* Bitrate switches */}
              <div>
                <div className="text-gray-500 dark:text-gray-400">Switches</div>
                <div className={`text-lg font-bold ${s.bitrate_switches > 5 ? 'text-yellow-500' : 'text-gray-900 dark:text-white'}`}>
                  {s.bitrate_switches}
                </div>
              </div>

              {/* Segments */}
              <div>
                <div className="text-gray-500 dark:text-gray-400">Segments</div>
                <div className="text-lg font-bold text-gray-900 dark:text-white">{s.total_segments}</div>
              </div>

              {/* Errors */}
              <div>
                <div className="text-gray-500 dark:text-gray-400">Errors</div>
                <div className={`text-lg font-bold ${s.segment_errors > 0 ? 'text-red-500' : 'text-gray-900 dark:text-white'}`}>
                  {s.segment_errors}
                </div>
              </div>
            </div>
          </div>
        ))}

        {(streams ?? []).length === 0 && (
          <div className="py-8 text-center text-gray-500">
            <p className="mb-1 text-lg">No active streams</p>
            <p className="text-sm">Enable the proxy and start streaming on a connected device to see data here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
