export type Tab = 'sessions' | 'impairments' | 'adb' | 'captures' | 'streams' | 'system';
export type LegacyTab = Tab | 'sharing';
export type ImpairmentSubTab = 'profiles' | 'network' | 'wifi' | 'dns' | 'teleport';
export type SystemSubTab = 'overview' | 'network' | 'remote' | 'tools' | 'settings';

export type NavState = {
  tab: Tab;
  impSubTab: ImpairmentSubTab;
  sysSubTab: SystemSubTab;
  analyzingCaptureId: string | null;
  selectedStreamId: string | null;
};

export type DashboardTabOption<T extends string> = {
  id: T;
  label: string;
  desc?: string;
};

export type FeatureFlagChecker = (flagName: string) => boolean;

export const TABS: DashboardTabOption<Tab>[] = [
  { id: 'sessions', label: 'Sessions', desc: 'Primary workflow for test evidence and bundle sharing' },
  { id: 'impairments', label: 'Impairments', desc: 'Control network conditions' },
  { id: 'adb', label: 'ADB', desc: 'Android device control' },
  { id: 'captures', label: 'Captures', desc: 'Packet capture + AI analysis' },
  { id: 'streams', label: 'Streams', desc: 'HLS/DASH stream monitoring' },
  { id: 'system', label: 'System', desc: 'Network setup, remote access, and admin tools' },
];

export const IMPAIRMENT_SUBTABS: DashboardTabOption<ImpairmentSubTab>[] = [
  { id: 'profiles', label: 'Profiles' },
  { id: 'network', label: 'Network' },
  { id: 'wifi', label: 'WiFi' },
  { id: 'dns', label: 'DNS' },
  { id: 'teleport', label: 'Teleport' },
];

export const SYSTEM_SUBTABS: DashboardTabOption<SystemSubTab>[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'network', label: 'Network Config' },
  { id: 'remote', label: 'Remote Access' },
  { id: 'tools', label: 'Tools' },
  { id: 'settings', label: 'App Settings' },
];

export const DEFAULT_NAV_STATE: NavState = {
  tab: 'sessions',
  impSubTab: 'profiles',
  sysSubTab: 'overview',
  analyzingCaptureId: null,
  selectedStreamId: null,
};

export function normalizeNavState(
  state?: Omit<Partial<NavState>, 'tab'> & { tab?: LegacyTab } | null,
): NavState {
  const legacySharingTab = state?.tab === 'sharing';

  return {
    tab: TABS.some((tab) => tab.id === state?.tab) ? (state?.tab as Tab) : legacySharingTab ? 'system' : DEFAULT_NAV_STATE.tab,
    impSubTab: IMPAIRMENT_SUBTABS.some((tab) => tab.id === state?.impSubTab)
      ? (state?.impSubTab as ImpairmentSubTab)
      : DEFAULT_NAV_STATE.impSubTab,
    sysSubTab: SYSTEM_SUBTABS.some((tab) => tab.id === state?.sysSubTab)
      ? (state?.sysSubTab as SystemSubTab)
      : legacySharingTab
        ? 'remote'
        : DEFAULT_NAV_STATE.sysSubTab,
    analyzingCaptureId: typeof state?.analyzingCaptureId === 'string' ? state.analyzingCaptureId : null,
    selectedStreamId: typeof state?.selectedStreamId === 'string' ? state.selectedStreamId : null,
  };
}

export function getVisibleTabs(isEnabled: FeatureFlagChecker): DashboardTabOption<Tab>[] {
  return TABS.filter((tab) => {
    if (tab.id === 'sessions' && !isEnabled('sessions')) return false;
    if (tab.id === 'streams' && !isEnabled('streams')) return false;
    if (tab.id === 'adb' && !isEnabled('adb')) return false;
    if (tab.id === 'captures' && !isEnabled('captures')) return false;
    return true;
  });
}

export function getVisibleImpairmentSubTabs(isEnabled: FeatureFlagChecker): DashboardTabOption<ImpairmentSubTab>[] {
  return IMPAIRMENT_SUBTABS.filter((tab) => {
    if (tab.id === 'wifi' && !isEnabled('impairments_wifi')) return false;
    if (tab.id === 'dns' && !isEnabled('dns_simulation')) return false;
    if (tab.id === 'teleport' && !isEnabled('teleport')) return false;
    return true;
  });
}

export function getVisibleSystemSubTabs(remoteAccessEnabled: boolean): DashboardTabOption<SystemSubTab>[] {
  return SYSTEM_SUBTABS.filter((tab) => {
    if (tab.id === 'remote' && !remoteAccessEnabled) return false;
    return true;
  });
}

export function getVisibleSelection<T extends string>(
  current: T,
  options: DashboardTabOption<T>[],
  fallback: T,
): T {
  if (options.some((option) => option.id === current)) {
    return current;
  }

  return options[0]?.id ?? fallback;
}
