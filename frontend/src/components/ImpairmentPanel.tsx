import { useCallback, useEffect, useState } from 'react';
import type { ImpairmentConfig, InterfaceImpairmentState } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';

const DEFAULT_CONFIG: ImpairmentConfig = {
  delay: { ms: 0, jitter_ms: 0, correlation_pct: 25 },
  loss: { pct: 0, correlation_pct: 25 },
  corrupt: { pct: 0 },
  duplicate: { pct: 0 },
  reorder: { pct: 0, correlation_pct: 50 },
  rate: { kbit: 0, burst: '32kbit' },
};

function SliderRow({
  label,
  value,
  onChange,
  min = 0,
  max,
  step = 1,
  unit,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max: number;
  step?: number;
  unit: string;
}) {
  return (
    <div className="flex items-center gap-3 py-1">
      <label className="w-36 text-sm text-gray-600 dark:text-gray-400">{label}</label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-blue-600"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 rounded border border-gray-300 bg-white px-2 py-1 text-right text-sm dark:border-gray-600 dark:bg-gray-800"
      />
      <span className="w-12 text-xs text-gray-500">{unit}</span>
    </div>
  );
}

export default function ImpairmentPanel() {
  const fetcher = useCallback(() => api.getImpairments(), []);
  const { data: states, refresh } = useApi<InterfaceImpairmentState[]>(fetcher, 5000);
  const [selectedInterface, setSelectedInterface] = useState('');
  const [config, setConfig] = useState<ImpairmentConfig>(DEFAULT_CONFIG);
  const [applying, setApplying] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [feedback, setFeedback] = useState<'success' | 'error' | null>(null);

  useEffect(() => {
    if (states && states.length > 0 && !selectedInterface) {
      setSelectedInterface(states[0].interface);
    }
  }, [states, selectedInterface]);

  useEffect(() => {
    // Only sync from server when user hasn't made local changes
    if (dirty) return;
    if (states && selectedInterface) {
      const state = states.find((s) => s.interface === selectedInterface);
      if (state && state.active) {
        setConfig({
          ...DEFAULT_CONFIG,
          ...state.config,
        });
      }
    }
  }, [states, selectedInterface, dirty]);

  const update = (path: string, value: number) => {
    setDirty(true);
    setConfig((prev) => {
      // Merge with defaults so null sub-objects become valid objects
      const merged = { ...DEFAULT_CONFIG, ...prev };
      for (const key of Object.keys(DEFAULT_CONFIG) as (keyof ImpairmentConfig)[]) {
        if (merged[key] == null && DEFAULT_CONFIG[key] != null) {
          (merged as Record<string, unknown>)[key] = JSON.parse(JSON.stringify(DEFAULT_CONFIG[key]));
        }
      }
      const next = JSON.parse(JSON.stringify(merged)) as ImpairmentConfig;
      const parts = path.split('.');
      let obj: Record<string, unknown> = next as unknown as Record<string, unknown>;
      for (let i = 0; i < parts.length - 1; i++) {
        obj = obj[parts[i]] as Record<string, unknown>;
      }
      obj[parts[parts.length - 1]] = value;
      return next;
    });
  };

  const showFeedback = (type: 'success' | 'error') => {
    setFeedback(type);
    setTimeout(() => setFeedback(null), 2000);
  };

  const handleApply = async () => {
    if (!selectedInterface) return;
    setApplying(true);
    try {
      await api.applyImpairment(selectedInterface, config);
      setDirty(false);
      showFeedback('success');
      refresh();
    } catch (e) {
      showFeedback('error');
      alert(e instanceof Error ? e.message : 'Failed to apply');
    } finally {
      setApplying(false);
    }
  };

  const handleClear = async () => {
    if (!selectedInterface) return;
    setApplying(true);
    try {
      await api.clearImpairment(selectedInterface);
      setConfig(DEFAULT_CONFIG);
      setDirty(false);
      showFeedback('success');
      refresh();
    } catch (e) {
      showFeedback('error');
      alert(e instanceof Error ? e.message : 'Failed to clear');
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Network Impairments</h2>
          <span className="ml-2 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-gray-700 text-[10px] font-bold text-gray-400" title="Simulate adverse network conditions using tc netem. These affect all traffic on the selected interface — delay, jitter, packet loss, corruption, reordering, and bandwidth limits.">?</span>
        </div>
        {states && states.length > 1 && (
          <select
            value={selectedInterface}
            onChange={(e) => setSelectedInterface(e.target.value)}
            className="rounded border border-gray-300 bg-white px-3 py-1 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          >
            {states.map((s) => (
              <option key={s.interface} value={s.interface}>
                {s.interface} {s.active ? '(active)' : ''}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <h3 className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300" title="Add fixed delay and random jitter to packets. Simulates network distance and variability.">Delay</h3>
          <SliderRow label="Delay" value={config.delay?.ms ?? 0} onChange={(v) => update('delay.ms', v)} max={2000} unit="ms" />
          <SliderRow label="Jitter" value={config.delay?.jitter_ms ?? 0} onChange={(v) => update('delay.jitter_ms', v)} max={1000} unit="ms" />
          <SliderRow label="Correlation" value={config.delay?.correlation_pct ?? 0} onChange={(v) => update('delay.correlation_pct', v)} max={100} unit="%" />
        </div>

        <div>
          <h3 className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300" title="Randomly drop packets. TiVo recommends no worse than 0.03% (1 in 3333) for stable streaming.">Packet Loss</h3>
          <SliderRow label="Loss" value={config.loss?.pct ?? 0} onChange={(v) => update('loss.pct', v)} max={100} step={0.1} unit="%" />
          <SliderRow label="Correlation" value={config.loss?.correlation_pct ?? 0} onChange={(v) => update('loss.correlation_pct', v)} max={100} unit="%" />
        </div>

        <div>
          <h3 className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300" title="Corruption flips random bits in packets. Duplication creates copies. Reordering delivers packets out of order.">Other</h3>
          <SliderRow label="Corruption" value={config.corrupt?.pct ?? 0} onChange={(v) => update('corrupt.pct', v)} max={100} step={0.1} unit="%" />
          <SliderRow label="Duplication" value={config.duplicate?.pct ?? 0} onChange={(v) => update('duplicate.pct', v)} max={100} step={0.1} unit="%" />
          <SliderRow label="Reorder" value={config.reorder?.pct ?? 0} onChange={(v) => update('reorder.pct', v)} max={100} step={0.1} unit="%" />
        </div>

        <div>
          <h3 className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300" title="Limit throughput using a token bucket filter. Set to 0 for unlimited. TiVo needs at least 1.33x the highest ABR bitrate.">Bandwidth</h3>
          <SliderRow label="Rate Limit" value={config.rate?.kbit ?? 0} onChange={(v) => update('rate.kbit', v)} max={100000} step={100} unit="kbit/s" />
        </div>
      </div>

      {feedback === 'success' && (
        <div className="mt-4 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-2 text-sm font-medium text-green-400">
          Impairments applied successfully
        </div>
      )}
      {feedback === 'error' && (
        <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-400">
          Failed to apply impairments
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={handleApply}
          disabled={applying}
          className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {applying ? 'Applying...' : dirty ? 'Apply *' : 'Apply'}
        </button>
        <button
          onClick={handleClear}
          disabled={applying}
          className="rounded-lg border border-gray-300 bg-white px-6 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
        >
          Clear All
        </button>
        {states && selectedInterface && (() => {
          const st = states.find((s) => s.interface === selectedInterface);
          return st?.active ? (
            <span className="ml-2 rounded-full bg-yellow-500/20 px-3 py-1 text-xs font-medium text-yellow-400">
              Active on {selectedInterface}
            </span>
          ) : (
            <span className="ml-2 rounded-full bg-gray-500/20 px-3 py-1 text-xs font-medium text-gray-500">
              No impairments active
            </span>
          );
        })()}
      </div>
    </div>
  );
}
