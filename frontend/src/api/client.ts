/**
 * Typed API client for WiFry backend.
 */

import type {
  AdbDevice,
  AdbShellResult,
  AnalysisResult,
  ApStatus,
  CaptureFilters,
  CaptureInfo,
  ImpairmentConfig,
  InterfaceImpairmentState,
  InterfaceInfo,
  LogcatLine,
  LogcatSession,
  Profile,
  ProfileList,
  ProxyStatus,
  StreamSession,
  StreamSessionSummary,
  SystemInfo,
  SystemSettings,
  WifiClient,
} from '../types';

const BASE = '/api/v1';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
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

// --- Captures ---

export async function startCapture(params: {
  interface: string;
  name?: string;
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

export async function analyzeCapture(
  id: string,
  params?: { provider?: string; prompt?: string; focus?: string[] }
): Promise<AnalysisResult> {
  return request(`/captures/${id}/analyze`, {
    method: 'POST',
    body: JSON.stringify(params ?? {}),
  });
}

export async function getAnalysis(id: string): Promise<AnalysisResult> {
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
