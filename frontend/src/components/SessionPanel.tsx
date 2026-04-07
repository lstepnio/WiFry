import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useFeatureFlags } from '../hooks/useFeatureFlags';

interface SessionSummary {
  id: string;
  name: string;
  status: string;
  device_model: string;
  device_ip: string;
  tags: string[];
  artifact_count: number;
  created_at: string;
  updated_at: string;
}

interface Artifact {
  id: string;
  session_id: string;
  type: string;
  name: string;
  description: string;
  file_path: string | null;
  tags: string[];
  created_at: string;
  size_bytes: number;
}

interface SessionDetail {
  id: string;
  name: string;
  description: string;
  status: string;
  tags: string[];
  notes: string;
  device: { serial: string; model: string; manufacturer: string; android_version: string; ip_address: string };
  impairment_log: { timestamp: string; label: string; profile_name: string }[];
  artifact_count: number;
  total_size_bytes: number;
  created_at: string;
  completed_at: string;
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  completed: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  archived: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
};

const ARTIFACT_ICONS: Record<string, string> = {
  capture: 'pcap',
  analysis: 'AI',
  logcat: 'log',
  screenshot: 'img',
  bugreport: 'bug',
  stream: 'stream',
  speed_test: 'iperf',
  note: 'note',
  report: 'report',
  impairment_log: 'imp',
};

function formatBytes(b: number): string {
  if (b >= 1048576) return `${(b / 1048576).toFixed(1)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

export default function SessionPanel() {
  const { isEnabled } = useFeatureFlags();
  const listFetcher = useCallback(async () => {
    const res = await fetch('/api/v1/sessions');
    return res.json();
  }, []);
  const { data: sessions, refresh } = useApi<SessionSummary[]>(listFetcher, 5000);

  const activeFetcher = useCallback(async () => {
    const res = await fetch('/api/v1/sessions/active');
    return res.json();
  }, []);
  const { data: activeInfo, refresh: refreshActive } = useApi<{ active_session_id: string | null }>(activeFetcher, 5000);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTags, setNewTags] = useState('');
  const [newDeviceSerial, setNewDeviceSerial] = useState('');
  const [sharing, setSharing] = useState(false);
  const [shareResult, setShareResult] = useState<{ link?: string; error?: string } | null>(null);
  const bundleSharingEnabled = isEnabled('sharing_fileio');

  const loadDetail = async (id: string) => {
    setSelectedId(id);
    const [dRes, aRes] = await Promise.all([
      fetch(`/api/v1/sessions/${id}`),
      fetch(`/api/v1/sessions/${id}/artifacts`),
    ]);
    setDetail(await dRes.json());
    setArtifacts(await aRes.json());
  };

  const createSession = async () => {
    if (!newName) return;
    setCreating(true);
    try {
      await fetch('/api/v1/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newName,
          tags: newTags ? newTags.split(',').map(t => t.trim()) : [],
          device_serial: newDeviceSerial || '',
        }),
      });
      setNewName('');
      setNewTags('');
      setNewDeviceSerial('');
      refresh();
      refreshActive();
    } catch { alert('Failed to create session'); }
    finally { setCreating(false); }
  };

  const completeSession = async (id: string) => {
    await fetch(`/api/v1/sessions/${id}/complete`, { method: 'POST' });
    refresh();
    refreshActive();
    if (selectedId === id) loadDetail(id);
  };

  const activateSession = async (id: string) => {
    await fetch(`/api/v1/sessions/${id}/activate`, { method: 'POST' });
    refreshActive();
  };

  const generateAndShare = async (id: string) => {
    setSharing(true);
    setShareResult(null);
    try {
      const res = await fetch(`/api/v1/sessions/${id}/bundle/share?expires=15m`, { method: 'POST' });
      const data = await res.json();
      setShareResult(data.upload || { error: 'Failed' });
    } catch { setShareResult({ error: 'Upload failed' }); }
    finally { setSharing(false); }
  };

  const generateBundle = async (id: string) => {
    const res = await fetch(`/api/v1/sessions/${id}/bundle`, { method: 'POST' });
    const data = await res.json();
    if (data.bundle_path) alert(`Bundle saved: ${data.bundle_path}`);
    if (selectedId === id) loadDetail(id);
  };

  // Detail view
  if (selectedId && detail) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <button onClick={() => { setSelectedId(null); setDetail(null); }}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800">
            &larr; Back
          </button>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{detail.name}</h2>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[detail.status] || ''}`}>{detail.status}</span>
          {activeInfo?.active_session_id === detail.id && (
            <span className="rounded-full bg-green-600 px-2 py-0.5 text-xs font-bold text-white">ACTIVE</span>
          )}
        </div>

        {/* Session info */}
        <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            {detail.device.model && <div><div className="text-xs text-gray-500">Device</div><div className="font-medium text-gray-900 dark:text-white">{detail.device.manufacturer} {detail.device.model}</div></div>}
            {detail.device.ip_address && <div><div className="text-xs text-gray-500">IP</div><div className="font-mono text-gray-900 dark:text-white">{detail.device.ip_address}</div></div>}
            <div><div className="text-xs text-gray-500">Artifacts</div><div className="font-medium text-gray-900 dark:text-white">{detail.artifact_count}</div></div>
            <div><div className="text-xs text-gray-500">Size</div><div className="font-medium text-gray-900 dark:text-white">{formatBytes(detail.total_size_bytes)}</div></div>
          </div>
          {detail.tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {detail.tags.map(t => <span key={t} className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900 dark:text-blue-300">{t}</span>)}
            </div>
          )}
          {/* Editable notes */}
          <div className="mt-3">
            <textarea
              value={detail.notes || ''}
              onChange={async (e) => {
                const newNotes = e.target.value;
                setDetail({ ...detail, notes: newNotes });
              }}
              onBlur={async () => {
                await fetch(`/api/v1/sessions/${detail.id}/notes`, {
                  method: 'PUT', headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ notes: detail.notes }),
                });
              }}
              placeholder="Add session notes..."
              rows={2}
              className="w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 placeholder-gray-600 focus:border-blue-500 focus:outline-none"
            />
          </div>
          {detail.description && <p className="mt-1 text-xs text-gray-500">{detail.description}</p>}

          <div className={`mt-4 rounded-lg border p-3 text-xs ${bundleSharingEnabled ? 'border-green-700 bg-green-950/30 text-green-200' : 'border-yellow-700 bg-yellow-950/30 text-yellow-200'}`}>
            {bundleSharingEnabled
              ? 'Supported sharing workflow: keep evidence inside a Session, then use "Bundle + Share" to generate one expiring link with the full session context.'
              : 'Session bundle sharing is disabled right now. You can still generate a local bundle from this session.'}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {detail.status === 'active' && (
              <>
                <button onClick={() => completeSession(detail.id)} className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700">Complete Session</button>
                <button onClick={async () => {
                  await fetch('/api/v1/sessions/deactivate', { method: 'POST' });
                  refreshActive();
                }} className="rounded border border-yellow-500 px-3 py-1.5 text-xs font-medium text-yellow-500 hover:bg-yellow-950"
                  title="Stop auto-linking artifacts without completing the session">
                  Pause Recording
                </button>
              </>
            )}
            <button onClick={() => generateBundle(detail.id)} className="rounded bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700">Generate Bundle</button>
            {bundleSharingEnabled && (
              <button onClick={() => generateAndShare(detail.id)} disabled={sharing}
                className="rounded bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50">
                {sharing ? 'Sharing...' : 'Bundle + Share'}
              </button>
            )}
            <button onClick={async () => {
              if (!confirm(`DISCARD session "${detail.name}" and ALL its data files? This cannot be undone.`)) return;
              await fetch(`/api/v1/sessions/${detail.id}/discard`, { method: 'POST' });
              setSelectedId(null); setDetail(null); refresh(); refreshActive();
            }}
              className="rounded border border-red-500 px-3 py-1.5 text-xs font-medium text-red-500 hover:bg-red-950">
              Discard Session
            </button>
          </div>

          {shareResult && (
            <div className={`mt-3 rounded p-2 text-xs ${shareResult.link ? 'bg-green-950/30 text-green-300' : 'bg-red-950/30 text-red-300'}`}>
              {shareResult.link ? (
                <div className="flex items-center gap-2">
                  <code className="flex-1 font-mono">{shareResult.link}</code>
                  <button onClick={() => { navigator.clipboard.writeText(shareResult.link!); }}
                    className="rounded bg-green-600 px-2 py-1 text-white">Copy</button>
                </div>
              ) : shareResult.error}
            </div>
          )}
        </div>

        {/* Impairment timeline */}
        {detail.impairment_log.length > 0 && (
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="mb-2 text-sm font-medium text-gray-500">Impairment Timeline</h3>
            <div className="space-y-1">
              {detail.impairment_log.map((snap, i) => (
                <div key={i} className="flex gap-3 text-xs">
                  <span className="font-mono text-gray-500">{new Date(snap.timestamp).toLocaleTimeString()}</span>
                  <span className="text-gray-300">{snap.label || snap.profile_name || 'Custom'}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Artifacts */}
        <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <h3 className="mb-3 text-sm font-medium text-gray-500">Artifacts ({artifacts.length})</h3>
          <div className="space-y-1">
            {artifacts.map(a => (
              <div key={a.id} className="flex items-center justify-between rounded border border-gray-700 bg-gray-800/50 px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] font-bold uppercase text-gray-400">
                    {ARTIFACT_ICONS[a.type] || a.type}
                  </span>
                  <span className="text-xs font-medium text-gray-300">{a.name}</span>
                  {a.tags.map(t => <span key={t} className="rounded bg-gray-700 px-1 py-0.5 text-[10px] text-gray-500">{t}</span>)}
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  {a.size_bytes > 0 && <span>{formatBytes(a.size_bytes)}</span>}
                  <span>{new Date(a.created_at).toLocaleTimeString()}</span>
                </div>
              </div>
            ))}
            {artifacts.length === 0 && <p className="text-xs text-gray-500">No artifacts yet. Start captures, logcat, or other tools while this session is active.</p>}
          </div>
        </div>
      </div>
    );
  }

  // List view
  return (
    <div className="space-y-4">
      {/* Create session */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Test Sessions</h2>
          {(sessions ?? []).length > 0 && (
            <button
              onClick={async () => {
                if (!confirm(`Delete all ${(sessions ?? []).length} sessions and their data?`)) return;
                await fetch('/api/v1/sessions/delete-all?discard_data=true', { method: 'POST' });
                refresh(); refreshActive();
              }}
              className="rounded-lg border border-red-300 px-4 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
            >
              Delete All
            </button>
          )}
        </div>

        {activeInfo?.active_session_id && (
          <div className="mb-4 rounded-lg border border-green-600 bg-green-950/30 px-4 py-2 text-sm text-green-300">
            Active session: <strong>{sessions?.find(s => s.id === activeInfo.active_session_id)?.name || activeInfo.active_session_id}</strong>
            — all new artifacts will auto-link here
          </div>
        )}

        <p className="mb-4 text-sm text-gray-500">
          Start here for the supported workflow: create a session first, collect captures and device evidence into it, then generate or share a support bundle from the session detail.
        </p>

        <div className="mb-4 flex gap-2">
          <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Session name (e.g. 'STB-123 Buffering Test')"
            onKeyDown={e => e.key === 'Enter' && createSession()}
            className="flex-1 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
          <input value={newTags} onChange={e => setNewTags(e.target.value)} placeholder="Tags (comma-separated)"
            className="w-40 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
          <input value={newDeviceSerial} onChange={e => setNewDeviceSerial(e.target.value)} placeholder="ADB serial (optional)"
            className="w-40 rounded border border-gray-300 bg-white px-3 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
          <button onClick={createSession} disabled={creating || !newName}
            className="rounded-lg bg-blue-600 px-5 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {creating ? '...' : 'New Session'}
          </button>
        </div>

        {/* Session list */}
        <div className="space-y-2">
          {(sessions ?? []).map(s => (
            <div key={s.id} onClick={() => loadDetail(s.id)}
              className="cursor-pointer rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 transition-colors hover:border-blue-300 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-blue-700">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{s.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[s.status] || ''}`}>{s.status}</span>
                  {activeInfo?.active_session_id === s.id && (
                    <span className="inline-block h-2 w-2 rounded-full bg-green-500" title="Active" />
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">{s.artifact_count} artifacts</span>
                  {s.status === 'active' && activeInfo?.active_session_id !== s.id && (
                    <button onClick={e => { e.stopPropagation(); activateSession(s.id); }}
                      className="rounded bg-green-600 px-2 py-1 text-xs text-white hover:bg-green-700">Activate</button>
                  )}
                </div>
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                {s.device_model && <span>{s.device_model}</span>}
                {s.device_ip && <span className="font-mono">{s.device_ip}</span>}
                <span>{new Date(s.created_at).toLocaleString()}</span>
              </div>
              {s.tags.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {s.tags.map(t => <span key={t} className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-700 dark:text-gray-400">{t}</span>)}
                </div>
              )}
            </div>
          ))}
          {(sessions ?? []).length === 0 && (
            <p className="py-4 text-center text-sm text-gray-500">No sessions yet. Create one to start correlating test artifacts.</p>
          )}
        </div>
      </div>
    </div>
  );
}
