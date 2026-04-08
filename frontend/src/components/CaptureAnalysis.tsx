import { useCallback, useEffect, useState } from 'react';
import type { AnalysisResultV2, CaptureSummary, SystemSettings, Finding } from '../types';
import * as api from '../api/client';

// ── Style Maps ──────────────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'border-red-500 bg-red-50 dark:bg-red-950',
  high: 'border-orange-500 bg-orange-50 dark:bg-orange-950',
  medium: 'border-yellow-500 bg-yellow-50 dark:bg-yellow-950',
  low: 'border-green-500 bg-green-50 dark:bg-green-950',
};

const SEVERITY_BADGE: Record<string, string> = {
  critical: 'bg-red-600 text-white',
  high: 'bg-orange-500 text-white',
  medium: 'bg-yellow-500 text-white',
  low: 'bg-green-600 text-white',
};

const CONFIDENCE_BADGE: Record<string, string> = {
  high: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  medium: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  low: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
};

const HEALTH_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  healthy: { bg: 'bg-green-100 dark:bg-green-900', text: 'text-green-700 dark:text-green-300', label: 'Healthy' },
  degraded: { bg: 'bg-yellow-100 dark:bg-yellow-900', text: 'text-yellow-700 dark:text-yellow-300', label: 'Degraded' },
  unhealthy: { bg: 'bg-red-100 dark:bg-red-900', text: 'text-red-700 dark:text-red-300', label: 'Unhealthy' },
  insufficient: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-500 dark:text-gray-400', label: 'Insufficient Data' },
};

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatBps(bps: number): string {
  if (bps === 0) return '0 bps';
  if (bps > 1_000_000) return `${(bps / 1_000_000).toFixed(1)} Mbps`;
  if (bps > 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`;
  return `${bps} bps`;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function CaptureAnalysis({
  captureId,
  onBack,
}: {
  captureId: string;
  onBack: () => void;
}) {
  const [result, setResult] = useState<AnalysisResultV2 | null>(null);
  const [summary, setSummary] = useState<CaptureSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    fetch('/api/v1/system/settings').then(r => r.json()).then((s: SystemSettings) => {
      setAiConfigured(s.anthropic_api_key_set || s.openai_api_key_set);
    }).catch(() => setAiConfigured(false));
  }, []);

  // Load summary
  useEffect(() => {
    api.getCaptureSummary(captureId).then(setSummary).catch(() => {});
  }, [captureId]);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.analyzeCapture(captureId);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [captureId]);

  // Load existing analysis on mount
  useEffect(() => {
    api.getAnalysis(captureId).then(setResult).catch(() => {});
  }, [captureId]);

  return (
    <div className="space-y-4">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            &larr; Back
          </button>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Capture Analysis
          </h2>
          {result && (
            <span className={`rounded-full px-3 py-1 text-sm font-medium ${HEALTH_STYLES[result.health_badge]?.bg || ''} ${HEALTH_STYLES[result.health_badge]?.text || ''}`}>
              {HEALTH_STYLES[result.health_badge]?.label || result.health_badge}
            </span>
          )}
        </div>
        <button
          onClick={runAnalysis}
          disabled={loading || aiConfigured === false}
          className="rounded-lg bg-purple-600 px-5 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          title={aiConfigured === false ? 'Configure an AI API key in System > App Settings' : ''}
        >
          {loading ? 'Analyzing...' : result ? 'Re-analyze' : 'Run Analysis'}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-700 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-12 text-center text-gray-500">
          <div className="mb-2 text-2xl">Analyzing capture data...</div>
          <p className="text-sm">Extracting statistics and sending to AI for evidence-based analysis</p>
        </div>
      )}

      {/* ── Stats Dashboard (from CaptureSummary) ──────────────────── */}
      {summary && !loading && <StatsDashboard summary={summary} />}

      {/* ── AI Findings ────────────────────────────────────────────── */}
      {result && !loading && (
        <>
          {/* Summary */}
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">AI Summary</h3>
            <p className="text-gray-900 dark:text-white">{result.summary}</p>
            <div className="mt-3 flex gap-4 text-xs text-gray-500">
              <span>Provider: {result.provider}</span>
              <span>Model: {result.model}</span>
              {result.tokens_used > 0 && <span>Tokens: {result.tokens_used}</span>}
              {result.analyzed_at && <span>At: {new Date(result.analyzed_at).toLocaleString()}</span>}
            </div>
          </div>

          {/* Findings */}
          {result.findings.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">
                Findings ({result.findings.length})
              </h3>
              {result.findings.map((finding) => (
                <FindingCard key={finding.id} finding={finding} />
              ))}
            </div>
          )}

          {/* Insufficient Evidence */}
          {result.insufficient_evidence.length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800">
              <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">
                Insufficient Evidence
              </h3>
              <div className="space-y-2">
                {result.insufficient_evidence.map((note, i) => (
                  <div key={i} className="text-sm">
                    <span className="font-medium text-gray-700 dark:text-gray-300">{note.area}:</span>{' '}
                    <span className="text-gray-600 dark:text-gray-400">{note.reason}</span>
                    {note.suggestion && (
                      <span className="ml-1 text-blue-600 dark:text-blue-400">&mdash; {note.suggestion}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Not configured / No results states */}
      {!result && !loading && !error && aiConfigured === false && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-6 text-center">
          <p className="mb-2 text-lg font-medium text-yellow-400">AI Analysis Not Configured</p>
          <p className="mb-4 text-sm text-gray-400">
            To analyze packet captures with AI, configure an API key in settings.
          </p>
          <p className="text-xs text-gray-500">
            Go to <span className="font-medium text-white">System</span> &rarr; <span className="font-medium text-white">App Settings</span>
          </p>
        </div>
      )}

      {!result && !loading && !error && aiConfigured !== false && (
        <div className="py-12 text-center text-gray-500">
          <p className="mb-2 text-lg">No analysis yet</p>
          <p className="text-sm">Click &ldquo;Run Analysis&rdquo; for evidence-based AI diagnosis</p>
        </div>
      )}
    </div>
  );
}

// ── Finding Card Component ──────────────────────────────────────────────────

function FindingCard({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded-lg border-l-4 p-4 ${SEVERITY_COLORS[finding.severity] || 'border-gray-300 bg-gray-50 dark:bg-gray-800'}`}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-gray-400">{finding.id}</span>
            <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${SEVERITY_BADGE[finding.severity] || 'bg-gray-500 text-white'}`}>
              {finding.severity}
            </span>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${CONFIDENCE_BADGE[finding.confidence] || ''}`}>
              {finding.confidence} confidence
            </span>
            <span className="rounded bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-700 dark:text-gray-300">
              {finding.category}
            </span>
          </div>
          <h4 className="font-medium text-gray-900 dark:text-white">{finding.title}</h4>
          <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">{finding.description}</p>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="ml-2 text-xs text-gray-400 hover:text-gray-600"
        >
          {expanded ? 'Less' : 'More'}
        </button>
      </div>

      {/* Evidence (always visible) */}
      {finding.evidence.length > 0 && (
        <div className="mt-3 rounded bg-white/50 p-2 dark:bg-black/20">
          <div className="mb-1 text-xs font-medium text-gray-500">Evidence</div>
          <div className="space-y-1">
            {finding.evidence.map((e, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <code className="rounded bg-gray-200 px-1 font-mono text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                  {e.metric}
                </code>
                <span className="font-semibold text-gray-900 dark:text-white">{e.value}</span>
                {e.context && <span className="text-gray-500">&mdash; {e.context}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="mt-3 space-y-2 border-t border-gray-200 pt-3 dark:border-gray-700">
          {finding.affected_flows.length > 0 && (
            <div className="text-xs">
              <span className="font-medium text-gray-500">Affected Flows: </span>
              {finding.affected_flows.map((f, j) => (
                <span key={j} className="mr-2 font-mono text-gray-700 dark:text-gray-300">{f}</span>
              ))}
            </div>
          )}

          {finding.likely_causes.length > 0 && (
            <div className="text-xs">
              <span className="font-medium text-gray-500">Likely Causes: </span>
              <ul className="ml-4 mt-0.5 list-disc text-gray-600 dark:text-gray-400">
                {finding.likely_causes.map((c, j) => <li key={j}>{c}</li>)}
              </ul>
            </div>
          )}

          {finding.next_steps.length > 0 && (
            <div className="text-xs">
              <span className="font-medium text-gray-500">Next Steps: </span>
              <ul className="ml-4 mt-0.5 list-disc text-gray-600 dark:text-gray-400">
                {finding.next_steps.map((s, j) => <li key={j}>{s}</li>)}
              </ul>
            </div>
          )}

          {finding.cross_references.length > 0 && (
            <div className="text-xs text-gray-500">
              <span className="font-medium">Related: </span>
              {finding.cross_references.join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Stats Dashboard Component ───────────────────────────────────────────────

function StatsDashboard({ summary }: { summary: CaptureSummary }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">Capture Statistics</h3>
        <div className="flex gap-3 text-xs text-gray-500">
          <span>{summary.meta.total_packets.toLocaleString()} packets</span>
          <span>{formatBytes(summary.meta.total_bytes)}</span>
          <span>{summary.meta.duration_secs.toFixed(1)}s</span>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Protocol Breakdown */}
        {summary.protocol_breakdown && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-gray-400">Protocols</h4>
            <div className="space-y-1">
              {summary.protocol_breakdown.protocols.slice(0, 8).map((p) => (
                <div key={p.name} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-gray-700 dark:text-gray-300">{p.name}</span>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                      <div
                        className="h-full rounded-full bg-blue-500"
                        style={{ width: `${Math.min(p.pct, 100)}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-gray-500">{p.pct}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TCP Health */}
        {summary.tcp_health && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-gray-400">TCP Health</h4>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <StatCell label="Retransmissions" value={`${summary.tcp_health.retransmission_pct}%`}
                warn={summary.tcp_health.retransmission_pct > 0.5}
                danger={summary.tcp_health.retransmission_pct > 2} />
              <StatCell label="Dup ACKs" value={String(summary.tcp_health.duplicate_ack_count)} />
              <StatCell label="Zero Windows" value={String(summary.tcp_health.zero_window_count)}
                warn={summary.tcp_health.zero_window_count > 0} />
              <StatCell label="RSTs" value={String(summary.tcp_health.rst_count)}
                warn={summary.tcp_health.rst_count > 5} />
              <StatCell label="Out of Order" value={String(summary.tcp_health.out_of_order_count)} />
              <StatCell label="Total Segments" value={summary.tcp_health.total_segments.toLocaleString()} />
            </div>
          </div>
        )}

        {/* Throughput */}
        {summary.throughput && summary.throughput.samples.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-gray-400">Throughput</h4>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <StatCell label="Average" value={formatBps(summary.throughput.avg_bps)} />
              <StatCell label="Peak" value={formatBps(summary.throughput.max_bps)} />
              <StatCell label="Min" value={formatBps(summary.throughput.min_bps)} />
              <StatCell label="Variability" value={`${(summary.throughput.coefficient_of_variation * 100).toFixed(0)}%`}
                warn={summary.throughput.coefficient_of_variation > 0.3}
                danger={summary.throughput.coefficient_of_variation > 0.5} />
            </div>
            {/* Mini sparkline */}
            <div className="mt-2 flex h-8 items-end gap-px">
              {summary.throughput.samples.slice(0, 30).map((s, i) => {
                const maxBps = summary.throughput?.max_bps || 1;
                const pct = (s.bps / maxBps) * 100;
                return (
                  <div
                    key={i}
                    className="flex-1 rounded-t bg-blue-400 dark:bg-blue-600"
                    style={{ height: `${Math.max(pct, 2)}%` }}
                    title={`${formatBps(s.bps)} @ ${s.interval_start}s`}
                  />
                );
              })}
            </div>
          </div>
        )}

        {/* DNS */}
        {summary.dns && summary.dns.total_queries > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-gray-400">DNS</h4>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <StatCell label="Queries" value={String(summary.dns.total_queries)} />
              <StatCell label="Unique Domains" value={String(summary.dns.unique_domains)} />
              <StatCell label="Avg Latency" value={`${summary.dns.avg_latency_ms.toFixed(1)}ms`}
                warn={summary.dns.avg_latency_ms > 100} danger={summary.dns.avg_latency_ms > 200} />
              <StatCell label="NXDOMAIN" value={String(summary.dns.nxdomain_count)}
                warn={summary.dns.nxdomain_count > 5} />
              <StatCell label="SERVFAIL" value={String(summary.dns.servfail_count)}
                danger={summary.dns.servfail_count > 0} />
              <StatCell label="Timeouts" value={String(summary.dns.timeout_count)}
                danger={summary.dns.timeout_count > 0} />
            </div>
          </div>
        )}

        {/* Top Conversations */}
        {summary.conversations.length > 0 && (
          <div className="sm:col-span-2">
            <h4 className="mb-2 text-xs font-medium text-gray-400">Top Conversations</h4>
            <div className="space-y-1">
              {summary.conversations.slice(0, 5).map((c, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-gray-700 dark:text-gray-300">
                    {c.src}:{c.src_port} &harr; {c.dst}:{c.dst_port}
                  </span>
                  <span className="text-gray-500">{formatBytes(c.bytes)} &middot; {formatBps(c.bps)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Anomaly Flags */}
        {summary.interest.anomaly_flags.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-gray-400">Detected Anomalies</h4>
            <div className="space-y-1">
              {summary.interest.anomaly_flags.map((flag, i) => (
                <div key={i} className={`rounded px-2 py-1 text-xs ${
                  flag.severity === 'high' || flag.severity === 'critical'
                    ? 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400'
                    : 'bg-yellow-50 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-400'
                }`}>
                  {flag.label}: <span className="font-mono">{flag.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Stat Cell ───────────────────────────────────────────────────────────────

function StatCell({ label, value, warn, danger }: { label: string; value: string; warn?: boolean; danger?: boolean }) {
  const color = danger
    ? 'text-red-600 dark:text-red-400'
    : warn
      ? 'text-yellow-600 dark:text-yellow-400'
      : 'text-gray-900 dark:text-white';

  return (
    <div>
      <div className="text-gray-400">{label}</div>
      <div className={`font-medium ${color}`}>{value}</div>
    </div>
  );
}
