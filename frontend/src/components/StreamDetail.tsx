import { useCallback, useState } from 'react';
import type { StreamSession } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';

function formatBitrate(bps: number): string {
  if (bps >= 1000000) return `${(bps / 1000000).toFixed(1)} Mbps`;
  if (bps >= 1000) return `${(bps / 1000).toFixed(0)} kbps`;
  return `${bps} bps`;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export default function StreamDetail({
  sessionId,
  onBack,
}: {
  sessionId: string;
  onBack: () => void;
}) {
  const fetcher = useCallback(() => api.getStream(sessionId), [sessionId]);
  const { data: session } = useApi<StreamSession>(fetcher, 3000);

  if (!session) return <div className="text-gray-500">Loading...</div>;

  const ratioClass = session.throughput_ratio >= 1.33 ? 'text-green-500' : session.throughput_ratio >= 1.0 ? 'text-yellow-500' : 'text-red-500';

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
        >
          &larr; Back
        </button>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          Stream — {session.client_ip}
        </h2>
        <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${session.stream_type === 'hls' ? 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300' : 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300'}`}>
          {session.stream_type}
        </span>
        <div className="ml-auto flex gap-2">
          <SaveStreamButton sessionId={sessionId} session={session} />
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Throughput Ratio" value={`${session.throughput_ratio}x`} className={ratioClass} subtitle={session.throughput_ratio >= 1.33 ? 'Stable' : 'At risk'} />
        <MetricCard label="Buffer Health" value={`${session.buffer_health_secs}s`} subtitle={session.buffer_health_secs >= 15 ? 'Healthy' : 'Low'} />
        <MetricCard label="Current Bitrate" value={formatBitrate(session.current_bitrate_bps)} subtitle={session.resolution} />
        <MetricCard label="Avg Throughput" value={formatBitrate(session.avg_throughput_bps || 0)} />
      </div>

      {/* Variant ladder */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h3 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">
          Bitrate Ladder ({session.variants.length} variants)
        </h3>
        <div className="space-y-1">
          {session.variants.map((v, i) => {
            const isActive = session.active_variant?.bandwidth === v.bandwidth;
            return (
              <div
                key={i}
                className={`flex items-center justify-between rounded px-3 py-2 text-sm ${isActive ? 'border border-blue-500 bg-blue-50 font-medium dark:bg-blue-950' : 'bg-gray-50 dark:bg-gray-800'}`}
              >
                <div className="flex items-center gap-3">
                  {isActive && <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />}
                  <span className="text-gray-900 dark:text-white">{v.resolution || '—'}</span>
                  <span className="text-gray-500">{v.codecs}</span>
                </div>
                <span className="font-mono text-gray-700 dark:text-gray-300">{formatBitrate(v.bandwidth)}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Segment history */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h3 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">
          Recent Segments ({session.segments.length})
        </h3>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 border-b border-gray-200 bg-white text-gray-500 dark:border-gray-700 dark:bg-gray-900">
              <tr>
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Duration</th>
                <th className="py-2 pr-3">Download</th>
                <th className="py-2 pr-3">Size</th>
                <th className="py-2 pr-3">Throughput</th>
                <th className="py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {session.segments.slice(-50).reverse().map((seg, i) => {
                const slow = seg.duration_secs > 0 && seg.download_time_secs > seg.duration_secs;
                return (
                  <tr key={i} className={`border-b border-gray-100 dark:border-gray-800 ${slow ? 'bg-red-50 dark:bg-red-950' : ''}`}>
                    <td className="py-1.5 pr-3 font-mono text-gray-500">{seg.sequence}</td>
                    <td className="py-1.5 pr-3">{seg.duration_secs.toFixed(1)}s</td>
                    <td className={`py-1.5 pr-3 ${slow ? 'font-bold text-red-600' : ''}`}>
                      {seg.download_time_secs.toFixed(2)}s
                    </td>
                    <td className="py-1.5 pr-3">{formatBytes(seg.size_bytes)}</td>
                    <td className="py-1.5 pr-3 font-mono">{formatBitrate(seg.throughput_bps)}</td>
                    <td className="py-1.5">
                      {seg.status_code >= 400 ? (
                        <span className="text-red-600">{seg.status_code}</span>
                      ) : (
                        <span className="text-green-600">{seg.status_code}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Info */}
      <div className="text-xs text-gray-500">
        Master URL: <span className="font-mono">{session.master_url}</span>
        <br />
        Total segments: {session.total_segments} | Bitrate switches: {session.bitrate_switches} | Errors: {session.segment_errors} | Rebuffers: {session.rebuffer_events ?? 0}
      </div>
    </div>
  );
}

function SaveStreamButton({ session }: { sessionId: string; session: StreamSession }) {
  const [saving, setSaving] = useState(false);

  const saveToSession = async () => {
    setSaving(true);
    try {
      // Save stream data as an artifact to the active test session
      const res = await fetch('/api/v1/sessions/active');
      const active = await res.json();
      if (!active.active_session_id) {
        alert('No active test session. Create one in the Sessions tab first.');
        return;
      }
      await fetch(`/api/v1/sessions/${active.active_session_id}/artifacts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'stream',
          name: `Stream ${session.stream_type.toUpperCase()} — ${session.client_ip} (${session.resolution})`,
          description: `Throughput: ${session.throughput_ratio}x, Switches: ${session.bitrate_switches}, Errors: ${session.segment_errors}`,
          data: {
            stream_type: session.stream_type,
            client_ip: session.client_ip,
            resolution: session.resolution,
            current_bitrate_bps: session.current_bitrate_bps,
            avg_throughput_bps: session.avg_throughput_bps,
            throughput_ratio: session.throughput_ratio,
            buffer_health_secs: session.buffer_health_secs,
            bitrate_switches: session.bitrate_switches,
            segment_errors: session.segment_errors,
            total_segments: session.total_segments,
            master_url: session.master_url,
          },
          tags: ['stream', session.stream_type],
        }),
      });
      alert('Stream data saved to active session');
    } catch { alert('Failed to save'); }
    finally { setSaving(false); }
  };

  const shareStream = async () => {
    setSaving(true);
    try {
      // Create a JSON snapshot and upload via file.io
      const snapshot = JSON.stringify(session, null, 2);
      navigator.clipboard.writeText(snapshot);
      alert('Stream data copied to clipboard (JSON)');
    } catch { alert('Failed'); }
    finally { setSaving(false); }
  };

  return (
    <>
      <button onClick={saveToSession} disabled={saving}
        className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50">
        {saving ? '...' : 'Save to Session'}
      </button>
      <button onClick={shareStream}
        className="rounded bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700">
        Copy JSON
      </button>
    </>
  );
}

function MetricCard({
  label,
  value,
  subtitle,
  className = '',
}: {
  label: string;
  value: string;
  subtitle?: string;
  className?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 text-center shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`text-2xl font-bold ${className || 'text-gray-900 dark:text-white'}`}>{value}</div>
      {subtitle && <div className="text-xs text-gray-400">{subtitle}</div>}
    </div>
  );
}
