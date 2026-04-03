// Impairment types matching backend models

export interface DelayConfig {
  ms: number;
  jitter_ms: number;
  correlation_pct: number;
}

export interface LossConfig {
  pct: number;
  correlation_pct: number;
}

export interface CorruptConfig {
  pct: number;
}

export interface DuplicateConfig {
  pct: number;
}

export interface ReorderConfig {
  pct: number;
  correlation_pct: number;
}

export interface RateConfig {
  kbit: number;
  burst: string;
}

export interface ImpairmentConfig {
  delay?: DelayConfig | null;
  loss?: LossConfig | null;
  corrupt?: CorruptConfig | null;
  duplicate?: DuplicateConfig | null;
  reorder?: ReorderConfig | null;
  rate?: RateConfig | null;
}

export interface InterfaceImpairmentState {
  interface: string;
  active: boolean;
  config: ImpairmentConfig;
  per_client: Record<string, ImpairmentConfig>;
}

// Profile types

export interface Profile {
  name: string;
  description: string;
  builtin: boolean;
  category: string;
  tags: string[];
  config: ImpairmentConfig;
  wifi_config?: Record<string, unknown> | null;
}

export interface ProfileList {
  profiles: Profile[];
}

// Network types

export interface InterfaceInfo {
  name: string;
  mac: string;
  ipv4: string;
  state: string;
  type: string;
  speed: string;
}

export interface WifiClient {
  mac: string;
  ip: string;
  hostname: string;
  signal_dbm: number;
  connected_time: string;
}

export interface ApStatus {
  ssid: string;
  channel: number;
  band: string;
  interface: string;
  client_count: number;
  active: boolean;
}

// System types

export interface SystemInfo {
  model: string;
  platform: string;
  os: string;
  temperature_c?: number | null;
  memory_total_mb?: number;
  memory_used_mb?: number;
  memory_available_mb?: number | null;
  uptime?: string;
}

// Capture types

export type CaptureStatus = 'running' | 'completed' | 'stopped' | 'error';

export interface CaptureFilters {
  host?: string | null;
  port?: number | null;
  protocol?: string | null;
  direction?: string | null;
  custom_bpf?: string | null;
}

export interface CaptureInfo {
  id: string;
  name: string;
  interface: string;
  status: CaptureStatus;
  filters: CaptureFilters;
  bpf_expression: string;
  started_at?: string | null;
  stopped_at?: string | null;
  packet_count: number;
  file_size_bytes: number;
  pcap_path: string;
  error?: string | null;
}

export interface AnalysisIssue {
  severity: string;
  category: string;
  description: string;
  affected_flows: string[];
  recommendation: string;
}

export interface AnalysisResult {
  capture_id: string;
  summary: string;
  issues: AnalysisIssue[];
  statistics: Record<string, unknown>;
  provider: string;
  model: string;
  tokens_used: number;
  analyzed_at?: string | null;
}

// Stream types

export type StreamType = 'hls' | 'dash' | 'unknown';

export interface VariantInfo {
  bandwidth: number;
  resolution: string;
  codecs: string;
  url: string;
  frame_rate?: number | null;
}

export interface SegmentInfo {
  url: string;
  sequence: number;
  duration_secs: number;
  download_time_secs: number;
  size_bytes: number;
  bitrate_bps: number;
  throughput_bps: number;
  timestamp: string;
  status_code: number;
  saved_path?: string | null;
}

export interface StreamSessionSummary {
  id: string;
  stream_type: StreamType;
  client_ip: string;
  active: boolean;
  current_bitrate_bps: number;
  resolution: string;
  buffer_health_secs: number;
  throughput_ratio: number;
  bitrate_switches: number;
  segment_errors: number;
  total_segments: number;
  started_at: string;
  last_activity: string;
}

export interface StreamSession extends StreamSessionSummary {
  master_url: string;
  variants: VariantInfo[];
  active_variant?: VariantInfo | null;
  segments: SegmentInfo[];
  avg_throughput_bps: number;
  rebuffer_events: number;
}

export interface ProxyStatus {
  enabled: boolean;
  running: boolean;
  port: number;
  save_segments: boolean;
  max_storage_mb: number;
  cert_installed_hint: string;
  intercepted_flows: number;
}

// ADB types

export type AdbDeviceState = 'connected' | 'disconnected' | 'offline' | 'unauthorized';

export interface AdbDevice {
  serial: string;
  state: AdbDeviceState;
  model: string;
  product: string;
  manufacturer: string;
  android_version: string;
  sdk_version: string;
  display_resolution: string;
}

export interface AdbShellResult {
  serial: string;
  command: string;
  stdout: string;
  stderr: string;
  exit_code: number;
}

export interface LogcatSession {
  id: string;
  serial: string;
  filters: string[];
  active: boolean;
  started_at: string;
  line_count: number;
  scenario_id?: string | null;
}

export interface LogcatLine {
  timestamp: string;
  pid: string;
  tid: string;
  level: string;
  tag: string;
  message: string;
  raw: string;
}

export interface SystemSettings {
  mock_mode: boolean;
  ap_ssid: string;
  ap_channel: number;
  ap_band: string;
  ai_provider: string;
  anthropic_api_key_set: boolean;
  openai_api_key_set: boolean;
  dns_enabled: boolean;
}
