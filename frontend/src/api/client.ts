/**
 * Typed API client for WiFry backend.
 */

import type {
  ActiveSessionInfo,
  AdbDevice,
  AdbShellResult,
  AnalysisResultV2,
  ApStatus,
  CaptureFilters,
  CaptureInfo,
  CaptureSummary,
  FeatureFlags,
  GremlinStatus,
  ImpairmentConfig,
  InterfaceImpairmentState,
  InterfaceInfo,
  LogcatLine,
  LogcatSession,
  PackConfig,
  Profile,
  ProfileList,
  ProxyStatus,
  StreamSession,
  StreamSessionSummary,
  SystemInfo,
  SystemSettings,
  WifiCapabilities,
  WifiClient,
  WifiImpairmentState,
  WifiScanData,
} from '../types';

const BASE = '/api/v1';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (options?.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
  });
  const body = await res.text();

  if (!res.ok) {
    throw new Error(body ? `API ${res.status}: ${body}` : `API ${res.status}`);
  }

  if (!body) {
    return undefined as T;
  }

  const contentType = res.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    return JSON.parse(body) as T;
  }

  return body as T;
}

// --- Impairments ---

export async function getImpairments(): Promise<InterfaceImpairmentState[]> {
  return request('/impairments');
}

export async function getImpairment(iface: string): Promise<InterfaceImpairmentState> {
  return request(`/impairments/${iface}`);
}

export async function applyImpairment(
  iface: string,
  config: ImpairmentConfig
): Promise<InterfaceImpairmentState> {
  return request(`/impairments/${iface}`, {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

export async function clearImpairment(iface: string): Promise<void> {
  await request(`/impairments/${iface}`, { method: 'DELETE' });
}

export async function clearAllImpairments(): Promise<void> {
  await request('/impairments', { method: 'DELETE' });
}

// --- Profiles ---

export async function getProfiles(): Promise<ProfileList> {
  return request('/profiles');
}

export async function getProfile(name: string): Promise<Profile> {
  return request(`/profiles/${encodeURIComponent(name)}`);
}

export async function createProfile(profile: Profile): Promise<Profile> {
  return request('/profiles', {
    method: 'POST',
    body: JSON.stringify(profile),
  });
}

export async function deleteProfile(name: string): Promise<void> {
  await request(`/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export async function applyProfile(
  name: string,
  interfaces?: string[]
): Promise<void> {
  await request(`/profiles/${encodeURIComponent(name)}/apply`, {
    method: 'POST',
    body: JSON.stringify({ interfaces: interfaces ?? [] }),
  });
}

// --- Network ---

export async function getInterfaces(): Promise<InterfaceInfo[]> {
  return request('/network/interfaces');
}

export async function getClients(): Promise<WifiClient[]> {
  return request('/network/clients');
}

export async function getApStatus(): Promise<ApStatus> {
  return request('/network/ap/status');
}

export async function getWifiScan(): Promise<WifiScanData> {
  return request('/wifi/scan');
}

export async function getWifiImpairments(): Promise<WifiImpairmentState> {
  return request('/wifi-impairments');
}

export async function getWifiImpairmentCapabilities(): Promise<WifiCapabilities> {
  return request('/wifi-impairments/capabilities');
}

export async function updateWifiImpairments(config: Record<string, Record<string, unknown>>): Promise<void> {
  await request('/wifi-impairments', {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

export async function clearWifiImpairments(): Promise<void> {
  await request('/wifi-impairments', { method: 'DELETE' });
}

// --- Captures ---

export async function getPacks(): Promise<PackConfig[]> {
  return request('/captures/packs');
}

export async function startCapture(params: {
  interface: string;
  name?: string;
  pack?: string;
  filters?: CaptureFilters;
  max_packets?: number;
  max_duration_secs?: number;
  max_file_size_mb?: number;
}): Promise<CaptureInfo> {
  return request('/captures', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function getCaptures(): Promise<CaptureInfo[]> {
  return request('/captures');
}

export async function getCapture(id: string): Promise<CaptureInfo> {
  return request(`/captures/${id}`);
}

export async function stopCapture(id: string): Promise<CaptureInfo> {
  return request(`/captures/${id}/stop`, { method: 'POST' });
}

export async function deleteCapture(id: string): Promise<void> {
  await request(`/captures/${id}`, { method: 'DELETE' });
}

export async function getCaptureSummary(id: string): Promise<CaptureSummary> {
  return request(`/captures/${id}/summary`);
}

export async function getCaptureStatus(): Promise<{
  active_captures: number;
  max_concurrent: number;
  storage: { capture_count: number; total_mb: number; max_storage_mb: number; usage_pct: number };
}> {
  return request('/captures/status');
}

export async function analyzeCapture(
  id: string,
  params?: { provider?: string; prompt?: string; focus?: string[]; pack?: string }
): Promise<{ status: string; capture_id: string; message: string }> {
  return request(`/captures/${id}/analyze`, {
    method: 'POST',
    body: JSON.stringify(params ?? {}),
  });
}

export async function getAnalysis(id: string): Promise<AnalysisResultV2> {
  return request(`/captures/${id}/analysis`);
}

// --- Streams ---

export async function getStreams(): Promise<StreamSessionSummary[]> {
  return request('/streams');
}

export async function getStream(id: string): Promise<StreamSession> {
  return request(`/streams/${id}`);
}

// --- Proxy ---

export async function getProxyStatus(): Promise<ProxyStatus> {
  return request('/proxy/status');
}

export async function enableProxy(): Promise<ProxyStatus> {
  return request('/proxy/enable', { method: 'POST' });
}

export async function disableProxy(): Promise<ProxyStatus> {
  return request('/proxy/disable', { method: 'POST' });
}

export async function updateProxySettings(settings: {
  save_segments?: boolean;
  max_storage_mb?: number;
}): Promise<ProxyStatus> {
  return request('/proxy/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

// --- ADB ---

export async function getAdbDevices(): Promise<AdbDevice[]> {
  return request('/adb/devices');
}

export async function connectAdbDevice(ip: string, port: number = 5555): Promise<AdbDevice> {
  return request('/adb/connect', {
    method: 'POST',
    body: JSON.stringify({ ip, port }),
  });
}

export async function disconnectAdbDevice(serial: string): Promise<AdbDevice> {
  return request(`/adb/disconnect/${encodeURIComponent(serial)}`, { method: 'POST' });
}

export async function adbShell(serial: string, command: string): Promise<AdbShellResult> {
  return request('/adb/shell', {
    method: 'POST',
    body: JSON.stringify({ serial, command }),
  });
}

export async function adbSendKey(serial: string, keycode: string): Promise<void> {
  await request('/adb/key', {
    method: 'POST',
    body: JSON.stringify({ serial, keycode }),
  });
}

export async function getAdbKeycodes(): Promise<Record<string, string>> {
  return request('/adb/keycodes');
}

export async function startLogcat(serial: string, scenarioId?: string): Promise<LogcatSession> {
  const params = new URLSearchParams({ serial });
  if (scenarioId) params.set('scenario_id', scenarioId);
  return request(`/adb/logcat/start?${params}`, { method: 'POST' });
}

export async function stopLogcat(sessionId: string): Promise<LogcatSession> {
  return request(`/adb/logcat/${sessionId}/stop`, { method: 'POST' });
}

export async function getLogcatSessions(): Promise<LogcatSession[]> {
  return request('/adb/logcat');
}

export async function getLogcatLines(
  sessionId: string,
  lastN: number = 200,
  level?: string,
  tag?: string,
): Promise<LogcatLine[]> {
  const params = new URLSearchParams({ last_n: String(lastN) });
  if (level) params.set('level', level);
  if (tag) params.set('tag', tag);
  return request(`/adb/logcat/${sessionId}/lines?${params}`);
}

// --- System ---

export async function getSystemInfo(): Promise<SystemInfo> {
  return request('/system/info');
}

export async function getSettings(): Promise<SystemSettings> {
  return request('/system/settings');
}

export async function getAiModels(provider?: string): Promise<{
  provider: string;
  models: Array<{ id: string; name: string; tier: string }>;
}> {
  const params = provider ? `?provider=${encodeURIComponent(provider)}` : '';
  return request(`/system/ai-models${params}`);
}

export async function getFeatureFlags(): Promise<FeatureFlags> {
  return request('/system/features');
}

export async function getActiveSession(): Promise<ActiveSessionInfo> {
  return request('/sessions/active');
}

export async function getGremlinStatus(): Promise<GremlinStatus> {
  return request('/gremlin/status');
}

export async function activateGremlin(intensity: number): Promise<GremlinStatus> {
  return request(`/gremlin/activate?intensity=${intensity}`, { method: 'POST' });
}

export async function deactivateGremlin(): Promise<GremlinStatus> {
  return request('/gremlin/deactivate', { method: 'POST' });
}

// EXPERIMENTAL_VIDEO_CAPTURE — Live video stream endpoints
export async function getVideoStatus(): Promise<{ device: Record<string, unknown>; streaming: boolean; clients: number }> {
  return request('/experimental/video/status');
}

export async function startVideoStream(): Promise<{ status: string; device?: string; resolution?: string; fps?: number; message?: string }> {
  return request('/experimental/video/start', { method: 'POST' });
}

export async function stopVideoStream(): Promise<{ status: string }> {
  return request('/experimental/video/stop', { method: 'POST' });
}

// EXPERIMENTAL_VIDEO_CAPTURE — Frame analysis endpoints
export async function getVideoSnapshot(): Promise<{ image: string; format: string; size_bytes: number; captured_at: string }> {
  return request('/experimental/video/snapshot');
}

export async function analyzeVideoFrame(params?: { provider?: string; model?: string }): Promise<import('../types').FrameAnalysisResult> {
  return request('/experimental/video/analyze', {
    method: 'POST',
    body: JSON.stringify(params ?? {}),
  });
}

// STB_AUTOMATION — STB test automation endpoints
export async function getStbStatus(): Promise<import('../types').StbStatus> {
  return request('/experimental/stb/status');
}

export async function getStbState(serial: string, includeHierarchy: boolean = true, includeVision: boolean = false, visionThreshold?: number, signal?: AbortSignal, visionPrompt?: string): Promise<import('../types').StbScreenStateResponse> {
  const params = new URLSearchParams({ serial, include_hierarchy: String(includeHierarchy), include_vision: String(includeVision) });
  if (visionThreshold !== undefined) params.set('vision_threshold', String(visionThreshold));
  if (visionPrompt) params.set('vision_prompt', visionPrompt);
  return request(`/experimental/stb/state?${params}`, signal ? { signal } : undefined);
}

export async function getStbVisionPrompt(): Promise<{ system_prompt: string; user_prompt: string }> {
  return request('/experimental/stb/vision/prompt');
}

export async function getStbVisionCache(): Promise<import('../types').StbVisionCacheDebug> {
  return request('/experimental/stb/vision/cache');
}

export async function clearStbVisionCache(): Promise<{ cleared: number }> {
  return request('/experimental/stb/vision/cache', { method: 'DELETE' });
}

// UI Map
export async function getUIMap(): Promise<import('../types').UIMapResponse> {
  return request('/experimental/stb/ui-map');
}

export async function getUIMapScreen(screenKey: string): Promise<{ screen_key: string; entries: import('../types').UIMapEntry[] }> {
  return request(`/experimental/stb/ui-map/screen?screen_key=${encodeURIComponent(screenKey)}`);
}

export async function getUIMapGraph(): Promise<import('../types').UIMapGraph> {
  return request('/experimental/stb/ui-map/graph');
}

export async function getUIMapStats(): Promise<import('../types').UIMapStats> {
  return request('/experimental/stb/ui-map/stats');
}

export async function clearUIMap(): Promise<{ cleared: number }> {
  return request('/experimental/stb/ui-map', { method: 'DELETE' });
}

export async function getStbEvents(lastN: number = 20): Promise<import('../types').StbLogcatEvent[]> {
  return request(`/experimental/stb/events?last_n=${lastN}`);
}

export async function startStbMonitor(serial: string, tags?: string[]): Promise<{ status: string; session_id?: string; serial?: string }> {
  return request('/experimental/stb/monitor/start', {
    method: 'POST',
    body: JSON.stringify({ serial, tags }),
  });
}

export async function stopStbMonitor(): Promise<{ status: string }> {
  return request('/experimental/stb/monitor/stop', { method: 'POST' });
}

export async function stbNavigate(serial: string, action: string, settleTimeoutMs: number = 3000): Promise<import('../types').StbNavigateResponse> {
  return request('/experimental/stb/navigate', {
    method: 'POST',
    body: JSON.stringify({ serial, action, settle_timeout_ms: settleTimeoutMs }),
  });
}

// STB_AUTOMATION — Crawl + navigation model endpoints
export async function startStbCrawl(config: { serial: string; max_depth?: number; max_transitions?: number; settle_timeout_ms?: number; explore_actions?: string[] }): Promise<import('../types').StbCrawlStatus> {
  return request('/experimental/stb/crawl/start', { method: 'POST', body: JSON.stringify(config) });
}

export async function stopStbCrawl(): Promise<import('../types').StbCrawlStatus> {
  return request('/experimental/stb/crawl/stop', { method: 'POST' });
}

export async function stbCrawlStep(config: { serial: string; explore_actions?: string[] }): Promise<Record<string, unknown>> {
  return request('/experimental/stb/crawl/step', { method: 'POST', body: JSON.stringify(config) });
}

export async function getStbModel(deviceId: string): Promise<import('../types').StbNavigationModel> {
  return request(`/experimental/stb/model?device_id=${encodeURIComponent(deviceId)}`);
}

export async function getStbModelNode(deviceId: string, nodeId: string): Promise<import('../types').StbScreenNode> {
  return request(`/experimental/stb/model/${nodeId}?device_id=${encodeURIComponent(deviceId)}`);
}

export async function findStbPath(deviceId: string, fromNode: string, toNode: string): Promise<import('../types').StbPathResponse> {
  return request('/experimental/stb/model/path', { method: 'POST', body: JSON.stringify({ device_id: deviceId, from_node: fromNode, to_node: toNode }) });
}

export async function deleteStbModel(deviceId: string): Promise<{ deleted: boolean; device_id: string }> {
  return request(`/experimental/stb/model?device_id=${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
}

// STB_AUTOMATION — Anomaly detection endpoints
export async function getStbAnomalies(lastN: number = 50): Promise<import('../types').StbDetectedAnomaly[]> {
  return request(`/experimental/stb/anomalies?last_n=${lastN}`);
}

export async function getStbAnomalyPatterns(): Promise<import('../types').StbAnomalyPattern[]> {
  return request('/experimental/stb/anomalies/patterns');
}

export async function setStbAnomalyPatterns(patterns: import('../types').StbAnomalyPattern[]): Promise<import('../types').StbAnomalyPattern[]> {
  return request('/experimental/stb/anomalies/patterns', {
    method: 'PUT',
    body: JSON.stringify(patterns),
  });
}

export async function collectStbDiagnostics(serial: string, reason: string = 'manual', severity: string = 'medium'): Promise<import('../types').StbDiagnosticsResult> {
  return request('/experimental/stb/diagnostics/collect', {
    method: 'POST',
    body: JSON.stringify({ serial, reason, severity }),
  });
}

// STB_AUTOMATION — Test flow endpoints
export async function listStbFlows(): Promise<import('../types').StbTestFlow[]> {
  return request('/experimental/stb/flows');
}

export async function getStbFlow(flowId: string): Promise<import('../types').StbTestFlow> {
  return request(`/experimental/stb/flows/${flowId}`);
}

export async function createStbFlow(params: { name: string; serial: string; description?: string; steps?: import('../types').StbTestStep[]; source?: string }): Promise<import('../types').StbTestFlow> {
  return request('/experimental/stb/flows', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function updateStbFlow(flowId: string, updates: { name?: string; description?: string; serial?: string; steps?: import('../types').StbTestStep[] }): Promise<import('../types').StbTestFlow> {
  return request(`/experimental/stb/flows/${flowId}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
}

export async function deleteStbFlow(flowId: string): Promise<{ deleted: boolean; flow_id: string }> {
  return request(`/experimental/stb/flows/${flowId}`, { method: 'DELETE' });
}

export async function runStbFlow(flowId: string): Promise<import('../types').StbTestFlowRun> {
  return request(`/experimental/stb/flows/${flowId}/run`, { method: 'POST' });
}

export async function stopStbFlow(flowId: string): Promise<Record<string, unknown>> {
  return request(`/experimental/stb/flows/${flowId}/stop`, { method: 'POST' });
}

export async function getStbFlowResults(flowId: string): Promise<import('../types').StbTestFlowRun> {
  return request(`/experimental/stb/flows/${flowId}/results`);
}

export async function startStbRecording(name: string, serial: string, description: string = ''): Promise<import('../types').StbTestFlow> {
  return request('/experimental/stb/flows/record/start', {
    method: 'POST',
    body: JSON.stringify({ name, serial, description }),
  });
}

export async function stopStbRecording(): Promise<Record<string, unknown>> {
  return request('/experimental/stb/flows/record/stop', { method: 'POST' });
}

// STB_AUTOMATION — Chaos mode endpoints
export async function startStbChaos(config: import('../types').StbChaosConfig): Promise<import('../types').StbChaosResult> {
  return request('/experimental/stb/chaos/start', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function stopStbChaos(): Promise<import('../types').StbChaosResult> {
  return request('/experimental/stb/chaos/stop', { method: 'POST' });
}

export async function getStbChaosStatus(): Promise<import('../types').StbChaosResult> {
  return request('/experimental/stb/chaos/status');
}

// STB_AUTOMATION — Natural language test generation endpoints
export async function generateStbFlow(params: import('../types').StbNLGenerateRequest): Promise<import('../types').StbTestFlow> {
  return request('/experimental/stb/nl/generate', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function refineStbFlow(flowId: string, params: import('../types').StbNLRefineRequest): Promise<import('../types').StbTestFlow> {
  return request(`/experimental/stb/nl/refine/${flowId}`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

// STB_AUTOMATION — Vision enrichment endpoint
export async function enrichStbState(serial: string): Promise<import('../types').StbVisionEnrichment> {
  return request(`/experimental/stb/state/enrich?serial=${encodeURIComponent(serial)}`, {
    method: 'POST',
  });
}
