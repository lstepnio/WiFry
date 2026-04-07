import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useConfirm } from '../hooks/useConfirm';
import { useNotification } from '../hooks/useNotification';

interface TeleportProfile {
  id: string;
  name: string;
  description: string;
  market: string;
  region: string;
  vpn_type: string;
  tags: string[];
  expected_country: string;
}

interface TeleportStatus {
  connected: boolean;
  active_profile: string | null;
  active_profile_name: string;
  market: string;
  region: string;
  vpn_type: string;
  public_ip: string;
  connected_at: string | null;
}

interface VerifyResult {
  connected: boolean;
  public_ip: string;
  country: string;
  city?: string;
  org?: string;
  verified: boolean;
}

export default function TeleportPanel() {
  const confirmAction = useConfirm();
  const { notify } = useNotification();
  const statusFetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/teleport/status');
      if (!res.ok) return { connected: false } as TeleportStatus;
      return res.json();
    } catch { return { connected: false } as TeleportStatus; }
  }, []);
  const { data: status, refresh: refreshStatus } = useApi<TeleportStatus>(statusFetcher, 5000);

  const profilesFetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/teleport/profiles');
      if (!res.ok) return [];
      return res.json();
    } catch { return []; }
  }, []);
  const { data: profiles, refresh: refreshProfiles } = useApi<TeleportProfile[]>(profilesFetcher);

  const [connecting, setConnecting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [newMarket, setNewMarket] = useState('');
  const [newRegion, setNewRegion] = useState('');
  const [newConfig, setNewConfig] = useState('');
  const [newVpnType, setNewVpnType] = useState('wireguard');

  const connect = async (profileId: string) => {
    setConnecting(true);
    try {
      await fetch(`/api/v1/teleport/connect/${profileId}`, { method: 'POST' });
      refreshStatus();
    } catch { notify('Connection failed', 'error'); }
    finally { setConnecting(false); }
  };

  const disconnect = async () => {
    setConnecting(true);
    try {
      await fetch('/api/v1/teleport/disconnect', { method: 'POST' });
      refreshStatus();
      setVerifyResult(null);
    } catch { notify('Disconnect failed', 'error'); }
    finally { setConnecting(false); }
  };

  const verify = async () => {
    setVerifying(true);
    try {
      const res = await fetch('/api/v1/teleport/verify');
      setVerifyResult(await res.json());
    } catch { notify('Verify failed', 'error'); }
    finally { setVerifying(false); }
  };

  const addProfile = async () => {
    if (!newName || !newConfig) return;
    await fetch('/api/v1/teleport/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newName,
        market: newMarket,
        region: newRegion,
        vpn_type: newVpnType,
        config_contents: newConfig,
      }),
    });
    setShowAdd(false);
    setNewName('');
    setNewMarket('');
    setNewRegion('');
    setNewConfig('');
    refreshProfiles();
  };

  const deleteProfile = async (id: string) => {
    if (!await confirmAction({ title: 'Delete Profile', message: 'Delete this teleport profile?', confirmLabel: 'Delete', confirmTone: 'danger' })) return;
    await fetch(`/api/v1/teleport/profiles/${id}`, { method: 'DELETE' });
    refreshProfiles();
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Teleport</h2>
          <p className="text-xs text-gray-500">Route STB traffic through remote networks for geo/market testing</p>
        </div>
        {status?.connected ? (
          <button onClick={disconnect} disabled={connecting}
            className="rounded-lg bg-red-600 px-5 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
            {connecting ? '...' : 'Disconnect'}
          </button>
        ) : (
          <button onClick={() => setShowAdd(!showAdd)}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300">
            {showAdd ? 'Cancel' : '+ Add Profile'}
          </button>
        )}
      </div>

      {/* Active connection */}
      {status?.connected && (
        <div className="mb-4 rounded-lg border border-green-600 bg-green-950/30 p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
                <span className="text-sm font-medium text-green-300">Connected: {status.active_profile_name}</span>
              </div>
              <div className="mt-1 text-xs text-gray-400">
                Market: {status.market || '—'} | Region: {status.region || '—'} | VPN: {status.vpn_type}
                {status.public_ip && <> | IP: <span className="font-mono">{status.public_ip}</span></>}
              </div>
            </div>
            <button onClick={verify} disabled={verifying}
              className="rounded bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50">
              {verifying ? 'Checking...' : 'Verify'}
            </button>
          </div>
          {verifyResult && (
            <div className="mt-2 rounded bg-gray-800/50 p-2 text-xs">
              {verifyResult.verified ? (
                <div className="text-green-300">
                  Public IP: <span className="font-mono">{verifyResult.public_ip}</span>
                  {verifyResult.country && <> | Country: {verifyResult.country}</>}
                  {verifyResult.city && <> | City: {verifyResult.city}</>}
                  {verifyResult.org && <> | ISP: {verifyResult.org}</>}
                </div>
              ) : (
                <div className="text-red-400">Verification failed — VPN may not be routing traffic correctly</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Add profile form */}
      {showAdd && (
        <div className="mb-4 space-y-3 rounded-lg border border-blue-700 bg-blue-950/30 p-4">
          <p className="text-xs text-gray-400">Paste the WireGuard or OpenVPN config file provided by your network/secops team.</p>
          <div className="grid grid-cols-3 gap-2">
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Profile name (e.g. US East)"
              className="rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-white" />
            <input value={newMarket} onChange={e => setNewMarket(e.target.value)} placeholder="Market (e.g. us-east)"
              className="rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-white" />
            <input value={newRegion} onChange={e => setNewRegion(e.target.value)} placeholder="Region (e.g. New York)"
              className="rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-white" />
          </div>
          <select value={newVpnType} onChange={e => setNewVpnType(e.target.value)}
            className="rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-white">
            <option value="wireguard">WireGuard (.conf)</option>
            <option value="openvpn">OpenVPN (.ovpn)</option>
          </select>
          <textarea value={newConfig} onChange={e => setNewConfig(e.target.value)}
            placeholder={newVpnType === 'wireguard' ? '[Interface]\nPrivateKey = ...\nAddress = ...\n\n[Peer]\nPublicKey = ...\nEndpoint = ...\nAllowedIPs = 0.0.0.0/0' : '# OpenVPN config...'}
            rows={6}
            className="w-full rounded border border-gray-600 bg-gray-800 p-3 font-mono text-xs text-white" />
          <button onClick={addProfile} disabled={!newName || !newConfig}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            Save Profile
          </button>
        </div>
      )}

      {/* Profile list */}
      <div className="space-y-2">
        {(profiles ?? []).map(p => (
          <div key={p.id} className={`flex items-center justify-between rounded-lg border px-4 py-3 ${
            status?.active_profile === p.id ? 'border-green-600 bg-green-950/20' : 'border-gray-700 bg-gray-800/50'
          }`}>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-200">{p.name}</span>
                <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] uppercase text-gray-400">{p.vpn_type}</span>
                {p.market && <span className="rounded bg-indigo-900 px-1.5 py-0.5 text-[10px] text-indigo-300">{p.market}</span>}
              </div>
              {p.description && <div className="text-xs text-gray-500">{p.description}</div>}
            </div>
            <div className="flex gap-2">
              {status?.active_profile !== p.id && (
                <button onClick={() => connect(p.id)} disabled={connecting}
                  className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                  {connecting ? '...' : 'Connect'}
                </button>
              )}
              <button onClick={() => deleteProfile(p.id)}
                className="rounded border border-red-700 px-2 py-1 text-xs text-red-400 hover:bg-red-950">
                Delete
              </button>
            </div>
          </div>
        ))}
        {(profiles ?? []).length === 0 && !showAdd && (
          <p className="py-4 text-center text-xs text-gray-500">
            No teleport profiles. Click "+ Add Profile" and paste a VPN config from your secops team.
          </p>
        )}
      </div>
    </div>
  );
}
