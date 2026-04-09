/**
 * STB_AUTOMATION — STB Test Automation Panel.
 *
 * Provides:
 * - ADB device discovery and selection (reuses existing ADB device API)
 * - Live HDMI video stream (MJPEG from video capture module)
 * - D-pad remote with navigate-and-observe (settle detection)
 * - Screen state display (activity, focused element, fingerprint)
 * - Crawl controls (start/stop BFS, model stats)
 * - Test flow management (list, record, replay)
 * - Anomaly feed (live detected anomalies)
 * - Chaos mode controls (start/stop, progress, anomaly count)
 * - NL test generation (describe test in English → flow)
 *
 * Only rendered when the 'stb_automation' feature flag is enabled.
 * Removal: delete this file and its references in DashboardPanels.tsx + config.ts.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import type {
  AdbDevice,
  StbChaosResult,
  StbCrawlStatus,
  StbDetectedAnomaly,
  StbLogcatEvent,
  StbNavigateResponse,
  StbScreenStateResponse,
  StbStatus,
  StbTestFlow,
  StbTestFlowRun,
} from '../types';

// ── Styles ──────────────────────────────────────────────────────────

const card = 'rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900';
const sectionTitle = 'text-sm font-semibold text-gray-700 dark:text-gray-300';
const badge = 'inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold';
const btnBase = 'flex items-center justify-center rounded font-medium transition-colors active:scale-95 disabled:opacity-50';
const btnPrimary = `${btnBase} bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700`;
const btnSuccess = `${btnBase} bg-green-600 px-3 py-1.5 text-xs text-white hover:bg-green-700`;
const btnDanger = `${btnBase} bg-red-600 px-3 py-1.5 text-xs text-white hover:bg-red-700`;
const btnGhost = `${btnBase} rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800`;

// D-pad button styles
const dpadBtn = `${btnBase} h-10 w-12 bg-gray-700 text-sm text-white hover:bg-gray-600`;
const dpadOk = `${btnBase} h-10 w-12 bg-blue-600 text-xs text-white hover:bg-blue-700`;
const dpadSmall = `${btnBase} h-8 w-14 bg-gray-700 text-[10px] text-white hover:bg-gray-600`;

const STATE_COLORS: Record<string, string> = {
  idle: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  running: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  completed: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  error: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
  low: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const DEVICE_STATE_COLORS: Record<string, string> = {
  connected: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  disconnected: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  offline: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  unauthorized: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

type PanelSection = 'remote' | 'crawl' | 'flows' | 'chaos' | 'nl';

function VisionCacheDump() {
  const [cache, setCache] = useState<import('../types').StbVisionCacheDebug | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLoad = async () => {
    setLoading(true);
    try {
      setCache(await api.getStbVisionCache());
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  const handleClear = async () => {
    try {
      await api.clearStbVisionCache();
      setCache(null);
    } catch {
      // silent
    }
  };

  return (
    <div className="space-y-1 px-2 py-1">
      <div className="flex gap-2">
        <button onClick={handleLoad} disabled={loading} className={`${btnBase} border border-gray-300 px-2 py-0.5 text-[10px] text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800`}>
          {loading ? 'Loading...' : 'Load Cache'}
        </button>
        <button onClick={handleClear} className={`${btnBase} border border-red-300 px-2 py-0.5 text-[10px] text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/20`}>
          Clear Cache
        </button>
      </div>
      {cache && (
        <div className="space-y-1 font-mono text-[10px] text-gray-500 dark:text-gray-400">
          <div>size: {cache.size}/{cache.max_size} | threshold: {cache.threshold} | nav_seq: {cache.nav_sequence} | perceptual: {String(cache.has_perceptual_hash)}</div>
          <div>
            hits: {cache.hits_total} | misses: {cache.misses_total} |{' '}
            <span className={
              cache.hit_ratio_pct >= 75 ? 'text-green-600 dark:text-green-400'
                : cache.hit_ratio_pct >= 50 ? 'text-amber-600 dark:text-amber-400'
                  : 'text-red-600 dark:text-red-400'
            }>ratio: {cache.hit_ratio_pct}%</span>
          </div>
          {cache.entries.length > 0 && (
            <div className="max-h-40 overflow-y-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-700">
                    <th className="pb-0.5 pr-2">hash</th>
                    <th className="pb-0.5 pr-2">screen</th>
                    <th className="pb-0.5 pr-2">focused</th>
                    <th className="pb-0.5">tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {cache.entries.map((e, i) => (
                    <tr key={i} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="py-0.5 pr-2 text-gray-400">{e.hash_key.slice(0, 12)}...</td>
                      <td className="py-0.5 pr-2">{e.screen_type}{e.screen_title ? `: ${e.screen_title}` : ''}</td>
                      <td className="py-0.5 pr-2">{e.focused_label || '—'}</td>
                      <td className="py-0.5">{e.tokens_used}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {cache.entries.length === 0 && <div className="text-gray-400">Empty cache</div>}
        </div>
      )}
    </div>
  );
}

export default function StbAutomationPanel() {
  // ── Device State ───────────────────────────────────────────────────
  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);
  const [connectIp, setConnectIp] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [activeSection, setActiveSection] = useState<PanelSection>('remote');

  // ADB device discovery (polls every 5s)
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const deviceFetcher = useCallback((_signal: AbortSignal) => api.getAdbDevices(), []);
  const { data: devices, refresh: refreshDevices } = useApi<AdbDevice[]>(deviceFetcher, 5000);

  // STB status (polls every 5s, only when device selected)
  const stbFetcher = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    async (_signal: AbortSignal) => {
      if (!selectedSerial) return null;
      const [s, ev, an] = await Promise.all([
        api.getStbStatus(),
        api.getStbEvents(10),
        api.getStbAnomalies(10),
      ]);
      return { status: s, events: ev, anomalies: an };
    },
    [selectedSerial],
  );
  const { data: stbData, refresh: refreshStb } = useApi<{
    status: StbStatus;
    events: StbLogcatEvent[];
    anomalies: StbDetectedAnomaly[];
  } | null>(stbFetcher, selectedSerial ? 5000 : undefined);

  const status = stbData?.status ?? null;
  const events = stbData?.events ?? [];
  const anomalies = stbData?.anomalies ?? [];

  // Screen state
  const [screenState, setScreenState] = useState<StbScreenStateResponse | null>(null);
  const [lastNav, setLastNav] = useState<StbNavigateResponse | null>(null);
  const [navigating, setNavigating] = useState(false);
  const [visionEnabled, setVisionEnabled] = useState(false);
  const [visionThreshold, setVisionThreshold] = useState(0);

  // HDMI stream
  const [videoStreaming, setVideoStreaming] = useState(false);
  const videoCheckRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  // Crawl
  const [crawlStatus, setCrawlStatus] = useState<StbCrawlStatus | null>(null);

  // Flows
  const [flows, setFlows] = useState<StbTestFlow[]>([]);
  const [flowRun, setFlowRun] = useState<StbTestFlowRun | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordingName, setRecordingName] = useState('');

  // Chaos
  const [chaosResult, setChaosResult] = useState<StbChaosResult | null>(null);
  const [chaosDuration, setChaosDuration] = useState(300);

  // NL
  const [nlPrompt, setNlPrompt] = useState('');
  const [nlGenerating, setNlGenerating] = useState(false);

  // General
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // ── HDMI Stream Status ─────────────────────────────────────────────

  useEffect(() => {
    const check = async () => {
      try {
        const s = await api.getVideoStatus();
        setVideoStreaming(s.streaming);
      } catch {
        setVideoStreaming(false);
      }
    };
    check();
    videoCheckRef.current = setInterval(check, 5000);
    return () => clearInterval(videoCheckRef.current);
  }, []);

  // ── Device Connection ──────────────────────────────────────────────

  const handleConnect = async () => {
    if (!connectIp) return;
    setConnecting(true);
    setError(null);
    try {
      await api.connectAdbDevice(connectIp);
      setConnectIp('');
      await refreshDevices();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed');
    } finally {
      setConnecting(false);
    }
  };

  const handleSelectDevice = (serial: string) => {
    setSelectedSerial(serial);
    setScreenState(null);
    setLastNav(null);
    setError(null);
  };

  // ── Monitor ────────────────────────────────────────────────────────

  const handleStartMonitor = async () => {
    if (!selectedSerial) return;
    setLoading(true);
    try {
      await api.startStbMonitor(selectedSerial);
      await refreshStb();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start monitor');
    } finally {
      setLoading(false);
    }
  };

  const handleStopMonitor = async () => {
    setLoading(true);
    try {
      await api.stopStbMonitor();
      await refreshStb();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop monitor');
    } finally {
      setLoading(false);
    }
  };

  // ── Navigation ─────────────────────────────────────────────────────

  const handleNavigate = async (action: string) => {
    if (!selectedSerial || navigating) return;
    setNavigating(true);
    setError(null);
    try {
      const result = await api.stbNavigate(selectedSerial, action);
      setLastNav(result);
      setScreenState({
        state: result.post_state,
        fingerprint: result.post_fingerprint,
        diag: null,
      });
      // If vision is enabled, re-read state with vision analysis in background
      // (navigate endpoint doesn't include vision to keep it fast)
      if (visionEnabled) {
        api.getStbState(selectedSerial, true, true, visionThreshold).then(s => setScreenState(s)).catch(() => {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Navigate failed');
    } finally {
      setNavigating(false);
    }
  };

  const handleReadState = async () => {
    if (!selectedSerial) return;
    setLoading(true);
    try {
      const s = await api.getStbState(selectedSerial, true, visionEnabled, visionEnabled ? visionThreshold : undefined);
      setScreenState(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to read state');
    } finally {
      setLoading(false);
    }
  };

  // ── HDMI Stream Control ────────────────────────────────────────────

  const handleStartStream = async () => {
    setLoading(true);
    try {
      await api.startVideoStream();
      setVideoStreaming(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start stream');
    } finally {
      setLoading(false);
    }
  };

  const handleStopStream = async () => {
    setLoading(true);
    try {
      await api.stopVideoStream();
      setVideoStreaming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop stream');
    } finally {
      setLoading(false);
    }
  };

  // ── Crawl ──────────────────────────────────────────────────────────

  const handleStartCrawl = async () => {
    if (!selectedSerial) return;
    try {
      const s = await api.startStbCrawl({ serial: selectedSerial });
      setCrawlStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start crawl');
    }
  };

  const handleStopCrawl = async () => {
    try {
      const s = await api.stopStbCrawl();
      setCrawlStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop crawl');
    }
  };

  // ── Flows ──────────────────────────────────────────────────────────

  const handleRefreshFlows = useCallback(async () => {
    try {
      setFlows(await api.listStbFlows());
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (activeSection === 'flows') {
      handleRefreshFlows();
    }
  }, [activeSection, handleRefreshFlows]);

  const handleStartRecording = async () => {
    if (!selectedSerial || !recordingName) return;
    try {
      await api.startStbRecording(recordingName, selectedSerial);
      setRecording(true);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start recording');
    }
  };

  const handleStopRecording = async () => {
    try {
      await api.stopStbRecording();
      setRecording(false);
      setRecordingName('');
      await handleRefreshFlows();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop recording');
    }
  };

  const handleRunFlow = async (flowId: string) => {
    try {
      const run = await api.runStbFlow(flowId);
      setFlowRun(run);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run flow');
    }
  };

  const handleDeleteFlow = async (flowId: string) => {
    try {
      await api.deleteStbFlow(flowId);
      await handleRefreshFlows();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete flow');
    }
  };

  // ── Chaos ──────────────────────────────────────────────────────────

  const handleRefreshChaos = useCallback(async () => {
    try {
      const r = await api.getStbChaosStatus();
      setChaosResult(r);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (activeSection === 'chaos') {
      handleRefreshChaos();
    }
  }, [activeSection, handleRefreshChaos]);

  const handleStartChaos = async () => {
    if (!selectedSerial) return;
    try {
      const r = await api.startStbChaos({
        serial: selectedSerial,
        duration_secs: chaosDuration,
        on_anomaly: 'collect',
      });
      setChaosResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start chaos');
    }
  };

  const handleStopChaos = async () => {
    try {
      const r = await api.stopStbChaos();
      setChaosResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop chaos');
    }
  };

  // ── NL ─────────────────────────────────────────────────────────────

  const handleNlGenerate = async () => {
    if (!selectedSerial || !nlPrompt) return;
    setNlGenerating(true);
    setError(null);
    try {
      const flow = await api.generateStbFlow({
        prompt: nlPrompt,
        serial: selectedSerial,
        device_id: selectedSerial,
      });
      setNlPrompt('');
      setFlows((prev) => [flow, ...prev]);
      setActiveSection('flows');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'NL generation failed');
    } finally {
      setNlGenerating(false);
    }
  };

  // ── Derived ────────────────────────────────────────────────────────

  const connectedDevices = (devices ?? []).filter((d) => d.state === 'connected');
  const selectedDevice = connectedDevices.find((d) => d.serial === selectedSerial);

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header + Device Selector */}
      <div className={card}>
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">STB Automation</h2>
          <span className="rounded bg-yellow-200 px-1.5 py-0.5 text-[10px] font-medium text-yellow-700 dark:bg-yellow-800 dark:text-yellow-300">
            EXPERIMENTAL
          </span>
        </div>

        {/* Connect new device */}
        <div className="mb-3 flex items-center gap-2">
          <input
            value={connectIp}
            onChange={(e) => setConnectIp(e.target.value)}
            placeholder="IP address (e.g. 192.168.4.10)"
            onKeyDown={(e) => e.key === 'Enter' && handleConnect()}
            className="w-56 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />
          <button onClick={handleConnect} disabled={connecting || !connectIp} className={btnPrimary}>
            {connecting ? 'Connecting...' : 'Connect'}
          </button>
        </div>

        {/* Device list */}
        {(devices ?? []).length > 0 ? (
          <div className="space-y-1">
            {(devices ?? []).map((d) => (
              <div
                key={d.serial}
                onClick={() => d.state === 'connected' && handleSelectDevice(d.serial)}
                className={`flex cursor-pointer items-center justify-between rounded-lg border px-3 py-2 text-xs ${
                  selectedSerial === d.serial
                    ? 'border-blue-500 bg-blue-50 dark:border-blue-600 dark:bg-blue-950'
                    : 'border-gray-100 bg-gray-50 hover:bg-gray-100 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-750'
                } ${d.state !== 'connected' ? 'cursor-not-allowed opacity-60' : ''}`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono font-medium text-gray-900 dark:text-white">{d.serial}</span>
                  <span className={`${badge} ${DEVICE_STATE_COLORS[d.state] || DEVICE_STATE_COLORS.disconnected}`}>
                    {d.state}
                  </span>
                  {d.model && <span className="text-gray-500 dark:text-gray-400">{d.model}</span>}
                </div>
                {selectedSerial === d.serial && (
                  <span className="text-[10px] font-medium text-blue-600 dark:text-blue-400">SELECTED</span>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            No ADB devices found. Connect a device via IP address above or ensure USB connection.
          </p>
        )}

        {/* Selected device controls */}
        {selectedDevice && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button onClick={handleReadState} disabled={loading} className={btnPrimary}>
              Read State
            </button>
            <button
              onClick={status?.logcat_monitor_active ? handleStopMonitor : handleStartMonitor}
              disabled={loading}
              className={status?.logcat_monitor_active ? btnDanger : btnSuccess}
            >
              {status?.logcat_monitor_active ? 'Stop Monitor' : 'Start Monitor'}
            </button>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
              <input
                type="checkbox"
                checked={visionEnabled}
                onChange={e => setVisionEnabled(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              AI Vision
              {visionEnabled && <span className="text-[10px] text-amber-600 dark:text-amber-400">(uses API tokens)</span>}
            </label>
            {visionEnabled && (
              <div className="flex items-center gap-1.5">
                <label className="text-[10px] text-gray-500 dark:text-gray-400" title="Hamming distance threshold for perceptual hash cache. Lower = stricter matching (more API calls, more accurate). Higher = looser (fewer API calls, risk of stale results).&#10;&#10;Suggested ranges:&#10;  0 = exact match only (no fuzzy cache)&#10;  1-2 = very strict (JPEG noise tolerance only)&#10;  3-4 = strict (recommended for menus)&#10;  6 = default (may be too loose for similar screens)&#10;  8-12 = loose (only for very different screens)">
                  Cache d≤
                </label>
                <input
                  type="number"
                  min={0}
                  max={50}
                  value={visionThreshold}
                  onChange={e => setVisionThreshold(Math.max(0, Math.min(50, parseInt(e.target.value) || 0)))}
                  className="w-12 rounded border border-gray-300 px-1 py-0.5 text-center text-[11px] text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
                  title="Hamming distance threshold (0=exact, 1-2=strict, 3-4=recommended, 6=default)"
                />
              </div>
            )}
            {status && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Monitor:{' '}
                <span className={`font-medium ${status.logcat_monitor_active ? 'text-green-600 dark:text-green-400' : ''}`}>
                  {status.logcat_monitor_active ? 'active' : 'inactive'}
                </span>
              </span>
            )}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-900/30 dark:text-red-300">
            {error}
          </div>
        )}
      </div>

      {/* Only show rest when a device is selected */}
      {selectedDevice && (
        <>
          {/* Section Tabs */}
          <div className="flex gap-1 rounded-lg bg-gray-100 p-1 dark:bg-gray-800">
            {([
              { id: 'remote' as const, label: 'Remote' },
              { id: 'crawl' as const, label: 'Crawl' },
              { id: 'flows' as const, label: 'Test Flows' },
              { id: 'chaos' as const, label: 'Chaos' },
              { id: 'nl' as const, label: 'NL Test' },
            ]).map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveSection(tab.id)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  activeSection === tab.id
                    ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-white'
                    : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Remote Control Section */}
          {activeSection === 'remote' && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {/* D-pad + Controls */}
              <div className={card}>
                <h3 className={`mb-3 ${sectionTitle}`}>Navigate + Observe</h3>
                <p className="mb-3 text-[11px] text-gray-500 dark:text-gray-400">
                  Each key press uses logcat-driven settle detection to wait for the screen to stabilize.
                </p>
                <div className="mx-auto flex max-w-[220px] flex-col items-center gap-1 rounded-xl bg-gray-800 px-4 py-4 dark:bg-gray-950">
                  <button onClick={() => handleNavigate('up')} disabled={navigating} className={dpadBtn}>&#x25B2;</button>
                  <div className="flex items-center gap-1">
                    <button onClick={() => handleNavigate('left')} disabled={navigating} className={dpadBtn}>&#x25C0;</button>
                    <button onClick={() => handleNavigate('enter')} disabled={navigating} className={dpadOk}>OK</button>
                    <button onClick={() => handleNavigate('right')} disabled={navigating} className={dpadBtn}>&#x25B6;</button>
                  </div>
                  <button onClick={() => handleNavigate('down')} disabled={navigating} className={dpadBtn}>&#x25BC;</button>

                  <div className="mt-2 flex gap-1">
                    <button onClick={() => handleNavigate('back')} disabled={navigating} className={dpadSmall}>Back</button>
                    <button onClick={() => handleNavigate('home')} disabled={navigating} className={dpadSmall}>Home</button>
                    <button onClick={() => handleNavigate('menu')} disabled={navigating} className={dpadSmall}>Menu</button>
                  </div>
                </div>

                {navigating && <p className="mt-2 text-center text-xs text-blue-500">Navigating...</p>}

                {/* Last navigation result */}
                {lastNav && (
                  <div className="mt-3 rounded border border-gray-200 bg-gray-50 p-2 text-xs dark:border-gray-700 dark:bg-gray-800/50">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-600 dark:text-gray-300">{lastNav.action}</span>
                      <span className={`${badge} ${lastNav.transitioned ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300' : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'}`}>
                        {lastNav.transitioned ? 'transitioned' : 'no change'}
                      </span>
                      <span className="text-gray-500 dark:text-gray-400">
                        {lastNav.settle_ms}ms ({lastNav.settle_method})
                      </span>
                    </div>
                  </div>
                )}

                {/* Recording indicator */}
                {recording && (
                  <div className="mt-3 flex items-center gap-2 rounded border border-red-300 bg-red-50 px-3 py-2 dark:border-red-700 dark:bg-red-900/20">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
                    <span className="text-xs font-medium text-red-700 dark:text-red-300">Recording steps...</span>
                    <button onClick={handleStopRecording} className={`ml-auto ${btnDanger} py-1 text-[10px]`}>
                      Stop Recording
                    </button>
                  </div>
                )}
              </div>

              {/* HDMI Live View */}
              <div className={card}>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className={sectionTitle}>HDMI Live View</h3>
                  <div className="flex gap-1">
                    {!videoStreaming ? (
                      <button onClick={handleStartStream} disabled={loading} className={`${btnSuccess} py-1 text-[10px]`}>
                        Start Stream
                      </button>
                    ) : (
                      <button onClick={handleStopStream} disabled={loading} className={`${btnDanger} py-1 text-[10px]`}>
                        Stop Stream
                      </button>
                    )}
                  </div>
                </div>

                {videoStreaming ? (
                  <div className="overflow-hidden rounded border border-gray-200 bg-black dark:border-gray-700">
                    <img
                      src="/api/v1/experimental/video/stream"
                      alt="Live HDMI video stream"
                      className="w-full"
                      style={{ maxHeight: '360px', objectFit: 'contain' }}
                    />
                  </div>
                ) : (
                  <div className="flex h-48 items-center justify-center rounded border border-dashed border-gray-300 bg-gray-50 dark:border-gray-600 dark:bg-gray-800">
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      HDMI stream inactive. Click &quot;Start Stream&quot; to begin live capture.
                    </p>
                  </div>
                )}
              </div>

              {/* Screen State + Events */}
              <div className={card}>
                <h3 className={`mb-3 ${sectionTitle}`}>Screen State</h3>
                {screenState ? (
                  <div className="space-y-2 text-xs">
                    {/* Hashes — stable vs volatile */}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <div className="flex items-center gap-1">
                        <span className="text-gray-500 dark:text-gray-400">FP:</span>
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] dark:bg-gray-800">{screenState.diag?.fingerprint ?? screenState.fingerprint}</span>
                      </div>
                      {screenState.diag?.visual_hash && (
                        <div className="flex items-center gap-1">
                          <span className="text-gray-500 dark:text-gray-400">VH:</span>
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] dark:bg-amber-900/40">{screenState.diag.visual_hash}</span>
                        </div>
                      )}
                      {screenState.diag && (
                        <span className="text-[10px] text-gray-400 dark:text-gray-500">
                          {screenState.diag.total_ms ?? screenState.diag.read_ms}ms &middot; {screenState.diag.adb_signals} signals
                          {screenState.diag.vision_fast_path && (
                            <span className="ml-1 rounded bg-green-100 px-1 py-0.5 font-semibold text-green-700 dark:bg-green-900/40 dark:text-green-300">FAST PATH</span>
                          )}
                        </span>
                      )}
                    </div>
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Package: </span>
                      <span className="text-gray-900 dark:text-white">{screenState.state.package || '\u2014'}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Activity: </span>
                      <span className="text-gray-900 dark:text-white">{screenState.state.activity || '\u2014'}</span>
                    </div>
                    {/* AI Vision Analysis — most human-readable signal */}
                    {screenState.state.vision && (
                      <div className="rounded border border-emerald-200 bg-emerald-50 p-2 dark:border-emerald-800 dark:bg-emerald-900/20">
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-medium uppercase tracking-wider text-emerald-600 dark:text-emerald-400">AI Vision</span>
                          <span className={`${badge} ${screenState.state.vision.screen_type === 'unknown' ? 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300'}`}>
                            {screenState.state.vision.screen_type}
                          </span>
                          {screenState.state.vision.screen_title && (
                            <span className="text-[11px] font-medium text-emerald-900 dark:text-emerald-100">{screenState.state.vision.screen_title}</span>
                          )}
                          {/* Vision cache diagnostic badges */}
                          {screenState.diag?.vision && (
                            <>
                              <span className={`${badge} ${screenState.diag.vision.cache_hit ? 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300' : 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'}`}>
                                {screenState.diag.vision.cache_hit
                                  ? `CACHE`
                                  : `API ${screenState.diag.vision.api_call_ms}ms`}
                              </span>
                              {/* Hamming distance badge */}
                              {screenState.diag.vision.hamming_distance >= 0 && (
                                <span className={`${badge} ${
                                  screenState.diag.vision.hamming_distance === 0
                                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                                    : screenState.diag.vision.hamming_distance <= screenState.diag.vision.hamming_threshold
                                      ? 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                                      : 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                                }`}>
                                  d={screenState.diag.vision.hamming_distance}
                                </span>
                              )}
                              {/* Invalidation reason badge */}
                              {screenState.diag.vision.invalidation_reason && (
                                <span className={`${badge} bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400`}>
                                  {screenState.diag.vision.invalidation_reason}
                                </span>
                              )}
                              <span className={`${badge} bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400`}>
                                {screenState.diag.vision.hash_type}
                              </span>
                              {/* Hit ratio badge */}
                              {(screenState.diag.vision.cache_hits_total + screenState.diag.vision.cache_misses_total) > 0 && (
                                <span className={`${badge} ${
                                  screenState.diag.vision.cache_hit_ratio_pct >= 75
                                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                                    : screenState.diag.vision.cache_hit_ratio_pct >= 50
                                      ? 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                                      : 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                                }`}>
                                  {screenState.diag.vision.cache_hit_ratio_pct}% hit ({screenState.diag.vision.cache_hits_total}/{screenState.diag.vision.cache_hits_total + screenState.diag.vision.cache_misses_total})
                                </span>
                              )}
                            </>
                          )}
                        </div>
                        {screenState.state.vision.focused_label && (
                          <div className="text-[11px] text-emerald-800 dark:text-emerald-200">
                            <span className="font-medium">Focused:</span> {screenState.state.vision.focused_label}
                            {screenState.state.vision.focused_position && (
                              <span className="text-emerald-600 dark:text-emerald-400"> ({screenState.state.vision.focused_position})</span>
                            )}
                          </div>
                        )}
                        {screenState.state.vision.navigation_path?.length > 0 && (
                          <div className="text-[11px] text-emerald-800 dark:text-emerald-200">
                            <span className="font-medium">Nav:</span> {screenState.state.vision.navigation_path.join(' > ')}
                          </div>
                        )}
                        {screenState.state.vision.visible_text && (
                          <div className="mt-1 text-[10px] leading-relaxed text-emerald-700 dark:text-emerald-300">
                            {screenState.state.vision.visible_text}
                          </div>
                        )}
                        <div className="mt-1 text-[9px] text-emerald-500 dark:text-emerald-500">
                          {screenState.state.vision.provider} &middot; {screenState.state.vision.tokens_used} tokens
                        </div>
                      </div>
                    )}
                    {/* Vision error/status when enabled but no result */}
                    {visionEnabled && !screenState.state.vision && screenState.diag?.vision && (
                      <div className="rounded border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                        Vision: {screenState.diag.vision.error || 'No result'}
                        {!screenState.diag.vision.streamer_running && ' (HDMI streamer not running)'}
                      </div>
                    )}
                    {/* ADB Context — technical signals */}
                    {screenState.state.focused_context && (
                      <div className="rounded border border-purple-200 bg-purple-50 p-2 dark:border-purple-800 dark:bg-purple-900/20">
                        <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-purple-500 dark:text-purple-400">ADB Context</div>
                        <div className="space-y-0.5 text-[11px] text-purple-900 dark:text-purple-100">
                          {screenState.state.focused_context.split(' | ').map((part, i) => (
                            <div key={i}>{part}</div>
                          ))}
                        </div>
                      </div>
                    )}
                    {/* Fragments */}
                    {screenState.state.fragments?.length > 0 && (
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Fragments: </span>
                        <span className="font-mono text-[11px] text-gray-900 dark:text-white">
                          {screenState.state.fragments.join(', ')}
                        </span>
                      </div>
                    )}
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">UI Elements: </span>
                      <span className="text-gray-900 dark:text-white">{screenState.state.ui_elements?.length ?? 0}</span>
                    </div>
                    {/* Diagnostics panel — expanded by default */}
                    {screenState.diag && (
                      <details open className="rounded border border-gray-200 dark:border-gray-700">
                        <summary className="cursor-pointer px-2 py-1 text-[10px] font-medium text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800">
                          Diagnostics
                        </summary>
                        <div className="space-y-0.5 px-2 py-1 font-mono text-[10px] text-gray-500 dark:text-gray-400">
                          <div>stable_fp: {screenState.diag.fingerprint}</div>
                          <div>visual_hash: {screenState.diag.visual_hash}</div>
                          <div>inputs: {screenState.diag.fingerprint_inputs}</div>
                          <div>adb_signals: {screenState.diag.adb_signals}</div>
                          <div>total_ms: {screenState.diag.total_ms ?? screenState.diag.read_ms}{screenState.diag.vision_fast_path ? ' ⚡ fast path' : ''}</div>
                          {screenState.diag.adb_total_ms !== undefined && (
                            <div>adb: {screenState.diag.adb_foreground_ms ?? 0}+{screenState.diag.adb_hierarchy_ms ?? 0}+{screenState.diag.adb_fragments_ms ?? 0}+{screenState.diag.adb_window_title_ms ?? 0}={screenState.diag.adb_total_ms}ms{screenState.diag.frame_hash_ms ? ` | hash: ${screenState.diag.frame_hash_ms}ms` : ''}</div>
                          )}
                          {screenState.diag.vision && (
                            <>
                              <div className="mt-1 border-t border-gray-200 pt-1 dark:border-gray-700">vision:</div>
                              <div>&nbsp; cache_hit: <span className={screenState.diag.vision.cache_hit ? 'text-amber-600 dark:text-amber-400' : 'text-blue-600 dark:text-blue-400'}>{String(screenState.diag.vision.cache_hit)}</span></div>
                              <div>&nbsp; reason: {screenState.diag.vision.invalidation_reason || '—'}</div>
                              <div>&nbsp; hash_type: {screenState.diag.vision.hash_type || '—'}</div>
                              <div>&nbsp; cache_key: {screenState.diag.vision.cache_key} <span className="text-gray-400">({screenState.diag.vision.cache_key_source})</span></div>
                              <div>&nbsp; hamming_distance: <span className={
                                screenState.diag.vision.hamming_distance <= screenState.diag.vision.hamming_threshold
                                  ? 'text-green-600 dark:text-green-400'
                                  : 'text-red-600 dark:text-red-400'
                              }>{screenState.diag.vision.hamming_distance}</span> / threshold: {screenState.diag.vision.hamming_threshold}</div>
                              <div>&nbsp; nav_seq: {screenState.diag.vision.nav_sequence} (cached: {screenState.diag.vision.cached_nav_sequence})</div>
                              <div>&nbsp; cache_size: {screenState.diag.vision.cache_size}</div>
                              <div>&nbsp; api_call_ms: {screenState.diag.vision.api_call_ms}</div>
                              {screenState.diag.vision.error && <div>&nbsp; error: {screenState.diag.vision.error}</div>}
                              <div>&nbsp; streamer: {String(screenState.diag.vision.streamer_running)}</div>
                            </>
                          )}
                        </div>
                      </details>
                    )}
                    {/* Vision Cache dump — collapsible */}
                    {visionEnabled && (
                      <details open className="rounded border border-gray-200 dark:border-gray-700">
                        <summary className="cursor-pointer px-2 py-1 text-[10px] font-medium text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800">
                          Vision Cache
                        </summary>
                        <VisionCacheDump />
                      </details>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Click &quot;Read State&quot; or navigate to see the current screen.
                  </p>
                )}

                {/* Recent Events */}
                {events.length > 0 && (
                  <div className="mt-4">
                    <h4 className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">Recent Events</h4>
                    <div className="max-h-32 space-y-1 overflow-y-auto">
                      {events.map((ev, i) => (
                        <div key={i} className="flex gap-2 text-[11px]">
                          <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                            {ev.event_type}
                          </span>
                          <span className="truncate text-gray-600 dark:text-gray-400">
                            {ev.activity || ev.detail || ev.raw}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Anomalies */}
                {anomalies.length > 0 && (
                  <div className="mt-4">
                    <h4 className="mb-2 text-xs font-medium text-red-600 dark:text-red-400">Anomalies</h4>
                    <div className="max-h-24 space-y-1 overflow-y-auto">
                      {anomalies.map((a, i) => (
                        <div key={i} className="flex items-center gap-2 text-[11px]">
                          <span className={`${badge} ${SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.low}`}>
                            {a.severity}
                          </span>
                          <span className="text-gray-700 dark:text-gray-300">{a.pattern_name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Crawl Section */}
          {activeSection === 'crawl' && (
            <div className={card}>
              <h3 className={`mb-3 ${sectionTitle}`}>BFS Crawl Explorer</h3>
              <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                Autonomously explores the STB UI via key presses, building a persistent navigation model.
              </p>

              <div className="mb-4 flex gap-2">
                <button onClick={handleStartCrawl} disabled={crawlStatus?.state === 'running'} className={btnSuccess}>
                  Start Crawl
                </button>
                <button onClick={handleStopCrawl} disabled={crawlStatus?.state !== 'running'} className={btnDanger}>
                  Stop Crawl
                </button>
              </div>

              {crawlStatus && (
                <div className="space-y-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-500 dark:text-gray-400">State:</span>
                    <span className={`${badge} ${STATE_COLORS[crawlStatus.state] || STATE_COLORS.idle}`}>{crawlStatus.state}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Nodes: </span>
                      <span className="font-semibold text-gray-900 dark:text-white">{crawlStatus.nodes_discovered}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Transitions: </span>
                      <span className="font-semibold text-gray-900 dark:text-white">{crawlStatus.transitions_executed}</span>
                    </div>
                    {crawlStatus.current_node_id && (
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Current: </span>
                        <span className="font-mono text-[11px] text-gray-700 dark:text-gray-300">{crawlStatus.current_node_id}</span>
                      </div>
                    )}
                  </div>
                  {crawlStatus.error && (
                    <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-red-700 dark:border-red-800 dark:bg-red-900/30 dark:text-red-300">
                      {crawlStatus.error}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Test Flows Section */}
          {activeSection === 'flows' && (
            <div className="space-y-4">
              {/* Record controls */}
              <div className={card}>
                <h3 className={`mb-3 ${sectionTitle}`}>Test Flow Recording</h3>
                {recording ? (
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
                    <span className="text-xs font-medium text-red-700 dark:text-red-300">Recording... Navigate using the Remote tab to capture steps.</span>
                    <button onClick={handleStopRecording} className={`ml-auto ${btnDanger}`}>Stop Recording</button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <input
                      value={recordingName}
                      onChange={(e) => setRecordingName(e.target.value)}
                      placeholder="Flow name"
                      className="w-48 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                    />
                    <button onClick={handleStartRecording} disabled={!recordingName} className={btnSuccess}>
                      Start Recording
                    </button>
                  </div>
                )}
              </div>

              {/* Flow list */}
              <div className={card}>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className={sectionTitle}>Saved Flows</h3>
                  <button onClick={handleRefreshFlows} className={btnGhost}>Refresh</button>
                </div>

                {flows.length === 0 ? (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    No test flows yet. Record navigation or generate with NL.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {flows.map((flow) => (
                      <div key={flow.id} className="flex items-center justify-between rounded border border-gray-200 px-3 py-2 dark:border-gray-700">
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">{flow.name}</div>
                          <div className="flex gap-3 text-[11px] text-gray-500 dark:text-gray-400">
                            <span>{flow.steps.length} steps</span>
                            <span className={`${badge} bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400`}>{flow.source}</span>
                            {flow.description && <span className="max-w-xs truncate">{flow.description}</span>}
                          </div>
                        </div>
                        <div className="flex gap-1">
                          <button onClick={() => handleRunFlow(flow.id)} className={`${btnPrimary} py-1 text-[10px]`}>Run</button>
                          <button onClick={() => handleDeleteFlow(flow.id)} className={`${btnDanger} py-1 text-[10px]`}>Delete</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Active flow run */}
              {flowRun && (
                <div className={card}>
                  <h3 className={`mb-3 ${sectionTitle}`}>Flow Run</h3>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 dark:text-gray-400">State:</span>
                      <span className={`${badge} ${STATE_COLORS[flowRun.state] || STATE_COLORS.idle}`}>{flowRun.state}</span>
                    </div>
                    <div className="grid grid-cols-4 gap-4">
                      <div><span className="text-gray-500 dark:text-gray-400">Step: </span><span className="font-semibold">{flowRun.current_step}</span></div>
                      <div><span className="text-green-600">Passed: </span><span className="font-semibold">{flowRun.steps_passed}</span></div>
                      <div><span className="text-red-600">Failed: </span><span className="font-semibold">{flowRun.steps_failed}</span></div>
                      <div><span className="text-orange-600">Anomalies: </span><span className="font-semibold">{flowRun.anomalies_detected}</span></div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Chaos Section */}
          {activeSection === 'chaos' && (
            <div className={card}>
              <h3 className={`mb-3 ${sectionTitle}`}>Chaos Mode</h3>
              <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                Autonomous random exploration — sends weighted-random key presses while monitoring for anomalies.
              </p>

              <div className="mb-4 flex items-center gap-3">
                <label className="text-xs text-gray-500 dark:text-gray-400">Duration (s):</label>
                <input
                  type="number"
                  value={chaosDuration}
                  onChange={(e) => setChaosDuration(Number(e.target.value))}
                  min={10}
                  max={3600}
                  className="w-20 rounded border border-gray-300 bg-white px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                />
                <button onClick={handleStartChaos} disabled={chaosResult?.state === 'running'} className={btnSuccess}>
                  Start Chaos
                </button>
                <button onClick={handleStopChaos} disabled={chaosResult?.state !== 'running'} className={btnDanger}>
                  Stop Chaos
                </button>
                <button onClick={handleRefreshChaos} className={btnGhost}>Refresh</button>
              </div>

              {chaosResult && chaosResult.state !== 'idle' && (
                <div className="space-y-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-500 dark:text-gray-400">State:</span>
                    <span className={`${badge} ${STATE_COLORS[chaosResult.state] || STATE_COLORS.idle}`}>{chaosResult.state}</span>
                  </div>
                  <div className="grid grid-cols-4 gap-4">
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Keys Sent: </span>
                      <span className="font-semibold text-gray-900 dark:text-white">{chaosResult.keys_sent}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Screens: </span>
                      <span className="font-semibold text-gray-900 dark:text-white">{chaosResult.screens_visited}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Duration: </span>
                      <span className="font-semibold text-gray-900 dark:text-white">{chaosResult.duration_secs}s</span>
                    </div>
                    <div>
                      <span className="text-gray-500 dark:text-gray-400">Anomalies: </span>
                      <span className={`font-semibold ${chaosResult.anomalies.length > 0 ? 'text-red-600' : 'text-gray-900 dark:text-white'}`}>
                        {chaosResult.anomalies.length}
                      </span>
                    </div>
                  </div>

                  {chaosResult.anomalies.length > 0 && (
                    <div className="mt-2 max-h-40 space-y-1 overflow-y-auto rounded border border-red-200 bg-red-50 p-2 dark:border-red-800 dark:bg-red-900/20">
                      {chaosResult.anomalies.map((a, i) => (
                        <div key={i} className="flex items-center gap-2 text-[11px]">
                          <span className={`${badge} ${SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.low}`}>{a.severity}</span>
                          <span className="text-gray-700 dark:text-gray-300">{a.pattern_name}</span>
                          <span className="text-gray-500">{a.timestamp}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* NL Test Section */}
          {activeSection === 'nl' && (
            <div className={card}>
              <h3 className={`mb-3 ${sectionTitle}`}>Natural Language Test Generation</h3>
              <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                Describe a test scenario in plain English and the AI will generate an executable test flow.
              </p>

              <textarea
                value={nlPrompt}
                onChange={(e) => setNlPrompt(e.target.value)}
                placeholder="e.g. Navigate to Netflix, start a movie, apply 50% packet loss, verify playback degrades gracefully"
                rows={3}
                className="mb-3 w-full rounded border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />

              <button onClick={handleNlGenerate} disabled={!nlPrompt || nlGenerating} className={btnPrimary}>
                {nlGenerating ? 'Generating...' : 'Generate Test Flow'}
              </button>

              {nlGenerating && (
                <p className="mt-2 text-xs text-blue-500 dark:text-blue-400">
                  AI is analyzing your description and generating test steps...
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
