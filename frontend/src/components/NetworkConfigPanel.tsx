import { useCallback, useEffect, useState } from 'react';
import { useApi } from '../hooks/useApi';

interface WifiApConfig {
  ssid: string; password: string; channel: number; band: string;
  channel_width: number; hidden: boolean; ip: string; netmask: string;
  dhcp_start: string; dhcp_end: string; country_code: string;
}

interface EthernetConfig {
  mode: string; static_ip: string; static_netmask: string;
  static_gateway: string; static_dns: string;
}

interface FallbackConfig {
  enabled: boolean; ip: string; netmask: string;
}

interface FullNetworkConfig {
  wifi_ap: WifiApConfig; ethernet: EthernetConfig;
  fallback: FallbackConfig; first_boot: boolean;
}

interface NetworkProfile {
  id: string; name: string; description: string;
}

function Input({ label, value, onChange, type = 'text', title = '', disabled = false }: {
  label: string; value: string | number; onChange: (v: string) => void;
  type?: string; title?: string; disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-gray-500" title={title}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} disabled={disabled}
        className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white disabled:opacity-50" />
    </div>
  );
}

export default function NetworkConfigPanel() {
  const configFetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/network-config/current');
      return res.ok ? res.json() : null;
    } catch { return null; }
  }, []);
  const { data: config, refresh } = useApi<FullNetworkConfig>(configFetcher);

  const capsFetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/wifi-impairments/capabilities');
      return res.ok ? res.json() : null;
    } catch { return null; }
  }, []);
  const { data: caps } = useApi<{ features: Record<string, { supported: boolean; reason: string }> }>(capsFetcher);
  const band5ghzSupported = caps?.features?.band_5ghz?.supported !== false;

  const profilesFetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/network-config/profiles');
      return res.ok ? res.json() : [];
    } catch { return []; }
  }, []);
  const { data: profiles, refresh: refreshProfiles } = useApi<NetworkProfile[]>(profilesFetcher);

  const [ap, setAp] = useState<WifiApConfig | null>(null);
  const [eth, setEth] = useState<EthernetConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (config) {
      setAp(config.wifi_ap);
      setEth(config.ethernet);
    }
  }, [config]);

  const applyConfig = async () => {
    if (!ap || !eth) return;
    setSaving(true);
    setMessage('');
    try {
      const res = await fetch('/api/v1/network-config/apply', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wifi_ap: ap,
          ethernet: eth,
          fallback: config?.fallback ?? { enabled: true, ip: '169.254.42.1', netmask: '255.255.0.0' },
          first_boot: false,
        }),
      });
      if (res.ok) {
        setMessage('Configuration applied successfully');
        refresh();
      } else {
        setMessage('Failed to apply configuration');
      }
    } catch { setMessage('Error applying config'); }
    finally { setSaving(false); }
  };

  const resetDefaults = async () => {
    if (!confirm('Reset to factory defaults? WiFi SSID will be "WiFry" with password "wifry1234".')) return;
    await fetch('/api/v1/network-config/reset-defaults', { method: 'POST' });
    refresh();
    setMessage('Reset to defaults');
  };

  const saveProfile = async () => {
    const name = prompt('Profile name:');
    if (!name) return;
    await fetch('/api/v1/network-config/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    refreshProfiles();
  };

  const applyProfile = async (id: string) => {
    await fetch(`/api/v1/network-config/profiles/${id}/apply`, { method: 'POST' });
    refresh();
    setMessage('Profile applied');
  };

  if (!config || !ap || !eth) return null;

  return (
    <div className="space-y-4">
      {/* First boot banner */}
      {config.first_boot && (
        <div className="rounded-lg border border-yellow-500 bg-yellow-950/40 p-4">
          <h3 className="text-sm font-bold text-yellow-300">Welcome to WiFry - IP Video Edition</h3>
          <p className="mt-1 text-xs text-yellow-200">
            You're running with default settings. It's recommended to configure your WiFi hotspot
            and Ethernet settings before testing. The current defaults are:
          </p>
          <ul className="mt-2 space-y-0.5 text-xs text-yellow-300">
            <li>WiFi SSID: <strong>WiFry</strong> / Password: <strong>wifry1234</strong></li>
            <li>WiFi IP: <strong>192.168.4.1</strong> (channel 6, 2.4GHz)</li>
            <li>Ethernet: <strong>DHCP</strong></li>
            <li>Fallback IP: <strong>169.254.42.1</strong> (always reachable on Ethernet)</li>
          </ul>
          <p className="mt-2 text-xs text-yellow-200">
            Change settings below, or load a saved profile if you have one.
          </p>
        </div>
      )}

      {/* WiFi AP config */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-1 text-lg font-semibold text-gray-900 dark:text-white">WiFi Hotspot</h2>
        <p className="mb-4 text-xs text-gray-500">Configure the WiFi access point that STBs connect to.</p>

        {message && (
          <div className="mb-4 rounded bg-blue-950/30 px-3 py-2 text-xs text-blue-300">{message}</div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Input label="SSID" value={ap.ssid} onChange={v => setAp({...ap, ssid: v})} title="WiFi network name" />
          <Input label="Password" value={ap.password} onChange={v => setAp({...ap, password: v})} type="password" title="WPA2 password (min 8 chars)" />
          <div>
            <label className="mb-1 block text-xs text-gray-500">Band</label>
            <select value={ap.band} onChange={e => setAp({...ap, band: e.target.value})}
              className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white">
              <option value="2.4GHz">2.4 GHz</option>
              <option value="5GHz" disabled={!band5ghzSupported}>
                5 GHz{!band5ghzSupported ? ' (not supported on this hardware)' : ''}
              </option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">Channel Width</label>
            <select value={ap.channel_width || 20} onChange={e => setAp({...ap, channel_width: parseInt(e.target.value)})}
              className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white">
              <option value={20}>20 MHz</option>
              <option value={40}>40 MHz (HT40)</option>
              {ap.band === '5GHz' && <option value={80}>80 MHz (VHT80)</option>}
            </select>
          </div>
          <Input label="Channel" value={ap.channel} onChange={v => setAp({...ap, channel: parseInt(v) || 0})} type="number" title="0 = auto, 1-11 for 2.4GHz, 36-165 for 5GHz" />
          <Input label="AP IP Address" value={ap.ip} onChange={v => setAp({...ap, ip: v})} title="IP address of the WiFry RPi on the WiFi network" />
          <Input label="Country Code" value={ap.country_code} onChange={v => setAp({...ap, country_code: v})} title="Required for 5GHz. US, GB, DE, JP, etc." />
          <Input label="DHCP Start" value={ap.dhcp_start} onChange={v => setAp({...ap, dhcp_start: v})} title="First IP assigned to WiFi clients" />
          <Input label="DHCP End" value={ap.dhcp_end} onChange={v => setAp({...ap, dhcp_end: v})} title="Last IP assigned to WiFi clients" />
        </div>
      </div>

      {/* Ethernet config */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-1 text-lg font-semibold text-gray-900 dark:text-white">Ethernet (Uplink)</h2>
        <p className="mb-4 text-xs text-gray-500">Configure how the RPi connects to your upstream network. Fallback IP is always active to prevent lockout.</p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs text-gray-500">Mode</label>
            <select value={eth.mode} onChange={e => setEth({...eth, mode: e.target.value})}
              className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white">
              <option value="dhcp">DHCP (auto)</option>
              <option value="static">Static IP</option>
            </select>
          </div>
          {eth.mode === 'static' && (
            <>
              <Input label="Static IP" value={eth.static_ip} onChange={v => setEth({...eth, static_ip: v})} />
              <Input label="Netmask" value={eth.static_netmask} onChange={v => setEth({...eth, static_netmask: v})} />
              <Input label="Gateway" value={eth.static_gateway} onChange={v => setEth({...eth, static_gateway: v})} />
              <Input label="DNS Server" value={eth.static_dns} onChange={v => setEth({...eth, static_dns: v})} />
            </>
          )}
        </div>

        <div className="mt-3 rounded border border-gray-700 bg-gray-800/50 px-3 py-2 text-xs text-gray-400">
          <strong className="text-gray-300">Fallback IP: {config.fallback.ip}</strong> — always reachable on the Ethernet port regardless of config.
          Connect a laptop directly to the RPi and navigate to <span className="font-mono text-blue-400">http://{config.fallback.ip}:8080</span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <button onClick={applyConfig} disabled={saving}
          className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {saving ? 'Applying...' : 'Apply Configuration'}
        </button>
        <button onClick={saveProfile}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300">
          Save as Profile
        </button>
        <button onClick={resetDefaults}
          className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400">
          Reset Defaults
        </button>
      </div>

      {/* Saved profiles */}
      {(profiles ?? []).length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <h3 className="mb-2 text-sm font-medium text-gray-500">Saved Network Profiles</h3>
          <div className="space-y-1">
            {(profiles ?? []).map(p => (
              <div key={p.id} className="flex items-center justify-between rounded border border-gray-700 bg-gray-800/50 px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-300">{p.name}</span>
                  {(p as any).is_boot_profile && <span className="rounded bg-yellow-900 px-1.5 py-0.5 text-[9px] text-yellow-300">boot profile</span>}
                  {p.description && <span className="text-xs text-gray-500">{p.description}</span>}
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => applyProfile(p.id)}
                    className="rounded bg-blue-600 px-2 py-1 text-[10px] text-white hover:bg-blue-700">Apply</button>
                  {!(p as any).is_boot_profile ? (
                    <button onClick={async () => {
                      if (!confirm('Set as boot profile? If WiFi settings are wrong, use fallback IP (169.254.42.1) to recover.')) return;
                      await fetch(`/api/v1/network-config/profiles/${p.id}/set-boot`, { method: 'POST' });
                      refreshProfiles();
                    }} title="Load this profile automatically on boot"
                      className="rounded border border-gray-600 px-2 py-1 text-[10px] text-gray-500 hover:bg-gray-700">Set Boot</button>
                  ) : (
                    <button onClick={async () => {
                      await fetch('/api/v1/network-config/profiles/clear-boot', { method: 'POST' });
                      refreshProfiles();
                    }}
                      className="rounded border border-yellow-700 px-2 py-1 text-[10px] text-yellow-400 hover:bg-yellow-950">Unset Boot</button>
                  )}
                  <button onClick={() => { fetch(`/api/v1/network-config/profiles/${p.id}`, { method: 'DELETE' }); refreshProfiles(); }}
                    className="rounded bg-red-900 px-2 py-1 text-[10px] text-red-300 hover:bg-red-800">Delete</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
