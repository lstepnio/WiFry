import { useCallback, useState } from 'react';
import type { Profile } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import { useConfirm } from '../hooks/useConfirm';
import { useNotification } from '../hooks/useNotification';

const CATEGORY_COLORS: Record<string, string> = {
  network: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  wifi: 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
  dns: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300',
  combined: 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
  scenario: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
};

export default function ProfileManager() {
  const confirm = useConfirm();
  const { notify } = useNotification();
  const fetcher = useCallback(() => api.getProfiles(), []);
  const { data, refresh } = useApi(fetcher);
  const [applying, setApplying] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>('');

  const allProfiles = data?.profiles ?? [];
  const profiles = filterCategory
    ? allProfiles.filter((profile) => profile.category === filterCategory)
    : allProfiles;

  const categories = [...new Set(allProfiles.map((profile) => profile.category || 'network'))];

  const handleApply = async (name: string) => {
    setApplying(name);
    try {
      await api.applyProfile(name);
      window.dispatchEvent(new CustomEvent('wifry:refresh'));
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to apply profile', 'error');
    } finally {
      setApplying(null);
    }
  };

  const handleDelete = async (profile: Profile) => {
    if (profile.builtin) return;
    if (!await confirm({ title: 'Delete Profile', message: `Delete profile "${profile.name}"?`, confirmLabel: 'Delete', confirmTone: 'danger' })) return;
    try {
      await api.deleteProfile(profile.name);
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to delete', 'error');
    }
  };

  const handleDeleteAllCustom = async () => {
    const customProfiles = allProfiles.filter(p => !p.builtin);
    if (customProfiles.length === 0) {
      notify('No custom profiles to delete.', 'info');
      return;
    }
    if (!await confirm({ title: 'Delete All Custom Profiles', message: `Delete all ${customProfiles.length} custom profile(s)? Built-in profiles will not be affected.`, confirmLabel: 'Delete All', confirmTone: 'danger' })) return;
    try {
      for (const p of customProfiles) {
        await api.deleteProfile(p.name);
      }
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to delete some profiles', 'error');
      refresh();
    }
  };

  const formatConfig = (profile: Profile): string => {
    const parts: string[] = [];
    if (profile.config?.delay?.ms) parts.push(`${profile.config.delay.ms}ms delay`);
    if (profile.config?.delay?.jitter_ms) parts.push(`${profile.config.delay.jitter_ms}ms jitter`);
    if (profile.config?.loss?.pct) parts.push(`${profile.config.loss.pct}% loss`);
    if (profile.config?.rate?.kbit) parts.push(`${profile.config.rate.kbit} kbit/s`);

    // WiFi impairments summary
    const wifi = profile.wifi_config;
    if (wifi) {
      if (wifi.tx_power?.enabled) parts.push(`TX ${wifi.tx_power.power_dbm}dBm`);
      if (wifi.channel_interference?.enabled) parts.push('CH interference');
      if (wifi.periodic_disconnect?.enabled) parts.push(`disconnect/${wifi.periodic_disconnect.interval_secs}s`);
      if (wifi.broadcast_storm?.enabled) parts.push('broadcast storm');
      if (wifi.rate_limit?.enabled) parts.push(`rate cap ${wifi.rate_limit.legacy_rate_mbps}Mbps`);
      if (wifi.dhcp_disruption?.enabled) parts.push(`DHCP ${wifi.dhcp_disruption.mode}`);
      if (wifi.band_switch?.enabled) parts.push(`band→${wifi.band_switch.target_band}`);
    }

    // DNS impairments summary
    const dns = profile.dns_config;
    if (dns?.enabled) {
      const dParts: string[] = [];
      if (dns.impairments?.delay_ms) dParts.push(`${dns.impairments.delay_ms}ms`);
      if (dns.impairments?.failure_rate_pct) dParts.push(`${dns.impairments.failure_rate_pct}% drop`);
      if (dns.impairments?.servfail_rate_pct) dParts.push(`${dns.impairments.servfail_rate_pct}% SERVFAIL`);
      if (dns.impairments?.nxdomain_domains?.length) dParts.push(`${dns.impairments.nxdomain_domains.length} NXDOMAIN`);
      if (dns.impairments?.ttl_override) dParts.push(`TTL ${dns.impairments.ttl_override}s`);
      parts.push(`DNS: ${dParts.join(', ') || dns.upstream?.provider || 'enabled'}`);
    }

    return parts.join(', ') || 'No impairment';
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Profiles</h2>
          <p className="text-xs text-gray-500">One-click presets combining network and WiFi impairments. Built-in profiles simulate real-world conditions.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              if (!await confirm({ title: 'Clear All Impairments', message: 'Clear ALL impairments (network, WiFi, DNS)? This will stop all active impairments.', confirmLabel: 'Clear All', confirmTone: 'danger' })) return;
              try {
                await Promise.all([
                  api.clearAllImpairments(),
                  fetch('/api/v1/wifi-impairments', { method: 'DELETE' }),
                  fetch('/api/v1/dns/disable', { method: 'POST' }),
                ]);
                window.dispatchEvent(new CustomEvent('wifry:refresh'));
              } catch { notify('Failed to clear some impairments', 'error'); }
            }}
            className="rounded border border-yellow-300 px-3 py-1 text-xs font-medium text-yellow-600 hover:bg-yellow-50 dark:border-yellow-700 dark:text-yellow-400"
          >
            Clear All Impairments
          </button>
          {allProfiles.some(p => !p.builtin) && (
            <button
              onClick={handleDeleteAllCustom}
              className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
            >
              Delete All Custom
            </button>
          )}
        {categories.length > 1 && (
          <div className="flex gap-1">
            <button
              onClick={() => setFilterCategory('')}
              className={`rounded-full px-3 py-1 text-xs font-medium ${!filterCategory ? 'bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-white' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}`}
            >
              All ({allProfiles.length})
            </button>
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setFilterCategory(filterCategory === cat ? '' : cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${filterCategory === cat ? CATEGORY_COLORS[cat] || 'bg-gray-200' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
        </div>
      </div>

      <div className="space-y-1">
        {profiles.map((profile) => (
          <div
            key={profile.name}
            className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium text-gray-900 dark:text-white">{profile.name}</span>
                {profile.category && profile.category !== 'network' && (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium capitalize ${CATEGORY_COLORS[profile.category] || ''}`}>
                    {profile.category}
                  </span>
                )}
                {profile.dns_config?.enabled && (
                  <span className="rounded bg-cyan-900 px-1.5 py-0.5 text-[10px] text-cyan-300">DNS</span>
                )}
                <span className="ml-1 truncate text-xs text-gray-500">{formatConfig(profile)}</span>
              </div>
            </div>
            <div className="ml-3 flex gap-2">
              <button
                onClick={() => handleApply(profile.name)}
                disabled={applying === profile.name}
                className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {applying === profile.name ? 'Applying...' : 'Apply'}
              </button>
              {!profile.builtin && (
                <button
                  onClick={() => handleDelete(profile)}
                  className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
                >
                  Delete
                </button>
              )}
            </div>
          </div>
        ))}

        {profiles.length === 0 && (
          <p className="text-sm text-gray-500">No profiles match this filter.</p>
        )}
      </div>
    </div>
  );
}
