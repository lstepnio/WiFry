import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useFeatureFlags } from '../hooks/useFeatureFlags';
import PanelState from './PanelState';
import { useNotification } from '../hooks/useNotification';

interface TunnelStatus {
  active: boolean;
  url: string | null;
  started_at: string | null;
  share_url: string | null;
  message: string;
}

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

const MODE_LABELS: Record<string, { label: string; desc: string }> = {
  'co-pilot': { label: 'Co-Pilot', desc: 'Anyone on the tunnel can drive the UI.' },
  download: { label: 'Download Only', desc: 'Remote users can inspect and download, but not co-drive.' },
};

export default function SharePanel() {
  const { notify } = useNotification();
  const { isEnabled } = useFeatureFlags();
  const liveRemoteAccessEnabled = isEnabled('sharing_tunnel');
  const collaborationEnabled = isEnabled('collaboration');
  const bundleSharingEnabled = isEnabled('sharing_fileio');

  const tunnelFetcher = useCallback(async () => {
    if (!liveRemoteAccessEnabled) {
      return {
        active: false,
        url: null,
        started_at: null,
        share_url: null,
        message: 'Live remote access is disabled.',
      };
    }

    const res = await fetch('/api/v1/tunnel/status');
    return res.ok ? res.json() : null;
  }, [liveRemoteAccessEnabled]);
  const { data: status, loading: tunnelLoading, error: tunnelError, refresh } = useApi<TunnelStatus | null>(tunnelFetcher, liveRemoteAccessEnabled ? 5000 : undefined);

  const collabFetcher = useCallback(async () => {
    if (!collaborationEnabled) {
      return { mode: 'download', connected_users: [], user_count: 0 };
    }

    const res = await fetch('/api/v1/collab/status');
    return res.ok ? res.json() : null;
  }, [collaborationEnabled]);
  const { data: collabStatus, loading: collabLoading, error: collabError, refresh: refreshCollab } = useApi<CollabStatus | null>(collabFetcher, collaborationEnabled ? 3000 : undefined);

  const [toggling, setToggling] = useState(false);
  const [copied, setCopied] = useState('');
  const [updatingMode, setUpdatingMode] = useState<string | null>(null);

  const toggleTunnel = async () => {
    if (!liveRemoteAccessEnabled) return;

    setToggling(true);
    try {
      const endpoint = status?.active ? 'stop' : 'start';
      const res = await fetch(`/api/v1/tunnel/${endpoint}`, { method: 'POST' });
      if (!res.ok) throw new Error('Tunnel error');

      refresh();
      refreshCollab();
      notify(status?.active ? 'Live remote access stopped' : 'Live remote access started', 'success');
    } catch {
      notify('Tunnel error', 'error');
    } finally {
      setToggling(false);
    }
  };

  const setMode = async (mode: string) => {
    setUpdatingMode(mode);
    try {
      const res = await fetch('/api/v1/collab/mode', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      if (!res.ok) throw new Error('Failed to update collaboration mode');

      refreshCollab();
      notify(`Collaboration mode set to ${MODE_LABELS[mode]?.label ?? mode}`, 'success');
    } catch {
      notify('Failed to update collaboration mode.', 'error');
    } finally {
      setUpdatingMode(null);
    }
  };

  const copyUrl = (url: string, id: string, label: string) => {
    try {
      navigator.clipboard.writeText(url);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }

    setCopied(id);
    setTimeout(() => setCopied(''), 2000);
    notify(`${label} copied to clipboard`, 'success');
  };

  if (tunnelLoading && liveRemoteAccessEnabled) {
    return <PanelState title="Loading Remote Access" message="Checking tunnel status and collaboration details." variant="loading" />;
  }

  if (tunnelError && liveRemoteAccessEnabled) {
    return <PanelState title="Remote Access Unavailable" message="Unable to load remote-access status right now." variant="error" />;
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Remote Access</h2>
          <p className="text-xs text-gray-500">
            Supported sharing happens from Sessions using a single support bundle. The controls below are opt-in tools for temporary live troubleshooting.
          </p>
        </div>

        <div className={`rounded-lg border p-4 ${bundleSharingEnabled ? 'border-green-700 bg-green-950/30' : 'border-yellow-700 bg-yellow-950/30'}`}>
          <div className={`text-sm font-medium ${bundleSharingEnabled ? 'text-green-300' : 'text-yellow-300'}`}>
            {bundleSharingEnabled ? 'Supported workflow: Session bundle sharing' : 'Session bundle sharing is disabled'}
          </div>
          <p className={`mt-1 text-xs ${bundleSharingEnabled ? 'text-green-200' : 'text-yellow-200'}`}>
            {bundleSharingEnabled
              ? 'Create or open a Session, collect artifacts there, then use "Bundle + Share" from the session detail to generate one expiring link with the full test context.'
              : 'Live remote access can still be enabled below, but the recommended support-bundle flow is currently turned off in feature flags.'}
          </p>
        </div>
      </div>

      {liveRemoteAccessEnabled && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Live Remote Access</h3>
              <p className="text-xs text-gray-500">
                Experimental. Opens the WiFry UI through Cloudflare Quick Tunnel for short-lived remote troubleshooting.
              </p>
            </div>
            <button
              onClick={toggleTunnel}
              disabled={toggling}
              className={`rounded-lg px-4 py-1.5 text-xs font-medium text-white disabled:opacity-50 ${status?.active ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}`}
            >
              {toggling ? 'Working...' : status?.active ? 'Stop Tunnel' : 'Start Tunnel'}
            </button>
          </div>

          {status?.active && status.url ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded bg-gray-900 px-3 py-1.5 font-mono text-xs text-green-300">{status.url}</code>
                <button
                  onClick={() => copyUrl(status.url ?? '', 'tunnel', 'Tunnel URL')}
                  className="rounded bg-green-600 px-2 py-1.5 text-xs text-white hover:bg-green-700"
                >
                  {copied === 'tunnel' ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <p className="text-xs text-gray-500">
                Remote users will see the live UI. Prefer Sessions for durable evidence sharing and use the tunnel only when someone needs to inspect the box in real time.
              </p>
            </div>
          ) : (
            <PanelState title="Tunnel Not Active" message="Tunnel access is off. Start it only when you need a live troubleshooting session, then stop it when you are done." variant="empty" />
          )}
        </div>
      )}

      {collaborationEnabled && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Live Collaboration</h3>
          <p className="mt-1 text-xs text-gray-500">
            Experimental. This synchronizes navigation for remote users connected through the live tunnel.
          </p>

          {collabLoading ? (
            <PanelState title="Loading Collaboration" message="Checking collaboration mode and connected users." variant="loading" />
          ) : collabError || !collabStatus ? (
            <PanelState title="Collaboration Unavailable" message="Unable to load collaboration status right now." variant="error" />
          ) : (
            <>
              <div className="mt-4 flex flex-wrap gap-2">
                {Object.entries(MODE_LABELS).map(([mode, info]) => (
                  <button
                    key={mode}
                    onClick={() => setMode(mode)}
                    disabled={updatingMode === mode}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                      collabStatus.mode === mode
                        ? 'bg-blue-600 text-white'
                        : 'border border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800'
                    }`}
                  >
                    {updatingMode === mode ? 'Updating...' : info.label}
                  </button>
                ))}
              </div>

              <p className="mt-2 text-xs text-gray-500">
                {MODE_LABELS[collabStatus.mode]?.desc ?? MODE_LABELS.download.desc}
              </p>

              {collabStatus.connected_users.length > 0 ? (
                <div className="mt-4 rounded border border-gray-700 bg-gray-800/40 px-3 py-2">
                  <div className="text-xs text-gray-400">
                    Connected users: <span className="font-medium text-gray-200">{collabStatus.user_count}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {collabStatus.connected_users.map((user) => (
                      <span key={user.id} className="rounded-full bg-gray-700 px-2 py-0.5 text-[10px] text-gray-200">
                        {user.name}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <PanelState title="No Remote Users Connected" message="Collaboration is available, but nobody is connected to the live session right now." variant="empty" />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
