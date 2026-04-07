import { useCallback, useEffect, useMemo, useState } from 'react';
import ModalDialog from './ModalDialog';
import PanelState from './PanelState';
import { useNotification } from '../hooks/useNotification';

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

type DeleteActionKey = 'captures' | 'sessions' | 'adb' | 'annotations' | 'reports' | 'factory';

interface DeleteActionConfig {
  title: string;
  message: string;
  confirmLabel: string;
  deletingLabel: string;
  endpoint: string;
  successMessage: string;
  failureMessage: string;
}

const DELETE_ACTIONS: Record<DeleteActionKey, DeleteActionConfig> = {
  captures: {
    title: 'Delete All Captures',
    message: 'Delete all captures? This cannot be undone.',
    confirmLabel: 'Delete captures',
    deletingLabel: 'Deleting captures...',
    endpoint: '/api/v1/system/data/captures',
    successMessage: 'All captures deleted.',
    failureMessage: 'Failed to delete captures.',
  },
  sessions: {
    title: 'Delete All Sessions',
    message: 'Delete all sessions? This cannot be undone.',
    confirmLabel: 'Delete sessions',
    deletingLabel: 'Deleting sessions...',
    endpoint: '/api/v1/sessions/delete-all?discard_data=true',
    successMessage: 'All sessions deleted.',
    failureMessage: 'Failed to delete sessions.',
  },
  adb: {
    title: 'Delete All ADB Files',
    message: 'Delete all ADB files? This cannot be undone.',
    confirmLabel: 'Delete ADB files',
    deletingLabel: 'Deleting ADB files...',
    endpoint: '/api/v1/system/data/adb_files',
    successMessage: 'All ADB files deleted.',
    failureMessage: 'Failed to delete ADB files.',
  },
  annotations: {
    title: 'Delete All Annotations',
    message: 'Delete all annotations? This cannot be undone.',
    confirmLabel: 'Delete annotations',
    deletingLabel: 'Deleting annotations...',
    endpoint: '/api/v1/system/data/annotations',
    successMessage: 'All annotations deleted.',
    failureMessage: 'Failed to delete annotations.',
  },
  reports: {
    title: 'Delete All Reports',
    message: 'Delete all reports? This cannot be undone.',
    confirmLabel: 'Delete reports',
    deletingLabel: 'Deleting reports...',
    endpoint: '/api/v1/system/data/reports',
    successMessage: 'All reports deleted.',
    failureMessage: 'Failed to delete reports.',
  },
  factory: {
    title: 'Factory Reset',
    message: 'FACTORY RESET: This will delete ALL data (captures, sessions, ADB files, annotations, reports, and custom profiles). This cannot be undone. Are you sure?',
    confirmLabel: 'Continue',
    deletingLabel: 'Resetting...',
    endpoint: '/api/v1/system/data/all',
    successMessage: 'Factory reset complete. All data deleted.',
    failureMessage: 'Factory reset failed.',
  },
};

export default function SettingsPanel() {
  const { notify } = useNotification();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [anthropicKey, setAnthropicKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [aiProvider, setAiProvider] = useState('anthropic');
  const [gitRepo, setGitRepo] = useState('');
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [saving, setSaving] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [deleting, setDeleting] = useState<DeleteActionKey | null>(null);
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<DeleteActionKey | null>(null);
  const [factoryResetStage, setFactoryResetStage] = useState<'warning' | 'final' | null>(null);

  const load = useCallback(async () => {
    setLoadingSettings(true);
    setSettingsError(null);
    try {
      const res = await fetch('/api/v1/system/settings');
      if (!res.ok) throw new Error('Unable to load settings.');

      const data = await res.json();
      setSettings(data);
      setAiProvider(data.ai_provider);
      setGitRepo(data.git_repo_url || '');
    } catch {
      setSettingsError('Unable to load settings right now. Try refreshing the page.');
    } finally {
      setLoadingSettings(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveSettings = async () => {
    setSaving(true);
    try {
      const updates: Record<string, unknown> = { ai_provider: aiProvider };
      if (anthropicKey && !anthropicKey.startsWith('****')) updates.anthropic_api_key = anthropicKey;
      if (openaiKey && !openaiKey.startsWith('****')) updates.openai_api_key = openaiKey;
      if (gitRepo) updates.git_repo_url = gitRepo;

      const res = await fetch('/api/v1/system/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!res.ok) throw new Error('Failed to save');

      notify('Settings saved', 'success');
      load();
    } catch {
      notify('Failed to save settings.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const changePassword = async () => {
    try {
      const res = await fetch(`/api/v1/system/settings/password?current=${encodeURIComponent(currentPw)}&new_password=${encodeURIComponent(newPw)}`, { method: 'POST' });
      const data = await res.json();
      notify(data.message || data.status || 'Password updated', res.ok ? 'success' : 'error');
      if (res.ok) {
        setCurrentPw('');
        setNewPw('');
      }
    } catch {
      notify('Failed to change password.', 'error');
    }
  };

  const [versionInfo, setVersionInfo] = useState<{current_version: string; latest_version: string | null; update_available: boolean; available_versions: string[]} | null>(null);
  const [updateSteps, setUpdateSteps] = useState<string[]>([]);

  const checkForUpdates = async () => {
    try {
      const res = await fetch('/api/v1/system/version');
      if (!res.ok) throw new Error('Unable to check for updates.');
      setVersionInfo(await res.json());
    } catch {
      notify('Unable to check for updates.', 'error');
    }
  };

  const applyUpdate = async (version: string = '') => {
    setUpdating(true);
    setUpdateSteps([]);
    try {
      const params = version ? `?target_version=${version}` : '';
      const res = await fetch(`/api/v1/system/update/apply${params}`, { method: 'POST' });
      const data = await res.json();
      setUpdateSteps(data.steps || []);
      if (data.status === 'ok') {
        notify('Update complete. Restarting...', 'success');
        setTimeout(async () => {
          for (let attempt = 0; attempt < 20; attempt += 1) {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            try {
              const health = await fetch('/api/v1/health');
              if (health.ok) {
                window.location.reload();
                return;
              }
            } catch {
              /* keep polling until the backend returns */
            }
          }
          notify('Backend did not come back. Check the device.', 'error');
          setUpdating(false);
        }, 3000);
      } else {
        notify(data.message || 'Update failed', 'error');
        setUpdating(false);
      }
    } catch {
      notify('Update request failed', 'error');
      setUpdating(false);
    }
  };

  const runDeleteAction = async (action: DeleteActionKey) => {
    const config = DELETE_ACTIONS[action];
    setDeleting(action);
    setPendingDelete(null);
    setFactoryResetStage(null);
    try {
      const res = await fetch(config.endpoint, { method: 'DELETE' });
      if (!res.ok) throw new Error(config.failureMessage);

      notify(config.successMessage, 'success');
      if (action === 'factory') {
        window.dispatchEvent(new CustomEvent('wifry:refresh'));
      }
    } catch {
      notify(config.failureMessage, 'error');
    } finally {
      setDeleting(null);
    }
  };

  const deleteDialog = pendingDelete ? DELETE_ACTIONS[pendingDelete] : null;
  const factoryResetDialog = useMemo(() => {
    if (factoryResetStage === 'warning') {
      return {
        title: DELETE_ACTIONS.factory.title,
        message: DELETE_ACTIONS.factory.message,
        confirmLabel: DELETE_ACTIONS.factory.confirmLabel,
      };
    }

    if (factoryResetStage === 'final') {
      return {
        title: 'Factory Reset',
        message: 'Are you ABSOLUTELY sure? All data will be permanently deleted.',
        confirmLabel: 'Delete all data',
      };
    }

    return null;
  }, [factoryResetStage]);

  if (loadingSettings) {
    return <PanelState title="Loading Settings" message="Fetching saved settings and update preferences." variant="loading" />;
  }

  if (settingsError) {
    return <PanelState title="Settings Unavailable" message={settingsError} variant="error" />;
  }

  if (!settings) {
    return <PanelState title="No Settings Found" message="WiFry did not return any settings data." variant="empty" />;
  }

  return (
    <>
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">Settings</h2>

        <div className="space-y-4">
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
                  <button onClick={() => applyUpdate(versionInfo.latest_version ?? undefined)} disabled={updating}
                    className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50">
                    {updating ? 'Updating...' : `Update to ${versionInfo.latest_version}`}
                  </button>
                )}
              </div>
              {updateSteps.length > 0 && (
                <div className="rounded border border-gray-700 bg-gray-800 p-3">
                  <div className="mb-1 text-xs font-medium text-gray-400">Update Progress</div>
                  {updateSteps.map((step, index) => (
                    <div key={`${step}-${index}`} className="font-mono text-xs text-gray-500">{step}</div>
                  ))}
                </div>
              )}
            </div>
          </div>

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

          <div className="border-t border-gray-200 pt-4 dark:border-gray-700">
            <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">Data Management</h3>
            <p className="mb-3 text-xs text-gray-400">Delete stored data by category. Each action requires confirmation.</p>
            <div className="flex flex-wrap gap-2">
              <button
                disabled={deleting !== null}
                onClick={() => setPendingDelete('captures')}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
              >
                {deleting === 'captures' ? DELETE_ACTIONS.captures.deletingLabel : 'Delete All Captures'}
              </button>
              <button
                disabled={deleting !== null}
                onClick={() => setPendingDelete('sessions')}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
              >
                {deleting === 'sessions' ? DELETE_ACTIONS.sessions.deletingLabel : 'Delete All Sessions'}
              </button>
              <button
                disabled={deleting !== null}
                onClick={() => setPendingDelete('adb')}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
              >
                {deleting === 'adb' ? DELETE_ACTIONS.adb.deletingLabel : 'Delete All ADB Files'}
              </button>
              <button
                disabled={deleting !== null}
                onClick={() => setPendingDelete('annotations')}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
              >
                {deleting === 'annotations' ? DELETE_ACTIONS.annotations.deletingLabel : 'Delete All Annotations'}
              </button>
              <button
                disabled={deleting !== null}
                onClick={() => setPendingDelete('reports')}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400"
              >
                {deleting === 'reports' ? DELETE_ACTIONS.reports.deletingLabel : 'Delete All Reports'}
              </button>
            </div>

            <hr className="my-4 border-gray-200 dark:border-gray-700" />

            <button
              disabled={deleting !== null}
              onClick={() => setFactoryResetStage('warning')}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {deleting === 'factory' ? DELETE_ACTIONS.factory.deletingLabel : 'Factory Reset — Delete ALL Data'}
            </button>
          </div>
        </div>
      </div>

      <ModalDialog
        open={deleteDialog !== null}
        title={deleteDialog?.title ?? ''}
        description={deleteDialog?.message}
        confirmLabel={deleteDialog?.confirmLabel}
        confirmTone="danger"
        onCancel={() => setPendingDelete(null)}
        onConfirm={pendingDelete ? () => runDeleteAction(pendingDelete) : undefined}
      />

      <ModalDialog
        open={factoryResetDialog !== null}
        title={factoryResetDialog?.title ?? ''}
        description={factoryResetDialog?.message}
        confirmLabel={factoryResetDialog?.confirmLabel}
        confirmTone="danger"
        onCancel={() => setFactoryResetStage(null)}
        onConfirm={factoryResetStage === 'warning' ? () => setFactoryResetStage('final') : () => runDeleteAction('factory')}
      />
    </>
  );
}
