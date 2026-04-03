/**
 * Hook to fetch and check feature flags from the backend.
 * Features disabled by flags are hidden from the UI.
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
    if (!flags) return true; // Default to showing everything while loading
    const flag = flags[flagName];
    return flag ? flag.enabled : true; // Unknown flags default to enabled
  };

  return { flags: flags ?? {}, isEnabled };
}
