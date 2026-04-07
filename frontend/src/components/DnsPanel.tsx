import { useCallback, useEffect, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useNotification } from '../hooks/useNotification';

interface DnsResolver { address: string; label: string; healthy: boolean; delay_ms: number; }
interface DnsOverride { domain: string; record_type: string; value: string; }
interface DnsQueryLog { timestamp: string; client_ip: string; domain: string; query_type: string; response_code: string; latency_ms: number; resolver_used: string; }
interface DnsStatus { enabled: boolean; running: boolean; upstream_provider: string; upstream_protocol: string; resolver_count: number; healthy_resolvers: number; override_count: number; impairments_active: string[]; query_count: number; }
interface DnsConfig {
  enabled: boolean; listen_port: number; log_queries: boolean;
  upstream: { provider: string; custom_servers: string[]; protocol: string; resolvers: DnsResolver[]; };
  impairments: { delay_ms: number; failure_rate_pct: number; nxdomain_domains: string[]; servfail_rate_pct: number; ttl_override: number; };
  overrides: DnsOverride[];
}

function Slider({ label, value, onChange, min, max, step = 1, unit, title = '' }: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step?: number; unit: string; title?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 text-xs text-gray-400" title={title}>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} className="flex-1 accent-cyan-500" />
      <span className="w-20 text-right text-xs font-mono text-gray-300">{value} {unit}</span>
    </div>
  );
}

export default function DnsPanel() {
  const { notify } = useNotification();
  const statusFetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/dns/status'); return r.ok ? r.json() : null; } catch { return null; }
  }, []);
  const { data: status, refresh } = useApi<DnsStatus>(statusFetcher, 5000);

  const configFetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/dns/config'); return r.ok ? r.json() : null; } catch { return null; }
  }, []);
  const { data: config, refresh: refreshConfig } = useApi<DnsConfig>(configFetcher);

  const logFetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/dns/query-log?limit=20'); return r.ok ? r.json() : []; } catch { return []; }
  }, []);
  const { data: queryLog } = useApi<DnsQueryLog[]>(logFetcher, status?.enabled ? 3000 : 0);

  // Local state
  const [provider, setProvider] = useState('cloudflare');
  const [protocol, setProtocol] = useState('plain');
  const [resolvers, setResolvers] = useState<DnsResolver[]>([]);
  const [delayMs, setDelayMs] = useState(0);
  const [failRate, setFailRate] = useState(0);
  const [servfailRate, setServfailRate] = useState(0);
  const [ttlOverride, setTtlOverride] = useState(0);
  const [nxdomains, setNxdomains] = useState('');
  const [newDomain, setNewDomain] = useState('');
  const [newType, setNewType] = useState('A');
  const [newValue, setNewValue] = useState('');
  const [applying, setApplying] = useState(false);
  const [newResolverAddr, setNewResolverAddr] = useState('');
  const [newResolverLabel, setNewResolverLabel] = useState('');

  // Sync from server config
  useEffect(() => {
    if (config) {
      setProvider(config.upstream.provider);
      setProtocol(config.upstream.protocol);
      setResolvers(config.upstream.resolvers || []);
      setDelayMs(config.impairments.delay_ms);
      setFailRate(config.impairments.failure_rate_pct);
      setServfailRate(config.impairments.servfail_rate_pct);
      setTtlOverride(config.impairments.ttl_override);
      setNxdomains((config.impairments.nxdomain_domains || []).join('\n'));
    }
  }, [config]);

  const buildConfig = (enabled: boolean): DnsConfig => ({
    enabled,
    listen_port: 5053,
    log_queries: true,
    upstream: { provider, custom_servers: [], protocol, resolvers },
    impairments: {
      delay_ms: delayMs, failure_rate_pct: failRate,
      servfail_rate_pct: servfailRate, ttl_override: ttlOverride,
      nxdomain_domains: nxdomains.split('\n').map(s => s.trim()).filter(Boolean),
    },
    overrides: config?.overrides ?? [],
  });

  const applyConfig = async (enabled: boolean) => {
    setApplying(true);
    try {
      await fetch('/api/v1/dns/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildConfig(enabled)),
      });
      refresh(); refreshConfig();
    } catch { notify('Failed to apply DNS config', 'error'); }
    finally { setApplying(false); }
  };

  const addOverride = async () => {
    if (!newDomain || !newValue) return;
    await fetch('/api/v1/dns/overrides', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: newDomain, record_type: newType, value: newValue }),
    });
    setNewDomain(''); setNewValue(''); refreshConfig();
  };

  const removeOverride = async (domain: string) => {
    await fetch(`/api/v1/dns/overrides/${encodeURIComponent(domain)}`, { method: 'DELETE' });
    refreshConfig();
  };

  const addResolver = () => {
    if (!newResolverAddr) return;
    setResolvers(prev => [...prev, { address: newResolverAddr, label: newResolverLabel || newResolverAddr, healthy: true, delay_ms: 0 }]);
    setNewResolverAddr(''); setNewResolverLabel('');
  };

  const toggleResolverHealth = (idx: number) => {
    setResolvers(prev => prev.map((r, i) => i === idx ? { ...r, healthy: !r.healthy } : r));
  };

  const removeResolver = (idx: number) => {
    setResolvers(prev => prev.filter((_, i) => i !== idx));
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      {/* Header with enable/disable */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">DNS Simulation</h2>
          <p className="text-xs text-gray-500">Control DNS resolution behavior for connected devices</p>
        </div>
        <div className="flex items-center gap-3">
          {status?.enabled && (
            <div className="flex items-center gap-2 text-xs">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              <span className="text-green-400">{status.query_count} queries</span>
              {status.resolver_count > 0 && (
                <span className="text-gray-500">{status.healthy_resolvers}/{status.resolver_count} resolvers</span>
              )}
            </div>
          )}
          <div className="flex gap-2">
            <button onClick={() => applyConfig(true)} disabled={applying}
              className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {applying ? 'Applying...' : 'Apply'}
            </button>
            {status?.enabled && (
              <button onClick={() => applyConfig(false)} disabled={applying}
                className="rounded-lg border border-gray-300 bg-white px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300">
                Clear All
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Active impairments badges */}
      {status?.impairments_active && status.impairments_active.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1">
          {status.impairments_active.map(imp => (
            <span key={imp} className="rounded bg-cyan-900 px-2 py-0.5 text-[10px] text-cyan-300">{imp}</span>
          ))}
        </div>
      )}

      {/* === UPSTREAM SECTION === */}
      <div className="mb-5 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
        <h3 className="mb-3 text-sm font-medium text-gray-300">Upstream Resolvers</h3>

        <div className="mb-3 flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-gray-500">Provider</label>
            <select value={provider} onChange={e => { setProvider(e.target.value); if (e.target.value !== 'multi') setResolvers([]); }}
              className="w-full rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-white">
              <option value="dhcp">DHCP DNS (from network)</option>
              <option value="cloudflare">Cloudflare (1.1.1.1)</option>
              <option value="google">Google (8.8.8.8)</option>
              <option value="quad9">Quad9 (9.9.9.9)</option>
              <option value="opendns">OpenDNS (208.67.222.222)</option>
              <option value="custom">Custom</option>
              <option value="multi">Multi-Resolver (failover testing)</option>
            </select>
          </div>
          {provider !== 'multi' && (
            <div className="flex-1">
              <label className="mb-1 block text-xs text-gray-500">Protocol</label>
              <select value={protocol} onChange={e => setProtocol(e.target.value)}
                className="w-full rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-white">
                <option value="plain">Plain DNS (UDP/53)</option>
                <option value="doh">DNS over HTTPS (DoH)</option>
                <option value="dot">DNS over TLS (DoT)</option>
              </select>
            </div>
          )}
        </div>

        {/* Multi-resolver list */}
        {provider === 'multi' && (
          <div>
            <p className="mb-2 text-xs text-gray-500">Add resolvers and toggle their health to simulate failover scenarios.</p>
            <div className="mb-2 flex gap-2">
              <input value={newResolverAddr} onChange={e => setNewResolverAddr(e.target.value)}
                placeholder="8.8.8.8 or tls://1.1.1.1" className="flex-1 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs font-mono text-white" />
              <input value={newResolverLabel} onChange={e => setNewResolverLabel(e.target.value)}
                placeholder="Label (Primary)" className="w-32 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white" />
              <button onClick={addResolver} disabled={!newResolverAddr}
                className="rounded bg-cyan-600 px-3 py-1 text-xs text-white hover:bg-cyan-700 disabled:opacity-50">Add</button>
            </div>
            <div className="space-y-1">
              {resolvers.map((r, i) => (
                <div key={i} className={`flex items-center justify-between rounded px-3 py-2 ${r.healthy ? 'border border-green-800 bg-green-950/30' : 'border border-red-800 bg-red-950/30'}`}>
                  <div className="flex items-center gap-2">
                    <span className={`inline-block h-2 w-2 rounded-full ${r.healthy ? 'bg-green-500' : 'bg-red-500'}`} />
                    <span className="text-xs font-medium text-gray-300">{r.label || r.address}</span>
                    <span className="font-mono text-[10px] text-gray-500">{r.address}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${r.healthy ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                      {r.healthy ? 'HEALTHY' : 'FAILED'}
                    </span>
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => toggleResolverHealth(i)}
                      className={`rounded px-2 py-1 text-[10px] ${r.healthy ? 'bg-red-900 text-red-300 hover:bg-red-800' : 'bg-green-900 text-green-300 hover:bg-green-800'}`}>
                      {r.healthy ? 'Fail' : 'Restore'}
                    </button>
                    <button onClick={() => removeResolver(i)}
                      className="rounded bg-gray-700 px-2 py-1 text-[10px] text-gray-400 hover:bg-gray-600">Remove</button>
                  </div>
                </div>
              ))}
              {resolvers.length === 0 && (
                <p className="py-2 text-center text-xs text-gray-600">Add resolvers above. Toggle health to simulate primary failure.</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* === IMPAIRMENTS SECTION === */}
      <div className="mb-5 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
        <h3 className="mb-3 text-sm font-medium text-gray-300">DNS Impairments</h3>
        <div className="space-y-2">
          <Slider label="Response Delay" value={delayMs} onChange={setDelayMs} min={0} max={5000} step={50} unit="ms" title="Add latency to all DNS responses" />
          <Slider label="Query Drop" value={failRate} onChange={setFailRate} min={0} max={50} step={0.5} unit="%" title="Percentage of queries that get no response" />
          <Slider label="SERVFAIL" value={servfailRate} onChange={setServfailRate} min={0} max={50} step={0.5} unit="%" title="Percentage of queries that return SERVFAIL" />
          <Slider label="TTL Override" value={ttlOverride} onChange={setTtlOverride} min={0} max={3600} step={5} unit="sec" title="Force this TTL on all responses (0 = no override)" />
        </div>
        <div className="mt-3">
          <label className="mb-1 block text-xs text-gray-500">NXDOMAIN Injection (one pattern per line, wildcards OK)</label>
          <textarea value={nxdomains} onChange={e => setNxdomains(e.target.value)} rows={2} placeholder="*.badcdn.example.com&#10;blocked.domain.com"
            className="w-full rounded border border-gray-600 bg-gray-800 px-3 py-1.5 font-mono text-xs text-white" />
        </div>
      </div>

      {/* === RECORD OVERRIDES SECTION === */}
      <div className="mb-5 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
        <h3 className="mb-3 text-sm font-medium text-gray-300">Record Overrides ({config?.overrides?.length ?? 0})</h3>
        <p className="mb-2 text-xs text-gray-500">Redirect specific domains to custom IPs (e.g. point CDN at local server).</p>
        <div className="mb-2 flex gap-2">
          <input value={newDomain} onChange={e => setNewDomain(e.target.value)} placeholder="cdn.example.com"
            className="flex-1 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs font-mono text-white" />
          <select value={newType} onChange={e => setNewType(e.target.value)}
            className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white">
            <option value="A">A</option><option value="AAAA">AAAA</option><option value="CNAME">CNAME</option>
          </select>
          <input value={newValue} onChange={e => setNewValue(e.target.value)} placeholder="192.168.4.1"
            className="w-36 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs font-mono text-white" />
          <button onClick={addOverride} disabled={!newDomain || !newValue}
            className="rounded bg-cyan-600 px-3 py-1 text-xs text-white hover:bg-cyan-700 disabled:opacity-50">Add</button>
        </div>
        {(config?.overrides ?? []).map(o => (
          <div key={`${o.domain}-${o.record_type}`} className="mb-1 flex items-center justify-between rounded border border-gray-700 bg-gray-800/50 px-3 py-1.5">
            <div className="flex items-center gap-2 text-xs">
              <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] font-bold text-gray-400">{o.record_type}</span>
              <span className="font-mono text-gray-300">{o.domain}</span>
              <span className="text-gray-600">→</span>
              <span className="font-mono text-cyan-400">{o.value}</span>
            </div>
            <button onClick={() => removeOverride(o.domain)} className="text-xs text-red-400 hover:text-red-300">Remove</button>
          </div>
        ))}
      </div>

      {/* === QUERY LOG === */}
      {status?.enabled && (
        <div className="rounded-lg border border-gray-700 bg-gray-800/30 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-300">Live Query Log</h3>
          <div className="max-h-48 overflow-y-auto rounded bg-gray-950 p-2 font-mono text-[10px]">
            {(queryLog ?? []).length === 0 ? (
              <span className="text-gray-600">Waiting for DNS queries...</span>
            ) : (
              (queryLog ?? []).map((q, i) => (
                <div key={i} className={q.response_code === 'NXDOMAIN' ? 'text-red-400' : q.response_code === 'SERVFAIL' ? 'text-yellow-400' : 'text-gray-400'}>
                  <span className="text-gray-600">{q.client_ip} </span>
                  <span className="text-cyan-400">{q.query_type} </span>
                  <span className="text-gray-200">{q.domain} </span>
                  <span className={q.response_code === 'NOERROR' ? 'text-green-500' : 'text-red-400'}>{q.response_code} </span>
                  <span className="text-gray-600">{q.latency_ms}ms</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
