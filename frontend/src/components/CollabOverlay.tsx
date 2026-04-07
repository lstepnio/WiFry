/**
 * Collaboration overlay — shows connected users and mode indicator.
 */
import { useEffect, useRef, useState } from 'react';

interface User {
  id: string;
  name: string;
  ip: string;
  connected_at: string;
}

interface CollabStatus {
  mode: string;
  connected_users: User[];
  user_count: number;
}

const MODE_LABELS: Record<string, { label: string; color: string; desc: string }> = {
  'co-pilot': { label: 'Co-Pilot', color: 'bg-green-600', desc: 'Anyone can drive' },
  'download': { label: 'Download', color: 'bg-gray-600', desc: 'File access only' },
};

export default function CollabOverlay() {
  const [status, setStatus] = useState<CollabStatus | null>(null);
  const [showPanel, setShowPanel] = useState(false);
  const [lastAction] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/v1/collab/status');
        if (res.ok) setStatus(await res.json());
      } catch {}
    };
    load();
    pollRef.current = setInterval(load, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const setMode = async (mode: string) => {
    await fetch('/api/v1/collab/mode', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
  };

  const userCount = status?.user_count ?? 0;
  const mode = status?.mode ?? 'co-pilot';
  const modeInfo = MODE_LABELS[mode] || MODE_LABELS['co-pilot'];

  if (userCount <= 1 && !showPanel) return null;

  return (
    <>
      {/* Floating badge */}
      <button
        onClick={() => setShowPanel(!showPanel)}
        className="fixed bottom-4 left-4 z-40 flex items-center gap-2 rounded-full bg-gray-800 px-3 py-2 shadow-lg hover:bg-gray-700"
      >
        <div className="flex -space-x-1">
          {(status?.connected_users ?? []).slice(0, 4).map((u) => (
            <div key={u.id} className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-gray-800 bg-blue-600 text-[10px] font-bold text-white">
              {u.name[0].toUpperCase()}
            </div>
          ))}
        </div>
        <span className="text-xs text-gray-300">{userCount} user{userCount !== 1 ? 's' : ''}</span>
        <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold text-white ${modeInfo.color}`}>{modeInfo.label}</span>
      </button>

      {/* Panel */}
      {showPanel && (
        <div className="fixed bottom-14 left-4 z-50 w-72 overflow-hidden rounded-xl border border-gray-700 bg-gray-900 shadow-2xl">
          <div className="flex items-center justify-between bg-gray-800 px-4 py-2">
            <span className="text-sm font-medium text-gray-200">Collaboration</span>
            <button onClick={() => setShowPanel(false)} className="text-gray-400 hover:text-white">&#x2715;</button>
          </div>

          {/* Mode selector */}
          <div className="border-b border-gray-700 px-4 py-2">
            <div className="mb-1 text-[10px] text-gray-500">Mode</div>
            <div className="flex gap-1">
              {Object.entries(MODE_LABELS).map(([key, info]) => (
                <button
                  key={key}
                  onClick={() => setMode(key)}
                  className={`rounded px-2 py-1 text-[10px] font-medium ${mode === key ? `${info.color} text-white` : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}
                >
                  {info.label}
                </button>
              ))}
            </div>
            <div className="mt-1 text-[10px] text-gray-500">{modeInfo.desc}</div>
          </div>

          {/* Connected users */}
          <div className="px-4 py-2">
            <div className="mb-1 text-[10px] text-gray-500">Connected ({userCount})</div>
            <div className="space-y-1">
              {(status?.connected_users ?? []).map(u => (
                <div key={u.id} className="flex items-center gap-2 text-xs">
                  <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
                  <span className="text-gray-300">{u.name}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Last action */}
          {lastAction && (
            <div className="border-t border-gray-700 px-4 py-2 text-[10px] text-gray-400">
              {lastAction}
            </div>
          )}
        </div>
      )}
    </>
  );
}
