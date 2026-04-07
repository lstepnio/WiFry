import { useCallback, useEffect, useRef, useState } from 'react';
import ImpairmentPanel from './ImpairmentPanel';
import ProfileManager from './ProfileManager';
import NetworkStatus from './NetworkStatus';
import SystemInfo from './SystemInfo';
import CaptureManager from './CaptureManager';
import CaptureAnalysis from './CaptureAnalysis';
import StreamMonitor from './StreamMonitor';
import StreamDetail from './StreamDetail';
import ProxySettings from './ProxySettings';
import AdbPanel from './AdbPanel';
import WifiScanner from './WifiScanner';
import SpeedTest from './SpeedTest';
import WifiImpairmentPanel from './WifiImpairmentPanel';
import SettingsPanel from './SettingsPanel';
import SharePanel from './SharePanel';
import SessionPanel from './SessionPanel';
import NetworkConfigPanel from './NetworkConfigPanel';
import TeleportPanel from './TeleportPanel';
import StatusBar from './StatusBar';
import DnsPanel from './DnsPanel';
import { useFeatureFlags } from '../hooks/useFeatureFlags';
import FeatureFlagsPanel from './FeatureFlagsPanel';
import HwValidationPanel from './HwValidationPanel';
import VideoProbe from './VideoProbe';

/*
 * 6 main tabs (fits nav without overflow):
 * 1. Sessions     — Start here
 * 2. Impairments  — Main activity (sub-tabs: Profiles, Network, WiFi, DNS, Teleport)
 * 3. ADB          — Device control
 * 4. Captures     — Packet capture + AI
 * 5. Streams      — HLS/DASH monitoring
 * 6. System       — Setup, remote access, and admin tools (sub-tabs)
 */

type Tab = 'sessions' | 'impairments' | 'adb' | 'captures' | 'streams' | 'system';
type LegacyTab = Tab | 'sharing';
type ImpairmentSubTab = 'profiles' | 'network' | 'wifi' | 'dns' | 'teleport';
type SystemSubTab = 'overview' | 'network' | 'remote' | 'tools' | 'settings';
type NavState = {
  tab: Tab;
  impSubTab: ImpairmentSubTab;
  sysSubTab: SystemSubTab;
  analyzingCaptureId: string | null;
  selectedStreamId: string | null;
};

const TABS: { id: Tab; label: string; desc: string }[] = [
  { id: 'sessions', label: 'Sessions', desc: 'Primary workflow for test evidence and bundle sharing' },
  { id: 'impairments', label: 'Impairments', desc: 'Control network conditions' },
  { id: 'adb', label: 'ADB', desc: 'Android device control' },
  { id: 'captures', label: 'Captures', desc: 'Packet capture + AI analysis' },
  { id: 'streams', label: 'Streams', desc: 'HLS/DASH stream monitoring' },
  { id: 'system', label: 'System', desc: 'Network setup, remote access, and admin tools' },
];

const IMP_SUBTABS: { id: ImpairmentSubTab; label: string }[] = [
  { id: 'profiles', label: 'Profiles' },
  { id: 'network', label: 'Network' },
  { id: 'wifi', label: 'WiFi' },
  { id: 'dns', label: 'DNS' },
  { id: 'teleport', label: 'Teleport' },
];

const SYS_SUBTABS: { id: SystemSubTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'network', label: 'Network Config' },
  { id: 'remote', label: 'Remote Access' },
  { id: 'tools', label: 'Tools' },
  { id: 'settings', label: 'App Settings' },
];

const DEFAULT_NAV_STATE: NavState = {
  tab: 'sessions',
  impSubTab: 'profiles',
  sysSubTab: 'overview',
  analyzingCaptureId: null,
  selectedStreamId: null,
};

function normalizeNavState(state?: Omit<Partial<NavState>, 'tab'> & { tab?: LegacyTab } | null): NavState {
  const legacySharingTab = state?.tab === 'sharing';

  return {
    tab: TABS.some((tab) => tab.id === state?.tab) ? (state?.tab as Tab) : legacySharingTab ? 'system' : DEFAULT_NAV_STATE.tab,
    impSubTab: IMP_SUBTABS.some((tab) => tab.id === state?.impSubTab) ? (state?.impSubTab as ImpairmentSubTab) : DEFAULT_NAV_STATE.impSubTab,
    sysSubTab: SYS_SUBTABS.some((tab) => tab.id === state?.sysSubTab)
      ? (state?.sysSubTab as SystemSubTab)
      : legacySharingTab
        ? 'remote'
        : DEFAULT_NAV_STATE.sysSubTab,
    analyzingCaptureId: typeof state?.analyzingCaptureId === 'string' ? state.analyzingCaptureId : null,
    selectedStreamId: typeof state?.selectedStreamId === 'string' ? state.selectedStreamId : null,
  };
}

function SubTabNav<T extends string>({ tabs, active, onChange }: {
  tabs: { id: T; label: string }[];
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="mb-5 flex gap-1 border-b border-gray-800 pb-2">
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`rounded-t px-4 py-1.5 text-sm font-medium transition-colors ${
            active === t.id
              ? 'border-b-2 border-blue-500 text-blue-400'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>('sessions');
  const [impSubTab, setImpSubTab] = useState<ImpairmentSubTab>('profiles');
  const [sysSubTab, setSysSubTab] = useState<SystemSubTab>('overview');
  const [analyzingCaptureId, setAnalyzingCaptureId] = useState<string | null>(null);
  const [selectedStreamId, setSelectedStreamId] = useState<string | null>(null);
  const { isEnabled } = useFeatureFlags();
  const wsRef = useRef<WebSocket | null>(null);
  const isRemoteUpdate = useRef(false);
  const sessionsEnabled = isEnabled('sessions');
  const collaborationEnabled = isEnabled('collaboration');
  const remoteAccessEnabled = isEnabled('sharing_tunnel') || collaborationEnabled;

  // Broadcast full navigation state on any change
  // This captures ALL navigation: tabs, sub-tabs, sub-sub-tabs, panel selections
  const navStateRef = useRef<NavState>(DEFAULT_NAV_STATE);

  const broadcastNavState = useCallback(() => {
    if (isRemoteUpdate.current) {
      isRemoteUpdate.current = false;
      return;
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'navigate', state: navStateRef.current }));
    }
  }, []);

  // Wrap all state setters to auto-broadcast
  const handleTabChange = useCallback((newTab: Tab) => {
    setTab(newTab);
    if (newTab !== 'captures') setAnalyzingCaptureId(null);
    if (newTab !== 'streams') setSelectedStreamId(null);
    navStateRef.current = { ...navStateRef.current, tab: newTab, analyzingCaptureId: null, selectedStreamId: null };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleImpSubTabChange = useCallback((sub: ImpairmentSubTab) => {
    setImpSubTab(sub);
    navStateRef.current = { ...navStateRef.current, impSubTab: sub };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleSysSubTabChange = useCallback((sub: SystemSubTab) => {
    setSysSubTab(sub);
    navStateRef.current = { ...navStateRef.current, sysSubTab: sub };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleAnalyze = useCallback((id: string | null) => {
    setAnalyzingCaptureId(id);
    navStateRef.current = { ...navStateRef.current, analyzingCaptureId: id };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleStreamSelect = useCallback((id: string | null) => {
    setSelectedStreamId(id);
    navStateRef.current = { ...navStateRef.current, selectedStreamId: id };
    broadcastNavState();
  }, [broadcastNavState]);

  // Collaboration WebSocket (auto-reconnect)
  useEffect(() => {
    if (!collaborationEnabled) {
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }

    let alive = true;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      if (!alive) return;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/v1/collab/ws?name=`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'navigate' && msg.state) {
            // Apply full navigation state from remote user
            isRemoteUpdate.current = true;
            const s = normalizeNavState(msg.state);
            setTab(s.tab);
            setImpSubTab(s.impSubTab);
            setSysSubTab(s.sysSubTab);
            setAnalyzingCaptureId(s.analyzingCaptureId);
            setSelectedStreamId(s.selectedStreamId);
            navStateRef.current = s;
          } else if (msg.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (alive) reconnectTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => { ws.close(); };
    }

    connect();
    return () => { alive = false; clearTimeout(reconnectTimer); wsRef.current?.close(); wsRef.current = null; };
  }, [collaborationEnabled]);

  // Filter tabs based on feature flags
  const visibleTabs = TABS.filter(t => {
    if (t.id === 'sessions' && !sessionsEnabled) return false;
    if (t.id === 'streams' && !isEnabled('streams')) return false;
    if (t.id === 'adb' && !isEnabled('adb')) return false;
    if (t.id === 'captures' && !isEnabled('captures')) return false;
    return true;
  });

  // Filter impairment sub-tabs based on flags
  const visibleImpSubTabs = IMP_SUBTABS.filter(t => {
    if (t.id === 'wifi' && !isEnabled('impairments_wifi')) return false;
    if (t.id === 'dns' && !isEnabled('dns_simulation')) return false;
    if (t.id === 'teleport' && !isEnabled('teleport')) return false;
    return true;
  });

  // Filter system sub-tabs
  const visibleSysSubTabs = SYS_SUBTABS.filter(t => {
    if (t.id === 'remote' && !remoteAccessEnabled) return false;
    return true;
  });
  const currentTab = visibleTabs.some((visibleTab) => visibleTab.id === tab) ? tab : (visibleTabs[0]?.id ?? 'system');
  const currentImpSubTab = visibleImpSubTabs.some((visibleSubTab) => visibleSubTab.id === impSubTab) ? impSubTab : (visibleImpSubTabs[0]?.id ?? 'profiles');
  const currentSysSubTab = visibleSysSubTabs.some((visibleSubTab) => visibleSubTab.id === sysSubTab) ? sysSubTab : (visibleSysSubTabs[0]?.id ?? 'overview');

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white px-6 py-3 dark:border-gray-800 dark:bg-gray-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-lg font-bold text-white">
              W
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight text-gray-900 dark:text-white">WiFry</h1>
              <p className="text-[10px] text-gray-500 dark:text-gray-500">IP Video Edition</p>
            </div>
          </div>
          <nav className="flex gap-0.5">
            {visibleTabs.map((t) => (
              <button
                key={t.id}
                title={t.desc}
                onClick={() => handleTabChange(t.id)}
                className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${
                  currentTab === t.id
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Status bar */}
      <StatusBar />

      {/* Content */}
      <main className="mx-auto max-w-6xl p-6">

        {/* Sessions */}
        {currentTab === 'sessions' && <SessionPanel />}

        {/* Impairments — sub-tabbed, filtered by feature flags */}
        {currentTab === 'impairments' && (
          <div>
            <SubTabNav tabs={visibleImpSubTabs} active={currentImpSubTab} onChange={handleImpSubTabChange} />
            {currentImpSubTab === 'profiles' && isEnabled('impairments_profiles') && <ProfileManager />}
            {currentImpSubTab === 'network' && isEnabled('impairments_network') && <ImpairmentPanel />}
            {currentImpSubTab === 'wifi' && isEnabled('impairments_wifi') && <WifiImpairmentPanel />}
            {currentImpSubTab === 'dns' && isEnabled('dns_simulation') && <DnsPanel />}
            {currentImpSubTab === 'teleport' && isEnabled('teleport') && <TeleportPanel />}
          </div>
        )}

        {/* ADB */}
        {currentTab === 'adb' && isEnabled('adb') && <AdbPanel />}

        {/* Captures */}
        {currentTab === 'captures' && (
          analyzingCaptureId ? (
            <CaptureAnalysis
              captureId={analyzingCaptureId}
              onBack={() => handleAnalyze(null)}
            />
          ) : (
            <CaptureManager
              onAnalyze={(id) => handleAnalyze(id)}
            />
          )
        )}

        {/* Streams */}
        {currentTab === 'streams' && (
          selectedStreamId ? (
            <StreamDetail
              sessionId={selectedStreamId}
              onBack={() => handleStreamSelect(null)}
            />
          ) : (
            <div className="space-y-6">
              <ProxySettings />
              <StreamMonitor onSelect={(id) => handleStreamSelect(id)} />
              <VideoProbe />
            </div>
          )
        )}

        {/* System — sub-tabbed, filtered by feature flags */}
        {currentTab === 'system' && (
          <div>
            <SubTabNav tabs={visibleSysSubTabs} active={currentSysSubTab} onChange={handleSysSubTabChange} />
            {currentSysSubTab === 'overview' && (
              <div className="space-y-6">
                <SystemInfo />
                <NetworkStatus />
              </div>
            )}
            {currentSysSubTab === 'network' && <NetworkConfigPanel />}
            {currentSysSubTab === 'remote' && remoteAccessEnabled && <SharePanel />}
            {currentSysSubTab === 'tools' && (
              <div className="space-y-6">
                <HwValidationPanel />
                <WifiScanner />
                <SpeedTest />
              </div>
            )}
            {currentSysSubTab === 'settings' && (
              <div className="space-y-6">
                <SettingsPanel />
                <FeatureFlagsPanel />
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
