import { useCallback, useEffect, useState } from 'react';
import type { CaptureFilters, CaptureInfo, PackConfig } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import { useConfirm } from '../hooks/useConfirm';
import { useNotification } from '../hooks/useNotification';
import SessionBadge from './SessionBadge';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '\u2014';
  return new Date(iso).toLocaleString();
}

function formatDuration(startIso: string | null | undefined, stopIso: string | null | undefined): string {
  if (!startIso) return '\u2014';
  const start = new Date(startIso).getTime();
  const end = stopIso ? new Date(stopIso).getTime() : Date.now();
  const secs = Math.round((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  processing: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  stopped: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  error: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

const HEALTH_BADGE: Record<string, { label: string; color: string }> = {
  healthy: { label: 'Healthy', color: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300' },
  degraded: { label: 'Degraded', color: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300' },
  unhealthy: { label: 'Unhealthy', color: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300' },
  insufficient: { label: 'Insufficient', color: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
};

const PACK_ICONS: Record<string, string> = {
  connectivity: '\uD83D\uDCF6',
  dns: '\uD83C\uDF10',
  https: '\uD83D\uDD12',
  streaming: '\u25B6\uFE0F',
  security: '\uD83D\uDEE1\uFE0F',
  custom: '\u2699\uFE0F',
};

const PACK_COLORS: Record<string, string> = {
  connectivity: 'border-blue-400 bg-blue-50 dark:bg-blue-950 hover:border-blue-500',
  dns: 'border-green-400 bg-green-50 dark:bg-green-950 hover:border-green-500',
  https: 'border-purple-400 bg-purple-50 dark:bg-purple-950 hover:border-purple-500',
  streaming: 'border-red-400 bg-red-50 dark:bg-red-950 hover:border-red-500',
  security: 'border-amber-400 bg-amber-50 dark:bg-amber-950 hover:border-amber-500',
  custom: 'border-gray-400 bg-gray-50 dark:bg-gray-800 hover:border-gray-500',
};

export default function CaptureManager({
  onAnalyze,
}: {
  onAnalyze: (captureId: string) => void;
}) {
  const confirmAction = useConfirm();
  const { notify } = useNotification();
  const fetcher = useCallback(() => api.getCaptures(), []);
  const { data: captures, refresh } = useApi<CaptureInfo[]>(fetcher, 3000);

  const [packs, setPacks] = useState<PackConfig[]>([]);
  const [selectedPack, setSelectedPack] = useState<string | null>(null);
  const [iface, setIface] = useState('wlan0');
  const [name, setName] = useState('');
  const [filterBpf, setFilterBpf] = useState('');
  const [maxDuration, setMaxDuration] = useState(60);
  const [starting, setStarting] = useState(false);

  // Load packs
  useEffect(() => {
    api.getPacks().then(setPacks).catch(() => {});
  }, []);

  const activeCaptures = (captures ?? []).filter(c => c.status === 'running' || c.status === 'processing');
  const completedCaptures = (captures ?? []).filter(c => c.status !== 'running' && c.status !== 'processing');

  const handleQuickCapture = async (packId: string) => {
    const pack = packs.find(p => p.id === packId);
    if (!pack) return;

    setStarting(true);
    try {
      await api.startCapture({
        interface: iface,
        name: `${pack.name} - ${new Date().toLocaleTimeString()}`,
        pack: packId,
        max_duration_secs: pack.default_duration_secs,
        max_packets: 100000,
      });
      notify(`${pack.name} capture started`, 'success');
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to start capture', 'error');
    } finally {
      setStarting(false);
    }
  };

  const handleCustomCapture = async () => {
    setStarting(true);
    try {
      const filters: CaptureFilters = {};
      if (filterBpf) filters.custom_bpf = filterBpf;

      await api.startCapture({
        interface: iface,
        name: name || `Custom - ${new Date().toLocaleTimeString()}`,
        pack: 'custom',
        filters,
        max_duration_secs: maxDuration,
        max_packets: 100000,
      });
      setSelectedPack(null);
      setName('');
      setFilterBpf('');
      notify('Custom capture started', 'success');
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to start capture', 'error');
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async (id: string) => {
    try {
      await api.stopCapture(id);
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to stop', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!await confirmAction({ title: 'Delete Capture', message: 'Delete this capture and all associated data?', confirmLabel: 'Delete', confirmTone: 'danger' })) return;
    try {
      await api.deleteCapture(id);
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to delete', 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* ── Zone A: Quick Capture Pack Cards ────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="mb-1 flex items-center gap-3">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Quick Capture</h2>
              <SessionBadge />
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Select an analysis pack to start a pre-configured capture with AI-ready analysis.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">Interface:</label>
            <input
              value={iface}
              onChange={(e) => setIface(e.target.value)}
              className="w-24 rounded border border-gray-300 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-white"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {packs.map((pack) => (
            <button
              key={pack.id}
              onClick={() => {
                if (pack.id === 'custom') {
                  setSelectedPack(selectedPack === 'custom' ? null : 'custom');
                } else {
                  handleQuickCapture(pack.id);
                }
              }}
              disabled={starting}
              className={`group rounded-lg border-2 p-3 text-left transition-all ${PACK_COLORS[pack.id] || PACK_COLORS.custom} disabled:opacity-50`}
            >
              <div className="mb-1 text-xl">{PACK_ICONS[pack.id] || '\u2699\uFE0F'}</div>
              <div className="text-sm font-medium text-gray-900 dark:text-white">{pack.name}</div>
              <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">{pack.description}</div>
              <div className="mt-1 text-xs text-gray-400 dark:text-gray-500">{pack.default_duration_secs}s</div>
            </button>
          ))}
        </div>

        {/* Custom capture form */}
        {selectedPack === 'custom' && (
          <div className="mt-4 space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1 block text-xs text-gray-500">Name (optional)</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="my-capture"
                  className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Duration (seconds)</label>
                <input
                  type="number"
                  value={maxDuration}
                  onChange={(e) => setMaxDuration(Number(e.target.value))}
                  className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">BPF Filter (optional)</label>
                <input
                  value={filterBpf}
                  onChange={(e) => setFilterBpf(e.target.value)}
                  placeholder="tcp port 443"
                  className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCustomCapture}
                disabled={starting}
                className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {starting ? 'Starting...' : 'Start Custom Capture'}
              </button>
              <button
                onClick={() => setSelectedPack(null)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Zone B: Active Captures ────────────────────────────────────── */}
      {activeCaptures.length > 0 && (
        <div className="space-y-3">
          {activeCaptures.map((c) => (
            <div
              key={c.id}
              className="rounded-lg border-2 border-blue-300 bg-blue-50 p-4 dark:border-blue-700 dark:bg-blue-950"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="relative flex h-3 w-3">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75"></span>
                    <span className="relative inline-flex h-3 w-3 rounded-full bg-blue-500"></span>
                  </span>
                  <span className="font-medium text-gray-900 dark:text-white">{c.name}</span>
                  <span className="rounded-full bg-blue-200 px-2 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-800 dark:text-blue-200">
                    {PACK_ICONS[c.pack] || '\u2699\uFE0F'} {c.pack}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.status]}`}>
                    {c.status === 'processing' ? 'Analyzing...' : 'Capturing'}
                  </span>
                </div>
                {c.status === 'running' && (
                  <button
                    onClick={() => handleStop(c.id)}
                    className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700"
                  >
                    Stop
                  </button>
                )}
              </div>
              <div className="mt-2 flex gap-6 text-sm text-gray-600 dark:text-gray-400">
                <span>{formatBytes(c.file_size_bytes)} captured</span>
                <span className="font-mono text-xs">{c.interface}</span>
                {c.bpf_expression && <span className="font-mono text-xs">{c.bpf_expression}</span>}
                <span>{formatDuration(c.started_at, null)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Zone C: Capture History ────────────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
            Capture History ({completedCaptures.length})
          </h2>
          {completedCaptures.length > 0 && (
            <button
              onClick={async () => {
                if (!await confirmAction({ title: 'Delete All Captures', message: `Delete all ${completedCaptures.length} captures?`, confirmLabel: 'Delete All', confirmTone: 'danger' })) return;
                for (const c of completedCaptures) {
                  try { await api.deleteCapture(c.id); } catch { /* ignore */ }
                }
                refresh();
              }}
              className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
            >
              Delete All
            </button>
          )}
        </div>

        <div className="space-y-2">
          {completedCaptures.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-800"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm">{PACK_ICONS[c.pack] || '\u2699\uFE0F'}</span>
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{c.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.status] || ''}`}>
                    {c.status}
                  </span>
                  {c.health_badge && HEALTH_BADGE[c.health_badge] && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${HEALTH_BADGE[c.health_badge].color}`}>
                      {HEALTH_BADGE[c.health_badge].label}
                    </span>
                  )}
                  <span className="rounded bg-gray-200 px-1.5 py-0.5 text-xs text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                    {c.pack}
                  </span>
                </div>
                <div className="mt-0.5 flex gap-3 text-xs text-gray-500 dark:text-gray-400">
                  <span>{c.packet_count.toLocaleString()} packets</span>
                  <span>{formatBytes(c.file_size_bytes)}</span>
                  <span>{formatDuration(c.started_at, c.stopped_at)}</span>
                  <span className="font-mono">{c.interface}</span>
                  {c.bpf_expression && <span className="font-mono">{c.bpf_expression}</span>}
                  <span>{formatTime(c.started_at)}</span>
                </div>
              </div>
              <div className="flex gap-2">
                {c.file_size_bytes > 0 && (
                  <a
                    href={`/api/v1/captures/${c.id}/download`}
                    download={`${c.name || c.id}.pcap`}
                    className="rounded border border-blue-300 px-3 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 dark:border-blue-700 dark:text-blue-400"
                  >
                    Download
                  </a>
                )}
                <button
                  onClick={() => onAnalyze(c.id)}
                  className="rounded bg-purple-600 px-3 py-1 text-xs font-medium text-white hover:bg-purple-700"
                >
                  {c.has_analysis ? 'View Analysis' : 'Analyze'}
                </button>
                <button
                  onClick={() => handleDelete(c.id)}
                  className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
          {completedCaptures.length === 0 && (
            <p className="py-4 text-center text-sm text-gray-500">
              No captures yet. Select a pack above to start one.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
