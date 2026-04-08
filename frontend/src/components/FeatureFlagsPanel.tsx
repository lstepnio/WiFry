/**
 * Feature flags management UI.
 * Allows admins to enable/disable features that aren't ready for production.
 */
import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useConfirm } from '../hooks/useConfirm';

interface FeatureFlag {
  enabled: boolean;
  label: string;
  description: string;
  category: string;
  disabled_reason?: string;
}

type Flags = Record<string, FeatureFlag>;

const CATEGORY_ORDER = ['core', 'analysis', 'tools', 'advanced', 'sharing', 'experimental', 'fun'];
const EXPERIMENTAL_FLAGS = new Set(['sharing_tunnel', 'collaboration', 'experimental_video_capture']);
const CATEGORY_LABELS: Record<string, string> = {
  core: 'Core Features',
  analysis: 'Analysis',
  tools: 'Tools',
  advanced: 'Advanced (Hardware Required)',
  sharing: 'Sharing & Remote Access',
  experimental: 'Experimental',
  fun: 'Easter Eggs',
};

export default function FeatureFlagsPanel() {
  const confirmAction = useConfirm();
  const fetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/system/features'); return r.ok ? r.json() : {}; } catch { return {}; }
  }, []);
  const { data: flags, refresh } = useApi<Flags>(fetcher);
  const [toggling, setToggling] = useState<string | null>(null);

  const toggle = async (key: string, enabled: boolean) => {
    setToggling(key);
    try {
      await fetch(`/api/v1/system/features/${key}?enabled=${enabled}`, { method: 'PUT' });
      refresh();
    } catch {
      /* ignore toggle failures; the next refresh keeps UI consistent */
    }
    finally { setToggling(null); }
  };

  const resetDefaults = async () => {
    if (!await confirmAction({ title: 'Reset Feature Flags', message: 'Reset all feature flags to defaults?', confirmLabel: 'Reset' })) return;
    await fetch('/api/v1/system/features/reset', { method: 'POST' });
    refresh();
  };

  if (!flags) return null;

  // Group by category
  const grouped: Record<string, [string, FeatureFlag][]> = {};
  for (const [key, flag] of Object.entries(flags)) {
    const cat = flag.category || 'other';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push([key, flag]);
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Feature Flags</h2>
          <p className="text-xs text-gray-500">Supported workflows stay on by default. Use these flags to opt into or hide additional surfaces.</p>
        </div>
        <button onClick={resetDefaults}
          className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-800">
          Reset Defaults
        </button>
      </div>

      {CATEGORY_ORDER.filter(cat => grouped[cat]).map(cat => (
        <div key={cat} className="mb-4">
          <h3 className="mb-2 text-xs font-medium uppercase text-gray-500">{CATEGORY_LABELS[cat] || cat}</h3>
          <div className="space-y-1">
            {(grouped[cat] || []).map(([key, flag]) => (
              <div key={key} className="flex items-center justify-between rounded border border-gray-700 bg-gray-800/30 px-3 py-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-200">{flag.label}</span>
                    {EXPERIMENTAL_FLAGS.has(key) && (
                      <span className="rounded bg-yellow-900 px-1.5 py-0.5 text-[9px] font-bold text-yellow-300">
                        EXPERIMENTAL
                      </span>
                    )}
                    <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${flag.enabled ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                      {flag.enabled ? 'ON' : 'OFF'}
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-500">{flag.description}</p>
                  {!flag.enabled && flag.disabled_reason && (
                    <p className="mt-1 rounded bg-yellow-950/40 px-2 py-1 text-[10px] text-yellow-300/80">
                      Why disabled: {flag.disabled_reason}
                    </p>
                  )}
                </div>
                <label className="relative ml-3 inline-flex cursor-pointer items-center">
                  <input type="checkbox" checked={flag.enabled}
                    disabled={toggling === key}
                    onChange={(e) => toggle(key, e.target.checked)}
                    className="peer sr-only" />
                  <div className="peer h-5 w-9 rounded-full bg-gray-600 after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all peer-checked:bg-green-500 peer-checked:after:translate-x-full peer-disabled:opacity-50" />
                </label>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
