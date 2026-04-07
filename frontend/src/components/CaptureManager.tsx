import { useCallback, useState } from 'react';
import type { CaptureFilters, CaptureInfo } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  stopped: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  error: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

export default function CaptureManager({
  onAnalyze,
}: {
  onAnalyze: (captureId: string) => void;
}) {
  const fetcher = useCallback(() => api.getCaptures(), []);
  const { data: captures, refresh } = useApi<CaptureInfo[]>(fetcher, 3000);

  const [showNew, setShowNew] = useState(false);
  const [iface, setIface] = useState('wlan0');
  const [name, setName] = useState('');
  const [filterHost, setFilterHost] = useState('');
  const [filterPort, setFilterPort] = useState('');
  const [filterProto, setFilterProto] = useState('');
  const [filterBpf, setFilterBpf] = useState('');
  const [maxPackets, setMaxPackets] = useState(10000);
  const [maxDuration, setMaxDuration] = useState(300);
  const [starting, setStarting] = useState(false);

  const handleStart = async () => {
    setStarting(true);
    try {
      const filters: CaptureFilters = {};
      if (filterHost) filters.host = filterHost;
      if (filterPort) filters.port = parseInt(filterPort);
      if (filterProto) filters.protocol = filterProto;
      if (filterBpf) filters.custom_bpf = filterBpf;

      await api.startCapture({
        interface: iface,
        name: name || undefined,
        filters,
        max_packets: maxPackets,
        max_duration_secs: maxDuration,
      });
      setShowNew(false);
      setName('');
      setFilterHost('');
      setFilterPort('');
      setFilterProto('');
      setFilterBpf('');
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to start capture');
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async (id: string) => {
    try {
      await api.stopCapture(id);
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to stop');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this capture?')) return;
    try {
      await api.deleteCapture(id);
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to delete');
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Packet Captures</h2>
          <p className="text-xs text-gray-500">Capture network traffic with tshark. Use filters to scope captures. Click Analyze to run AI-powered analysis on completed captures.</p>
        </div>
        <div className="flex gap-2">
          {(captures ?? []).length > 0 && (
            <button
              onClick={async () => {
                if (!confirm(`Delete all ${(captures ?? []).length} captures?`)) return;
                for (const c of (captures ?? [])) {
                  try { await api.deleteCapture(c.id); } catch {}
                }
                refresh();
              }}
              className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
            >
              Delete All
            </button>
          )}
          <button
            onClick={() => setShowNew(!showNew)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            {showNew ? 'Cancel' : 'New Capture'}
          </button>
        </div>
      </div>

      {/* New capture form */}
      {showNew && (
        <div className="mb-6 space-y-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-gray-600 dark:text-gray-400">Interface</label>
              <input
                value={iface}
                onChange={(e) => setIface(e.target.value)}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-600 dark:text-gray-400">Name (optional)</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-capture"
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
          </div>

          <div className="text-xs font-medium text-gray-600 dark:text-gray-400">Filters</div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Host IP</label>
              <input
                value={filterHost}
                onChange={(e) => setFilterHost(e.target.value)}
                placeholder="192.168.4.10"
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Port</label>
              <input
                value={filterPort}
                onChange={(e) => setFilterPort(e.target.value)}
                placeholder="443"
                type="number"
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Protocol</label>
              <select
                value={filterProto}
                onChange={(e) => setFilterProto(e.target.value)}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              >
                <option value="">Any</option>
                <option value="tcp">TCP</option>
                <option value="udp">UDP</option>
                <option value="icmp">ICMP</option>
              </select>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs text-gray-500">Custom BPF (advanced)</label>
            <input
              value={filterBpf}
              onChange={(e) => setFilterBpf(e.target.value)}
              placeholder="tcp port 443 and host 192.168.4.10"
              className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Max packets</label>
              <input
                type="number"
                value={maxPackets}
                onChange={(e) => setMaxPackets(Number(e.target.value))}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Max duration (seconds)</label>
              <input
                type="number"
                value={maxDuration}
                onChange={(e) => setMaxDuration(Number(e.target.value))}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
          </div>

          <button
            onClick={handleStart}
            disabled={starting}
            className="rounded-lg bg-green-600 px-6 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {starting ? 'Starting...' : 'Start Capture'}
          </button>
        </div>
      )}

      {/* Capture list */}
      <div className="space-y-2">
        {(captures ?? []).map((c) => (
          <div
            key={c.id}
            className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-800"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {c.name}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.status] || ''}`}>
                  {c.status}
                </span>
                <span className="font-mono text-xs text-gray-500">{c.interface}</span>
              </div>
              <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                {c.status === 'running' ? (
                  <>{formatBytes(c.file_size_bytes)} captured</>
                ) : (
                  <>{c.packet_count} packets &middot; {formatBytes(c.file_size_bytes)}</>
                )}
                {c.bpf_expression && (
                  <> &middot; <span className="font-mono">{c.bpf_expression}</span></>
                )}
                &middot; {formatTime(c.started_at)}
              </div>
            </div>
            <div className="flex gap-2">
              {c.status === 'running' && (
                <button
                  onClick={() => handleStop(c.id)}
                  className="rounded border border-yellow-300 px-3 py-1 text-xs font-medium text-yellow-600 hover:bg-yellow-50 dark:border-yellow-700 dark:text-yellow-400"
                >
                  Stop
                </button>
              )}
              {c.status !== 'running' && c.file_size_bytes > 0 && (
                <a
                  href={`/api/v1/captures/${c.id}/download`}
                  download={`${c.name || c.id}.pcap`}
                  className="rounded border border-blue-300 px-3 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 dark:border-blue-700 dark:text-blue-400"
                >
                  Download
                </a>
              )}
              {c.status !== 'running' && (
                <button
                  onClick={() => onAnalyze(c.id)}
                  className="rounded bg-purple-600 px-3 py-1 text-xs font-medium text-white hover:bg-purple-700"
                >
                  Analyze
                </button>
              )}
              {c.status !== 'running' && (
                <button
                  onClick={() => handleDelete(c.id)}
                  className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
                >
                  Delete
                </button>
              )}
            </div>
          </div>
        ))}
        {(captures ?? []).length === 0 && !showNew && (
          <p className="py-4 text-center text-sm text-gray-500">
            No captures yet. Click "New Capture" to start one.
          </p>
        )}
      </div>
    </div>
  );
}
