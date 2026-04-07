/**
 * Hook to fetch and check feature flags from the backend.
 * Features disabled by flags are hidden from the UI.
 *
 * The frontend uses conservative fallbacks so unsupported or experimental
 * surfaces do not briefly appear while flags are loading.
 */
import { useCallback } from 'react';
import { useApi } from './useApi';

interface FeatureFlag {
  enabled: boolean;
  label: string;
  description: string;
  category: string;
}

type Flags = Record<string, FeatureFlag>;

const FALLBACK_ENABLED: Record<string, boolean> = {
  impairments_network: true,
  impairments_wifi: true,
  impairments_profiles: true,
  sessions: true,
  captures: true,
  adb: true,
  ai_analysis: true,
  speed_test_iperf: true,
  wifi_scanner: true,
  dns_simulation: true,
  streams: true,
  teleport: true,
  speed_test_ookla: true,
  video_probe: true,
  hdmi_capture: false,
  sharing_tunnel: false,
  sharing_fileio: true,
  collaboration: false,
  gremlin: true,
};

export function useFeatureFlags() {
  const fetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/system/features');
      return res.ok ? res.json() : {};
    } catch {
      return {};
    }
  }, []);

  const { data: flags } = useApi<Flags>(fetcher);

  const isEnabled = (flagName: string): boolean => {
    const flag = flags?.[flagName];
    if (flag) return flag.enabled;
    if (flagName in FALLBACK_ENABLED) return FALLBACK_ENABLED[flagName];
    return false;
  };

  return { flags: flags ?? {}, isEnabled };
}
