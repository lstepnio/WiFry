/**
 * Collaboration overlay — shows connected users, mode indicator,
 * and chat for shadow/co-pilot sessions.
 */
import { useEffect, useRef, useState } from 'react';

interface User {
  id: string;
  name: string;
  connected_at: string;
  is_local: boolean;
}

interface ChatMsg {
  user_name: string;
  message: string;
  timestamp: string;
}

interface CollabStatus {
  mode: string;
  connected_users: User[];
  user_count: number;
}

const MODE_LABELS: Record<string, { label: string; color: string; desc: string }> = {
  'co-pilot': { label: 'Co-Pilot', color: 'bg-green-600', desc: 'Anyone can drive' },
  'spectate': { label: 'Spectate', color: 'bg-blue-600', desc: 'View only for remote users' },
  'download': { label: 'Download', color: 'bg-gray-600', desc: 'File access only' },
};

export default function CollabOverlay({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const [status, setStatus] = useState<CollabStatus | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [showPanel, setShowPanel] = useState(false);
  const [lastAction, setLastAction] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll status
  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/v1/collab/status');
        if (res.ok) setStatus(await res.json());
      } catch {}
    };
    load();
    pollRef.current = setInterval(load, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // WebSocket connection
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/collab/ws?name=`;

    try {
      const socket = new WebSocket(wsUrl);

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'init':
            setStatus(prev => prev ? { ...prev, connected_users: data.users, mode: data.mode } : prev);
            break;
          case 'user_joined':
          case 'user_left':
            setStatus(prev => prev ? { ...prev, user_count: data.user_count } : prev);
            break;
          case 'navigate':
            if (onNavigate) onNavigate(data.tab);
            setLastAction(`${data.by} navigated to ${data.tab}`);
            break;
          case 'action':
            setLastAction(`${data.by}: ${data.action}`);
            break;
          case 'state_update':
            setLastAction(data.action);
            break;
          case 'chat':
            setChat(prev => [...prev.slice(-50), { user_name: data.user_name, message: data.message, timestamp: data.timestamp }]);
            break;
          case 'mode_change':
            setStatus(prev => prev ? { ...prev, mode: data.mode } : prev);
            break;
          case 'error':
            setLastAction(`Error: ${data.message}`);
            break;
        }
      };

      socket.onclose = () => setTimeout(() => { /* reconnect logic */ }, 3000);
      setWs(socket);

      return () => socket.close();
    } catch {
      // WebSocket not available (e.g., dev mode proxy issue)
    }
  }, [onNavigate]);

  const sendChat = () => {
    if (!ws || !chatInput.trim()) return;
    ws.send(JSON.stringify({ type: 'chat', message: chatInput }));
    setChatInput('');
  };

  const setMode = async (mode: string) => {
    await fetch('/api/v1/collab/mode', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
  };

  const userCount = status?.user_count ?? 0;
  const remoteUserCount = (status?.connected_users ?? []).filter(u => !u.is_local).length;
  const mode = status?.mode ?? 'co-pilot';
  const modeInfo = MODE_LABELS[mode] || MODE_LABELS['co-pilot'];

  // Only show overlay when there are remote (non-local) users connected
  if (remoteUserCount <= 0 && !showPanel) return null;

  return (
    <>
      {/* Floating user count badge */}
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

      {/* Expanded panel */}
      {showPanel && (
        <div className="fixed bottom-14 left-4 z-50 w-80 overflow-hidden rounded-xl border border-gray-700 bg-gray-900 shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between bg-gray-800 px-4 py-2">
            <span className="text-sm font-medium text-gray-200">Collaboration</span>
            <button onClick={() => setShowPanel(false)} className="text-gray-400 hover:text-white">&#x2715;</button>
          </div>

          {/* Mode selector */}
          <div className="border-b border-gray-700 px-4 py-2">
            <div className="mb-1 text-[10px] text-gray-500">Sharing Mode</div>
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
          <div className="border-b border-gray-700 px-4 py-2">
            <div className="mb-1 text-[10px] text-gray-500">Connected ({userCount})</div>
            <div className="space-y-1">
              {(status?.connected_users ?? []).map(u => (
                <div key={u.id} className="flex items-center gap-2 text-xs">
                  <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
                  <span className="text-gray-300">{u.name}</span>
                  {u.is_local && <span className="text-[9px] text-gray-600">(local)</span>}
                </div>
              ))}
            </div>
          </div>

          {/* Last action */}
          {lastAction && (
            <div className="border-b border-gray-700 px-4 py-2 text-[10px] text-gray-400">
              {lastAction}
            </div>
          )}

          {/* Chat */}
          <div className="px-4 py-2">
            <div className="mb-1 text-[10px] text-gray-500">Chat</div>
            <div className="mb-2 max-h-32 overflow-y-auto">
              {chat.length === 0 ? (
                <div className="text-[10px] text-gray-600">No messages yet</div>
              ) : (
                chat.slice(-10).map((m, i) => (
                  <div key={i} className="text-[10px]">
                    <span className="font-medium text-blue-400">{m.user_name}:</span>{' '}
                    <span className="text-gray-300">{m.message}</span>
                  </div>
                ))
              )}
            </div>
            <div className="flex gap-1">
              <input
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendChat()}
                placeholder="Type a message..."
                className="flex-1 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-[10px] text-white"
              />
              <button onClick={sendChat}
                className="rounded bg-blue-600 px-2 py-1 text-[10px] text-white hover:bg-blue-700">
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
