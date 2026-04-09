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
  wifi_config?: WifiProfileConfig | null;
  dns_config?: DnsProfileConfig | null;
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
  load_avg?: number[];
  cpu_cores?: number;
  cpu_usage_pct?: number;
  memory_total_mb?: number;
  memory_used_mb?: number;
  memory_available_mb?: number | null;
  uptime?: string;
}

// Capture types

export type CaptureStatus = 'running' | 'processing' | 'completed' | 'stopped' | 'error';
export type HealthBadge = 'healthy' | 'degraded' | 'unhealthy' | 'insufficient';
export type Confidence = 'high' | 'medium' | 'low';
export type AnalysisPack = 'connectivity' | 'dns' | 'https' | 'streaming' | 'security' | 'custom';

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
  pack: string;
  filters: CaptureFilters;
  bpf_expression: string;
  started_at?: string | null;
  stopped_at?: string | null;
  packet_count: number;
  file_size_bytes: number;
  pcap_path: string;
  error?: string | null;
  health_badge?: string | null;
  has_summary: boolean;
  has_analysis: boolean;
  analysis_status?: string | null;
  analysis_error?: string | null;
}

// Analysis Pack

export interface PackConfig {
  id: AnalysisPack;
  name: string;
  description: string;
  icon: string;
  color: string;
  bpf: string;
  default_duration_secs: number;
  max_duration_secs: number;
  queries: string[];
  focus_areas: string[];
}

// Capture Summary (typed stats)

export interface ProtocolEntry {
  name: string;
  frames: number;
  bytes: number;
  pct: number;
}

export interface TcpHealth {
  total_segments: number;
  retransmission_count: number;
  retransmission_pct: number;
  fast_retransmission_count: number;
  duplicate_ack_count: number;
  zero_window_count: number;
  rst_count: number;
  out_of_order_count: number;
  window_full_count: number;
}

export interface Conversation {
  src: string;
  src_port: number;
  dst: string;
  dst_port: number;
  protocol: string;
  frames: number;
  bytes: number;
  duration_secs: number;
  bps: number;
}

export interface DnsSummary {
  total_queries: number;
  total_responses: number;
  unique_domains: number;
  nxdomain_count: number;
  servfail_count: number;
  timeout_count: number;
  avg_latency_ms: number;
  max_latency_ms: number;
  top_domains: Array<{ domain: string; count: number }>;
}

export interface ThroughputSample {
  interval_start: number;
  interval_end: number;
  frames: number;
  bytes: number;
  bps: number;
}

export interface ThroughputSummary {
  samples: ThroughputSample[];
  avg_bps: number;
  max_bps: number;
  min_bps: number;
  coefficient_of_variation: number;
}

export interface ExpertEntry {
  severity: string;
  group: string;
  summary: string;
  count: number;
}

export interface AnomalyFlag {
  metric: string;
  value: number;
  threshold: number;
  severity: string;
  label: string;
}

export interface InterestAnnotations {
  anomaly_flags: AnomalyFlag[];
  health_badge: HealthBadge;
}

export interface ProcessingStats {
  queue_wait_secs: number;
  processing_secs: number;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface CaptureSummary {
  meta: {
    capture_id: string;
    pack: string;
    interface: string;
    duration_secs: number;
    total_packets: number;
    total_bytes: number;
  };
  protocol_breakdown?: {
    total_frames: number;
    total_bytes: number;
    protocols: ProtocolEntry[];
    unencrypted_pct: number;
  } | null;
  tcp_health?: TcpHealth | null;
  conversations: Conversation[];
  dns?: DnsSummary | null;
  throughput?: ThroughputSummary | null;
  expert?: {
    entries: ExpertEntry[];
    error_count: number;
    warning_count: number;
    note_count: number;
  } | null;
  endpoints: Array<{ ip: string; frames: number; bytes: number }>;
  interest: InterestAnnotations;
  processing_stats?: ProcessingStats | null;
}

// V1 Analysis models (kept for compat)

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

// V2 Analysis models

export interface EvidenceCitation {
  metric: string;
  value: string;
  context: string;
}

export interface Finding {
  id: string;
  title: string;
  severity: string;
  confidence: Confidence;
  category: string;
  description: string;
  evidence: EvidenceCitation[];
  affected_flows: string[];
  likely_causes: string[];
  next_steps: string[];
  cross_references: string[];
}

export interface InsufficientEvidenceNote {
  area: string;
  reason: string;
  suggestion: string;
}

export interface AnalysisResultV2 {
  capture_id: string;
  pack: string;
  summary: string;
  health_badge: HealthBadge;
  findings: Finding[];
  insufficient_evidence: InsufficientEvidenceNote[];
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
  ai_model: string;
  anthropic_api_key_set: boolean;
  openai_api_key_set: boolean;
  dns_enabled: boolean;
}

export interface AiModelInfo {
  id: string;
  name: string;
  tier: string;
}

// EXPERIMENTAL_VIDEO_CAPTURE — Frame analysis types

export interface FocusedElement {
  element_type: string;
  label: string;
  position: string;
  confidence: string;
}

export interface FrameAnalysisResult {
  screen_type: string;
  screen_title: string | null;
  focused_element: FocusedElement | null;
  navigation_path: string[] | null;
  visible_text_summary: string;
  raw_description: string;
  provider: string;
  model: string;
  tokens_used: number;
  analyzed_at: string;
  error: string | null;
}

export interface FeatureFlag {
  enabled: boolean;
  label: string;
  description: string;
  category: string;
}

export type FeatureFlags = Record<string, FeatureFlag>;

export interface ActiveSessionInfo {
  active_session_id: string | null;
  session_name?: string | null;
}

export interface WifiFeatureSupport {
  supported: boolean;
  reason: string;
}

export interface WifiCapabilities {
  features: Record<string, WifiFeatureSupport>;
  [key: string]: unknown;
}

export interface WifiImpairmentState {
  config: Record<string, Record<string, unknown>>;
  active_impairments: string[];
  disconnect_count: number;
  storm_active: boolean;
}

export interface WifiProfileConfig {
  tx_power?: {
    enabled?: boolean;
    power_dbm?: number;
  };
  channel_interference?: {
    enabled?: boolean;
    beacon_interval_ms?: number;
    rts_threshold?: number;
  };
  periodic_disconnect?: {
    enabled?: boolean;
    interval_secs?: number;
  };
  broadcast_storm?: {
    enabled?: boolean;
  };
  rate_limit?: {
    enabled?: boolean;
    legacy_rate_mbps?: number;
  };
  dhcp_disruption?: {
    enabled?: boolean;
    mode?: string;
  };
  band_switch?: {
    enabled?: boolean;
    target_band?: string;
  };
}

export interface DnsProfileConfig {
  enabled?: boolean;
  impairments?: {
    delay_ms?: number;
    failure_rate_pct?: number;
    servfail_rate_pct?: number;
    nxdomain_domains?: string[];
    ttl_override?: number;
  };
  upstream?: {
    provider?: string;
  };
}

export interface WifiNetwork {
  ssid: string;
  bssid: string;
  channel: number;
  frequency_mhz: number;
  signal_dbm: number;
  security: string;
  band: string;
  width: string;
}

export interface WifiChannelInfo {
  channel: number;
  frequency_mhz: number;
  band: string;
  network_count: number;
  strongest_signal_dbm: number;
  networks: string[];
}

export interface WifiScanData {
  scan_interface: string;
  our_channel: number;
  our_band: string;
  network_count: number;
  networks: WifiNetwork[];
  channels_2g: WifiChannelInfo[];
  channels_5g: WifiChannelInfo[];
}

export interface GremlinStatus {
  active: boolean;
  intensity: number;
  intensity_label: string;
  stall_count: number;
  activated_at: string | null;
  message: string;
  details: {
    drop_pct: number;
    tls_delay_ms: number;
    tls_jitter_ms: number;
    stall_interval: string;
  };
}

// STB_AUTOMATION types

export interface StbUIElement {
  resource_id: string;
  text: string;
  class_name: string;
  package: string;
  content_desc: string;
  bounds: string;
  focused: boolean;
  clickable: boolean;
  selected: boolean;
}

export interface StbLogcatEvent {
  event_type: string;
  package: string;
  activity: string;
  detail: string;
  timestamp: string;
  raw: string;
}

export interface StbVisionAnalysis {
  screen_type: string;
  screen_title: string;
  focused_label: string;
  focused_position: string;
  focused_confidence: string;
  navigation_path: string[];
  visible_text: string;
  raw_description: string;
  provider: string;
  tokens_used: number;
}

export interface StbScreenState {
  package: string;
  activity: string;
  ui_elements: StbUIElement[];
  focused_element: StbUIElement | null;
  focused_context: string;
  window_title: string;
  fragments: string[];
  vision: StbVisionAnalysis | null;
  recent_events: StbLogcatEvent[];
  timestamp: string;
}

export interface StbVisionDiag {
  cache_hit: boolean;
  cache_key: string;
  cache_key_source: string;
  cache_age_ms: number;
  cache_size: number;
  api_call_ms: number;
  error: string | null;
  streamer_running: boolean;
  // Perceptual hash diagnostics
  nav_sequence: number;
  cached_nav_sequence: number;
  hamming_distance: number;
  hamming_threshold: number;
  hash_type: string;
  invalidation_reason: string;
  // Hit ratio
  cache_hits_total: number;
  cache_misses_total: number;
  cache_hit_ratio_pct: number;
}

export interface StbVisionCacheEntry {
  hash_key: string;
  screen_type: string;
  screen_title: string;
  focused_label: string;
  tokens_used: number;
}

export interface StbVisionCacheDebug {
  size: number;
  max_size: number;
  threshold: number;
  nav_sequence: number;
  has_perceptual_hash: boolean;
  hits_total: number;
  misses_total: number;
  hit_ratio_pct: number;
  entries: StbVisionCacheEntry[];
}

export interface UIMapDiag {
  screen_key: string;
  last_action: string;
  from_focused: string;
  to_focused: string;
  observation_recorded: boolean;
  observation_skipped_reason: string;
  prediction_available: boolean;
  prediction_confidence: number;
  prediction_observations: number;
  map_entries_for_screen: number;
}

export interface StbScreenStateDiag {
  fingerprint: string;
  visual_hash: string;
  fingerprint_inputs: string;
  vision: StbVisionDiag | null;
  ui_map: UIMapDiag | null;
  adb_signals: number;
  read_ms: number;
  // Per-stage timing breakdown
  adb_foreground_ms?: number;
  adb_hierarchy_ms?: number;
  adb_fragments_ms?: number;
  adb_window_title_ms?: number;
  adb_total_ms?: number;
  fingerprint_ms?: number;
  frame_hash_ms?: number;
  total_ms?: number;
  vision_fast_path?: boolean;
}

export interface StbScreenStateResponse {
  state: StbScreenState;
  fingerprint: string;
  diag: StbScreenStateDiag | null;
}

export interface StbCrawlStatus {
  state: string;
  current_node_id: string | null;
  current_phase: string;
  current_action: string;
  nodes_discovered: number;
  transitions_executed: number;
  transitions_skipped: number;
  ai_calls_saved: number;
  unexplored_targets: number;
  elapsed_secs: number;
  avg_action_ms: number;
  error: string | null;
}

export interface StbStatus {
  logcat_monitor_active: boolean;
  logcat_session_id: string | null;
  logcat_serial: string | null;
  crawl: StbCrawlStatus;
}

export interface StbNavigateTimingDetail {
  foreground_ms: number;
  hierarchy_ms: number;
  fragments_ms: number;
  window_title_ms: number;
  total_ms: number;
}

export interface StbNavigateSignals {
  package: string;
  activity: string;
  window_title: string;
  fragments: string[];
  focused_element: string | null;
  focused_context: string;
  ui_elements_count: number;
}

export interface StbNavigateTiming {
  pre_state_ms: number;
  key_press_ms: number;
  settle_wait_ms: number;
  settle_read_ms: number;
  settle_read_detail: StbNavigateTimingDetail;
  post_fingerprint_ms: number;
  total_ms: number;
  signals?: StbNavigateSignals;
}

export interface StbNavigateResponse {
  action: string;
  pre_state: StbScreenState;
  post_state: StbScreenState;
  pre_fingerprint: string;
  post_fingerprint: string;
  transitioned: boolean;
  settle_method: string;
  settle_ms: number;
  timing?: StbNavigateTiming;
}

// UI Map (learned menu patterns)
export interface UIMapEntry {
  screen_key: string;
  action: string;
  from_element: string;
  to_element: string;
  to_screen_key?: string;
  to_screen_type: string;
  to_screen_title: string;
  to_focused_position: string;
  to_focused_confidence: string;
  to_navigation_path: string[];
  observation_count: number;
  confidence: number;
  avg_transition_ms?: number;
  no_effect_count?: number;
  last_observed: string;
  sources?: string[];
}

export interface UIMapScreenSummary {
  screen_key: string;
  entry_count: number;
  avg_confidence: number;
  max_observations: number;
}

export interface UIMapStats {
  total_screens: number;
  total_entries: number;
  total_observations: number;
  total_predictions: number;
  total_prediction_hits: number;
  total_prediction_misses: number;
  prediction_accuracy_pct: number;
}

export interface UIMapResponse {
  screens: UIMapScreenSummary[];
  stats: UIMapStats;
}

export interface UIMapGraphNode {
  id: string;
  label: string;
  screen_key: string;
  screen_type?: string;
}

export interface UIMapGraphEdge {
  from: string;
  to: string;
  action: string;
  confidence: number;
  observations: number;
  screen_key: string;
}

export interface UIMapGraph {
  nodes: UIMapGraphNode[];
  edges: UIMapGraphEdge[];
  screens: string[];
  stats: UIMapStats;
}

export interface StbTransitionEdge {
  from_node: string;
  to_node: string;
  action: string;
  success_count: number;
  no_effect_count: number;
  avg_transition_ms: number;
  settle_method: string;
}

export interface StbScreenNode {
  id: string;
  fingerprint: string;
  screen_type: string;
  title: string;
  package: string;
  activity: string;
  elements: StbUIElement[];
  vision_analysis: Record<string, unknown> | null;
  visit_count: number;
  last_visited: string;
}

export interface StbNavigationModel {
  device_id: string;
  device_model: string;
  created_at: string;
  updated_at: string;
  home_node_id: string;
  nodes: Record<string, StbScreenNode>;
  edges: StbTransitionEdge[];
}

export interface StbPathResponse {
  found: boolean;
  actions: string[];
  hop_count: number;
}

export interface StbAnomalyPattern {
  name: string;
  pattern: string;
  tags: string[];
  severity: string;
  category: string;
}

export interface StbDetectedAnomaly {
  pattern_name: string;
  severity: string;
  category: string;
  timestamp: string;
  logcat_line: StbLogcatEvent | null;
  vision_state: string | null;
  context_lines: string[];
  diagnostics_collected: boolean;
  artifact_ids: string[];
}

export interface StbDiagnosticsResult {
  collected_at: string;
  reason: string;
  severity: string;
  artifacts: string[];
  screenshot?: string;
  bugreport?: string;
  screenshot_error?: string;
  bugreport_error?: string;
}

export interface StbTestStep {
  action: string;
  expected_screen_id: string | null;
  expected_activity: string | null;
  wait_ms: number;
  description: string;
  collect_diagnostics: boolean;
}

export interface StbTestFlow {
  id: string;
  name: string;
  description: string;
  serial: string;
  steps: StbTestStep[];
  created_at: string;
  updated_at: string;
  source: string;
}

export interface StbTestFlowRun {
  flow_id: string;
  state: string;
  current_step: number;
  steps_passed: number;
  steps_failed: number;
  anomalies_detected: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface StbChaosConfig {
  serial: string;
  duration_secs?: number;
  seed?: number | null;
  key_weights?: Record<string, number>;
  on_anomaly?: string;
  enable_vision_checks?: boolean;
  vision_check_interval_secs?: number;
}

export interface StbChaosResult {
  state: string;
  duration_secs: number;
  keys_sent: number;
  screens_visited: number;
  anomalies: StbDetectedAnomaly[];
  seed_used: number;
}

export interface StbNLGenerateRequest {
  prompt: string;
  serial: string;
  device_id?: string | null;
  provider?: string | null;
  model?: string | null;
}

export interface StbNLRefineRequest {
  refinement: string;
  provider?: string | null;
  model?: string | null;
}

export interface StbVisionEnrichment {
  enriched: boolean;
  error?: string;
  screen_type?: string;
  screen_title?: string | null;
  focused_element?: {
    element_type: string;
    label: string;
    position: string;
    confidence: string;
  } | null;
  navigation_path?: string[] | null;
  visible_text_summary?: string;
  provider?: string;
  model?: string;
  tokens_used?: number;
}
