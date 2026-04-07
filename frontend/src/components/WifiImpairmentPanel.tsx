import { useCallback, useEffect, useState } from 'react';
import {
  clearWifiImpairments,
  getWifiImpairmentCapabilities,
  getWifiImpairments,
  updateWifiImpairments,
} from '../api/client';
import { useApi } from '../hooks/useApi';
import type { WifiCapabilities, WifiImpairmentState } from '../types';

interface ToggleRowProps {
  label: string;
  description: string;
  id: string;
  enabled: boolean;
  onToggle: (id: string, enabled: boolean) => void;
  disabled?: boolean;
  disabledReason?: string;
  children?: React.ReactNode;
}

function ToggleRow({ label, description, id, enabled, onToggle, disabled, disabledReason, children }: ToggleRowProps) {
  return (
    <div className={`rounded-lg border p-4 ${
      disabled ? 'border-gray-800 bg-gray-900/50 opacity-60' :
      enabled ? 'border-orange-500 bg-orange-950/30' : 'border-gray-700 bg-gray-800/50'
    }`}>
      <div className="flex items-center justify-between">
        <div>
          <div className={`text-sm font-medium ${disabled ? 'text-gray-500' : 'text-gray-200'}`}>{label}</div>
          <div className="text-xs text-gray-500">{description}</div>
          {disabled && disabledReason && (
            <div className="mt-1 text-xs text-yellow-500/80">{disabledReason}</div>
          )}
        </div>
        <label className={`relative inline-flex items-center ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}>
          <input type="checkbox" checked={enabled} onChange={(e) => !disabled && onToggle(id, e.target.checked)} disabled={disabled} className="peer sr-only" />
          <div className={`peer h-6 w-11 rounded-full after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all ${
            disabled ? 'bg-gray-700' : 'bg-gray-600 peer-checked:bg-orange-500 peer-checked:after:translate-x-full'
          }`} />
        </label>
      </div>
      {enabled && !disabled && children && <div className="mt-3 space-y-2">{children}</div>}
    </div>
  );
}

function Slider({ label, value, onChange, min, max, step = 1, unit }: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step?: number; unit: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 text-xs text-gray-400">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-orange-500" />
      <span className="w-20 text-right text-xs font-mono text-gray-300">{value} {unit}</span>
    </div>
  );
}

export default function WifiImpairmentPanel() {
  const fetcher = useCallback(() => getWifiImpairments(), []);
  const { data: state, refresh } = useApi<WifiImpairmentState>(fetcher, 5000);

  const capsFetcher = useCallback(async () => {
    try {
      return await getWifiImpairmentCapabilities();
    } catch {
      return null;
    }
  }, []);
  const { data: caps } = useApi<WifiCapabilities | null>(capsFetcher);

  const isSupported = (featureId: string): boolean => {
    if (!caps?.features) return true; // Default to enabled while loading
    return caps.features[featureId]?.supported !== false;
  };

  const disabledReason = (featureId: string): string => {
    if (!caps?.features) return '';
    return caps.features[featureId]?.reason || '';
  };

  const [config, setConfig] = useState<Record<string, Record<string, unknown>>>({
    channel_interference: { enabled: false, beacon_interval_ms: 100, rts_threshold: 2347 },
    tx_power: { enabled: false, power_dbm: 20 },
    band_switch: { enabled: false, target_band: '2.4GHz', target_channel: 0, bounce_enabled: false, bounce_interval_secs: 60, bounce_band_a: '2.4GHz', bounce_channel_a: 6, bounce_band_b: '5GHz', bounce_channel_b: 36, channel_hop_enabled: false, channel_hop_interval_secs: 30, channel_hop_list: '1,6,11' },
    deauth: { enabled: false, target_mac: '', reason_code: 3 },
    dhcp_disruption: { enabled: false, mode: 'delay', delay_secs: 30 },
    broadcast_storm: { enabled: false, packets_per_sec: 100, packet_size_bytes: 512 },
    rate_limit: { enabled: false, legacy_rate_mbps: 54, ht_mcs: -1, vht_mcs: -1 },
    periodic_disconnect: { enabled: false, interval_secs: 300, disconnect_duration_secs: 5, target_mac: '' },
  });
  const [applying, setApplying] = useState(false);
  const [feedback, setFeedback] = useState<'success' | 'error' | null>(null);
  const [dirty, setDirty] = useState(false);

  // Sync server state to local config when not dirty
  useEffect(() => {
    if (dirty || !state?.config) return;
    const serverConfig = state.config as Record<string, Record<string, unknown>>;
    setConfig(prev => {
      const merged = { ...prev };
      for (const key of Object.keys(merged)) {
        if (serverConfig[key]) {
          merged[key] = { ...merged[key], ...serverConfig[key] };
        }
      }
      return merged;
    });
  }, [state, dirty]);

  const showFeedback = (type: 'success' | 'error') => {
    setFeedback(type);
    setTimeout(() => setFeedback(null), 2000);
  };

  const toggle = (id: string, enabled: boolean) => {
    setDirty(true);
    setConfig(prev => ({ ...prev, [id]: { ...prev[id], enabled } }));
  };

  const updateField = (id: string, field: string, value: unknown) => {
    setDirty(true);
    setConfig(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      await updateWifiImpairments(config);
      setDirty(false);
      showFeedback('success');
      refresh();
    } catch {
      showFeedback('error');
    } finally {
      setApplying(false);
    }
  };

  const handleClear = async () => {
    setApplying(true);
    try {
      await clearWifiImpairments();
      setConfig(prev => {
        const cleared = { ...prev };
        for (const key of Object.keys(cleared)) {
          cleared[key] = { ...cleared[key], enabled: false };
        }
        return cleared;
      });
      setDirty(false);
      showFeedback('success');
      refresh();
    } catch {
      showFeedback('error');
    } finally {
      setApplying(false);
    }
  };

  const activeCount = state?.active_impairments?.length ?? 0;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="flex items-center">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">WiFi Impairments</h2>
            <span className="ml-2 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-gray-700 text-[10px] font-bold text-gray-400" title="WiFi-layer issues that go beyond tc netem. These affect the WiFi radio itself — signal strength, channel interference, deauthentication, DHCP, and more. Enable multiple simultaneously for realistic scenarios.">?</span>
          </div>
          <p className="text-xs text-gray-500">WiFi-layer issues beyond packet loss and delay</p>
        </div>
        {activeCount > 0 && (
          <span className="rounded-full bg-orange-100 px-3 py-1 text-xs font-medium text-orange-700 dark:bg-orange-900 dark:text-orange-300">
            {activeCount} active
          </span>
        )}
      </div>

      <div className="space-y-3">
        <ToggleRow label="Channel Interference" description="Simulate co-channel congestion via beacon interval and RTS threshold"
          id="channel_interference" enabled={!!config.channel_interference?.enabled} onToggle={toggle}
          disabled={!isSupported('channel_interference')} disabledReason={disabledReason('channel_interference')}>
          <Slider label="Beacon Interval" value={config.channel_interference?.beacon_interval_ms as number ?? 100}
            onChange={(v) => updateField('channel_interference', 'beacon_interval_ms', v)} min={15} max={2000} unit="ms" />
          <Slider label="RTS Threshold" value={config.channel_interference?.rts_threshold as number ?? 2347}
            onChange={(v) => updateField('channel_interference', 'rts_threshold', v)} min={1} max={2347} unit="bytes" />
        </ToggleRow>

        <ToggleRow label="TX Power Reduction" description="Reduce AP signal strength to simulate edge-of-coverage"
          disabled={!isSupported('tx_power')} disabledReason={disabledReason('tx_power')}
          id="tx_power" enabled={!!config.tx_power?.enabled} onToggle={toggle}>
          <Slider label="TX Power" value={config.tx_power?.power_dbm as number ?? 20}
            onChange={(v) => updateField('tx_power', 'power_dbm', v)} min={0} max={30} unit="dBm" />
        </ToggleRow>

        <ToggleRow label="Band Switch / Channel Hop" description="One-shot switch, periodic band bouncing, or channel hopping"
          disabled={!isSupported('band_switch')} disabledReason={disabledReason('band_switch')}
          id="band_switch" enabled={!!config.band_switch?.enabled} onToggle={toggle}>
          {/* One-shot switch */}
          <div className="mb-2 text-[10px] font-medium text-gray-500">One-shot switch</div>
          <div className="flex gap-2">
            <select value={config.band_switch?.target_band as string ?? '2.4GHz'}
              onChange={(e) => updateField('band_switch', 'target_band', e.target.value)}
              className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white">
              <option value="2.4GHz">2.4 GHz</option>
              <option value="5GHz">5 GHz</option>
            </select>
            <input type="number" value={config.band_switch?.target_channel as number ?? 0} min={0} max={165}
              onChange={(e) => updateField('band_switch', 'target_channel', Number(e.target.value))}
              placeholder="Channel (0=auto)"
              className="w-24 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white" />
          </div>

          {/* Band bounce */}
          <div className="mt-3 rounded border border-gray-700 p-2">
            <label className="flex items-center gap-2 text-xs text-gray-300">
              <input type="checkbox" checked={!!config.band_switch?.bounce_enabled}
                onChange={e => updateField('band_switch', 'bounce_enabled', e.target.checked)}
                className="h-3 w-3 accent-orange-500" />
              Band Bounce (cycle between 2.4GHz and 5GHz)
            </label>
            {Boolean(config.band_switch?.bounce_enabled) && (
              <div className="mt-2 space-y-2">
                <Slider label="Interval" value={Number(config.band_switch?.bounce_interval_secs ?? 60)}
                  onChange={v => updateField('band_switch', 'bounce_interval_secs', v)} min={10} max={600} step={5} unit="sec" />
                <div className="flex gap-2 text-xs">
                  <div>
                    <span className="text-gray-500">Band A:</span>
                    <select value={config.band_switch?.bounce_band_a as string ?? '2.4GHz'}
                      onChange={e => updateField('band_switch', 'bounce_band_a', e.target.value)}
                      className="ml-1 rounded border border-gray-600 bg-gray-800 px-1 py-0.5 text-white">
                      <option value="2.4GHz">2.4GHz</option><option value="5GHz">5GHz</option>
                    </select>
                    <input type="number" value={config.band_switch?.bounce_channel_a as number ?? 6} min={0} max={165}
                      onChange={e => updateField('band_switch', 'bounce_channel_a', Number(e.target.value))}
                      className="ml-1 w-12 rounded border border-gray-600 bg-gray-800 px-1 py-0.5 text-white" />
                  </div>
                  <div>
                    <span className="text-gray-500">Band B:</span>
                    <select value={config.band_switch?.bounce_band_b as string ?? '5GHz'}
                      onChange={e => updateField('band_switch', 'bounce_band_b', e.target.value)}
                      className="ml-1 rounded border border-gray-600 bg-gray-800 px-1 py-0.5 text-white">
                      <option value="2.4GHz">2.4GHz</option><option value="5GHz">5GHz</option>
                    </select>
                    <input type="number" value={config.band_switch?.bounce_channel_b as number ?? 36} min={0} max={165}
                      onChange={e => updateField('band_switch', 'bounce_channel_b', Number(e.target.value))}
                      className="ml-1 w-12 rounded border border-gray-600 bg-gray-800 px-1 py-0.5 text-white" />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Channel hop */}
          <div className="mt-2 rounded border border-gray-700 p-2">
            <label className="flex items-center gap-2 text-xs text-gray-300">
              <input type="checkbox" checked={!!config.band_switch?.channel_hop_enabled}
                onChange={e => updateField('band_switch', 'channel_hop_enabled', e.target.checked)}
                className="h-3 w-3 accent-orange-500" />
              Channel Hop (cycle through channels within a band)
            </label>
            {Boolean(config.band_switch?.channel_hop_enabled) && (
              <div className="mt-2 space-y-2">
                <Slider label="Interval" value={Number(config.band_switch?.channel_hop_interval_secs ?? 30)}
                  onChange={v => updateField('band_switch', 'channel_hop_interval_secs', v)} min={5} max={300} step={5} unit="sec" />
                <div>
                  <label className="text-[10px] text-gray-500">Channels (comma-separated)</label>
                  <input value={config.band_switch?.channel_hop_list as string ?? '1,6,11'}
                    onChange={e => updateField('band_switch', 'channel_hop_list', e.target.value)}
                    placeholder="1,6,11"
                    className="w-full rounded border border-gray-600 bg-gray-800 px-2 py-1 font-mono text-xs text-white" />
                </div>
              </div>
            )}
          </div>
        </ToggleRow>

        <ToggleRow label="Deauthentication" description="Force client disconnect (one-shot)"
          disabled={!isSupported('deauth')} disabledReason={disabledReason('deauth')}
          id="deauth" enabled={!!config.deauth?.enabled} onToggle={toggle}>
          <input value={config.deauth?.target_mac as string ?? ''} placeholder="MAC address (empty = all)"
            onChange={(e) => updateField('deauth', 'target_mac', e.target.value)}
            className="w-full rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs font-mono text-white" />
        </ToggleRow>

        <ToggleRow label="DHCP Disruption" description="Delay, fail, or change DHCP responses"
          disabled={!isSupported('dhcp_disruption')} disabledReason={disabledReason('dhcp_disruption')}
          id="dhcp_disruption" enabled={!!config.dhcp_disruption?.enabled} onToggle={toggle}>
          <select value={config.dhcp_disruption?.mode as string ?? 'delay'}
            onChange={(e) => updateField('dhcp_disruption', 'mode', e.target.value)}
            className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white">
            <option value="delay">Delay New Connections</option>
            <option value="fail">Block All DHCP (new + renewals)</option>
            <option value="change_ip">Force New IP Range</option>
          </select>
          {config.dhcp_disruption?.mode === 'delay' && (
            <>
              <Slider label="Delay" value={config.dhcp_disruption?.delay_secs as number ?? 30}
                onChange={(v) => updateField('dhcp_disruption', 'delay_secs', v)} min={1} max={300} unit="sec" />
              <p className="mt-1 text-xs text-gray-500">Delays DHCPDISCOVER only. Existing clients must forget the network or have leases cleared to be affected.</p>
            </>
          )}
          {config.dhcp_disruption?.mode === 'fail' && (
            <p className="mt-1 text-xs text-gray-500">Drops all DHCP replies via iptables. Affects both new connections and lease renewals.</p>
          )}
          {config.dhcp_disruption?.mode === 'change_ip' && (
            <p className="mt-1 text-xs text-gray-500">Switches DHCP range so clients get a different IP subnet on renewal.</p>
          )}
        </ToggleRow>

        <ToggleRow label="Broadcast Storm" description="Inject broadcast traffic to consume WiFi airtime"
          disabled={!isSupported('broadcast_storm')} disabledReason={disabledReason('broadcast_storm')}
          id="broadcast_storm" enabled={!!config.broadcast_storm?.enabled} onToggle={toggle}>
          <Slider label="Packets/sec" value={config.broadcast_storm?.packets_per_sec as number ?? 100}
            onChange={(v) => updateField('broadcast_storm', 'packets_per_sec', v)} min={1} max={10000} step={10} unit="pps" />
          <Slider label="Packet Size" value={config.broadcast_storm?.packet_size_bytes as number ?? 512}
            onChange={(v) => updateField('broadcast_storm', 'packet_size_bytes', v)} min={64} max={1500} unit="bytes" />
        </ToggleRow>

        <ToggleRow label="Rate Limiting" description="Force lower WiFi PHY rates (simulate distance)"
          disabled={!isSupported('rate_limit')} disabledReason={disabledReason('rate_limit')}
          id="rate_limit" enabled={!!config.rate_limit?.enabled} onToggle={toggle}>
          <Slider label="Max Legacy Rate" value={config.rate_limit?.legacy_rate_mbps as number ?? 54}
            onChange={(v) => updateField('rate_limit', 'legacy_rate_mbps', v)} min={1} max={54} unit="Mbps" />
          <Slider label="Max HT MCS" value={config.rate_limit?.ht_mcs as number ?? -1}
            onChange={(v) => updateField('rate_limit', 'ht_mcs', v)} min={-1} max={31} unit="" />
        </ToggleRow>

        <ToggleRow label="Periodic Disconnects" description="Schedule regular WiFi drops"
          disabled={!isSupported('periodic_disconnect')} disabledReason={disabledReason('periodic_disconnect')}
          id="periodic_disconnect" enabled={!!config.periodic_disconnect?.enabled} onToggle={toggle}>
          <Slider label="Interval" value={config.periodic_disconnect?.interval_secs as number ?? 300}
            onChange={(v) => updateField('periodic_disconnect', 'interval_secs', v)} min={10} max={3600} step={10} unit="sec" />
          <Slider label="Duration" value={config.periodic_disconnect?.disconnect_duration_secs as number ?? 5}
            onChange={(v) => updateField('periodic_disconnect', 'disconnect_duration_secs', v)} min={1} max={60} unit="sec" />
          <input value={config.periodic_disconnect?.target_mac as string ?? ''} placeholder="Target MAC (empty = all)"
            onChange={(e) => updateField('periodic_disconnect', 'target_mac', e.target.value)}
            className="w-full rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs font-mono text-white" />
        </ToggleRow>
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
        <button onClick={handleApply} disabled={applying}
          className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {applying ? 'Applying...' : dirty ? 'Apply *' : 'Apply'}
        </button>
        <button onClick={handleClear} disabled={applying}
          className="rounded-lg border border-gray-300 bg-white px-6 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300">
          Clear All
        </button>
        {activeCount > 0 && (
          <span className="rounded-full bg-yellow-500/20 px-3 py-1 text-xs font-medium text-yellow-400">
            {activeCount} active
          </span>
        )}
      </div>

      {state?.disconnect_count ? (
        <div className="mt-3 text-xs text-gray-500">Disconnects triggered: {state.disconnect_count}</div>
      ) : null}
    </div>
  );
}
