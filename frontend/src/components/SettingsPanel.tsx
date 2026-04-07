import { useCallback, useEffect, useState } from 'react';

interface Settings {
  anthropic_api_key: string;
  anthropic_api_key_set: boolean;
  openai_api_key: string;
  openai_api_key_set: boolean;
  ai_provider: string;
  git_repo_url: string;
  web_password_set: boolean;
  ap_ssid: string;
  ap_password: string;
  ap_channel: number;
  ap_band: string;
  mock_mode: boolean;
}

export default function SettingsPanel() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [anthropicKey, setAnthropicKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [aiProvider, setAiProvider] = useState('anthropic');
  const [gitRepo, setGitRepo] = useState('');
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [saving, setSaving] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [message, setMessage] = useState('');
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await fetch('/api/v1/system/settings');
    if (res.ok) {
      const data = await res.json();
      setSettings(data);
      setAiProvider(data.ai_provider);
      setGitRepo(data.git_repo_url || '');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveSettings = async () => {
    setSaving(true);
    setMessage('');
    try {
      const updates: Record<string, unknown> = { ai_provider: aiProvider };
      if (anthropicKey && !anthropicKey.startsWith('****')) updates.anthropic_api_key = anthropicKey;
      if (openaiKey && !openaiKey.startsWith('****')) updates.openai_api_key = openaiKey;
      if (gitRepo) updates.git_repo_url = gitRepo;

      await fetch('/api/v1/system/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      setMessage('Settings saved');
      load();
    } catch { setMessage('Failed to save'); }
    finally { setSaving(false); }
  };

  const changePassword = async () => {
    const res = await fetch(`/api/v1/system/settings/password?current=${encodeURIComponent(currentPw)}&new_password=${encodeURIComponent(newPw)}`, { method: 'POST' });
    const data = await res.json();
    setMessage(data.message || data.status);
    setCurrentPw('');
    setNewPw('');
  };

  const [versionInfo, setVersionInfo] = useState<{current_version: string; latest_version: string | null; update_available: boolean; available_versions: string[]} | null>(null);
  const [updateSteps, setUpdateSteps] = useState<string[]>([]);

  const checkForUpdates = async () => {
    try {
      const res = await fetch('/api/v1/system/version');
      if (res.ok) setVersionInfo(await res.json());
    } catch {}
  };

  const applyUpdate = async (version: string = '') => {
    setUpdating(true);
    setUpdateSteps([]);
    setMessage('');
    try {
      const params = version ? `?target_version=${version}` : '';
      const res = await fetch(`/api/v1/system/update/apply${params}`, { method: 'POST' });
      const data = await res.json();
      setUpdateSteps(data.steps || []);
      if (data.status === 'ok') {
        setMessage('Update complete. Restarting...');
        // Poll for backend to come back
        setTimeout(async () => {
          for (let i = 0; i < 20; i++) {
            await new Promise(r => setTimeout(r, 2000));
            try {
              const health = await fetch('/api/v1/health');
              if (health.ok) {
                window.location.reload();
                return;
              }
            } catch {}
          }
          setMessage('Backend did not come back. Check the device.');
          setUpdating(false);
        }, 3000);
      } else {
        setMessage(data.message || 'Update failed');
        setUpdating(false);
      }
    } catch {
      setMessage('Update request failed');
      setUpdating(false);
    }
  };

  if (!settings) return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">Settings</h2>

      {message && (
        <div className="mb-4 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-700 dark:bg-blue-950 dark:text-blue-300">
          {message}
        </div>
      )}

      <div className="space-y-4">
        {/* AI Configuration */}
        <div>
          <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">AI Analysis</h3>
          <div className="space-y-2">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Provider</label>
              <select value={aiProvider} onChange={(e) => setAiProvider(e.target.value)}
                className="w-48 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white">
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="openai">OpenAI (GPT)</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">
                Anthropic API Key {settings.anthropic_api_key_set && <span className="text-green-500">(set)</span>}
              </label>
              <input type="password" value={anthropicKey} onChange={(e) => setAnthropicKey(e.target.value)}
                placeholder={settings.anthropic_api_key_set ? '****already set****' : 'sk-ant-...'}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">
                OpenAI API Key {settings.openai_api_key_set && <span className="text-green-500">(set)</span>}
              </label>
              <input type="password" value={openaiKey} onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder={settings.openai_api_key_set ? '****already set****' : 'sk-...'}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
            </div>
          </div>
        </div>

        {/* Updates */}
        <div>
          <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">Software Updates</h3>
          <div className="space-y-3">
            {versionInfo && (
              <div className="flex items-center gap-3 text-sm">
                <span className="text-gray-400">Current: <span className="font-medium text-white">v{versionInfo.current_version}</span></span>
                {versionInfo.update_available && versionInfo.latest_version && (
                  <span className="rounded bg-green-900 px-2 py-0.5 text-xs font-medium text-green-400">
                    {versionInfo.latest_version} available
                  </span>
                )}
                {!versionInfo.update_available && (
                  <span className="text-xs text-gray-600">Up to date</span>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={checkForUpdates} disabled={updating}
                className="rounded-lg border border-gray-600 px-4 py-1.5 text-sm font-medium text-gray-400 hover:bg-gray-800 disabled:opacity-50">
                Check for Updates
              </button>
              {versionInfo?.update_available && versionInfo.latest_version && (
                <button onClick={() => applyUpdate(versionInfo.latest_version!)} disabled={updating}
                  className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50">
                  {updating ? 'Updating...' : `Update to ${versionInfo.latest_version}`}
                </button>
              )}
            </div>
            {updateSteps.length > 0 && (
              <div className="rounded border border-gray-700 bg-gray-800 p-3">
                <div className="mb-1 text-xs font-medium text-gray-400">Update Progress</div>
                {updateSteps.map((step, i) => (
                  <div key={i} className="font-mono text-xs text-gray-500">{step}</div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Password */}
        <div>
          <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">
            Web Password {settings.web_password_set && <span className="text-green-500">(set)</span>}
          </h3>
          <div className="flex gap-2">
            <input type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)}
              placeholder="Current password"
              className="w-40 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)}
              placeholder="New password"
              className="w-40 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
            <button onClick={changePassword} disabled={!newPw}
              className="rounded-lg bg-gray-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-600 disabled:opacity-50">
              Change
            </button>
          </div>
        </div>

        <button onClick={saveSettings} disabled={saving}
          className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {saving ? 'Saving...' : 'Save Settings'}
        </button>

        {/* Data Management */}
        <div className="border-t border-gray-200 pt-4 dark:border-gray-700">
          <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">Data Management</h3>
          <p className="mb-3 text-xs text-gray-400">Delete stored data by category. Each action requires confirmation.</p>
          <div className="flex flex-wrap gap-2">
            <button
              disabled={deleting !== null}
              onClick={async () => {
                if (!confirm('Delete all captures? This cannot be undone.')) return;
                setDeleting('captures');
                try {
                  await fetch('/api/v1/system/data/captures', { method: 'DELETE' });
                  setMessage('All captures deleted.');
                } catch { setMessage('Failed to delete captures.'); }
                finally { setDeleting(null); }
              }}
              className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
            >
              {deleting === 'captures' ? 'Deleting...' : 'Delete All Captures'}
            </button>
            <button
              disabled={deleting !== null}
              onClick={async () => {
                if (!confirm('Delete all sessions? This cannot be undone.')) return;
                setDeleting('sessions');
                try {
                  await fetch('/api/v1/sessions/delete-all?discard_data=true', { method: 'POST' });
                  setMessage('All sessions deleted.');
                } catch { setMessage('Failed to delete sessions.'); }
                finally { setDeleting(null); }
              }}
              className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
            >
              {deleting === 'sessions' ? 'Deleting...' : 'Delete All Sessions'}
            </button>
            <button
              disabled={deleting !== null}
              onClick={async () => {
                if (!confirm('Delete all ADB files? This cannot be undone.')) return;
                setDeleting('adb');
                try {
                  await fetch('/api/v1/system/data/adb_files', { method: 'DELETE' });
                  setMessage('All ADB files deleted.');
                } catch { setMessage('Failed to delete ADB files.'); }
                finally { setDeleting(null); }
              }}
              className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
            >
              {deleting === 'adb' ? 'Deleting...' : 'Delete All ADB Files'}
            </button>
            <button
              disabled={deleting !== null}
              onClick={async () => {
                if (!confirm('Delete all annotations? This cannot be undone.')) return;
                setDeleting('annotations');
                try {
                  await fetch('/api/v1/system/data/annotations', { method: 'DELETE' });
                  setMessage('All annotations deleted.');
                } catch { setMessage('Failed to delete annotations.'); }
                finally { setDeleting(null); }
              }}
              className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
            >
              {deleting === 'annotations' ? 'Deleting...' : 'Delete All Annotations'}
            </button>
            <button
              disabled={deleting !== null}
              onClick={async () => {
                if (!confirm('Delete all reports? This cannot be undone.')) return;
                setDeleting('reports');
                try {
                  await fetch('/api/v1/system/data/reports', { method: 'DELETE' });
                  setMessage('All reports deleted.');
                } catch { setMessage('Failed to delete reports.'); }
                finally { setDeleting(null); }
              }}
              className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
            >
              {deleting === 'reports' ? 'Deleting...' : 'Delete All Reports'}
            </button>
          </div>

          <hr className="my-4 border-gray-200 dark:border-gray-700" />

          <button
            disabled={deleting !== null}
            onClick={async () => {
              if (!confirm('FACTORY RESET: This will delete ALL data (captures, sessions, ADB files, annotations, reports, and custom profiles). This cannot be undone. Are you sure?')) return;
              if (!confirm('Are you ABSOLUTELY sure? All data will be permanently deleted.')) return;
              setDeleting('factory');
              try {
                await fetch('/api/v1/system/data/all', { method: 'DELETE' });
                setMessage('Factory reset complete. All data deleted.');
                window.dispatchEvent(new CustomEvent('wifry:refresh'));
              } catch { setMessage('Factory reset failed.'); }
              finally { setDeleting(null); }
            }}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {deleting === 'factory' ? 'Resetting...' : 'Factory Reset \u2014 Delete ALL Data'}
          </button>
        </div>
      </div>
    </div>
  );
}
