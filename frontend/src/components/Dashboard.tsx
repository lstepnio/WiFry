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
 * 6. System       — Settings, sharing, tools (sub-tabs)
 */

type Tab = 'sessions' | 'impairments' | 'adb' | 'captures' | 'streams' | 'sharing' | 'system';
type ImpairmentSubTab = 'profiles' | 'network' | 'wifi' | 'dns' | 'teleport';
type SystemSubTab = 'overview' | 'network' | 'tools' | 'settings';

const TABS: { id: Tab; label: string; desc: string }[] = [
  { id: 'sessions', label: 'Sessions', desc: 'Create and manage test sessions' },
  { id: 'impairments', label: 'Impairments', desc: 'Control network conditions' },
  { id: 'adb', label: 'ADB', desc: 'Android device control' },
  { id: 'captures', label: 'Captures', desc: 'Packet capture + AI analysis' },
  { id: 'streams', label: 'Streams', desc: 'HLS/DASH stream monitoring' },
  { id: 'sharing', label: 'Sharing', desc: 'Tunnel sharing, file uploads, collaboration' },
  { id: 'system', label: 'System', desc: 'Settings and tools' },
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
  { id: 'tools', label: 'Tools' },
  { id: 'settings', label: 'App Settings' },
];

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
  const ignoreNextNavigate = useRef(false);

  // Collaboration WebSocket for navigation mirroring (auto-reconnect)
  useEffect(() => {
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
          if (msg.type === 'navigate' && msg.tab) {
            ignoreNextNavigate.current = true;
            setTab(msg.tab as Tab);
            if (msg.subTab) {
              if (msg.tab === 'impairments') setImpSubTab(msg.subTab);
              if (msg.tab === 'system') setSysSubTab(msg.subTab);
            }
          } else if (msg.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (alive) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => { ws.close(); };
    }

    connect();

    return () => {
      alive = false;
      clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
      wsRef.current = null;
    };
  }, []);

  const sendNavigate = useCallback((mainTab: string, subTab?: string) => {
    if (ignoreNextNavigate.current) {
      ignoreNextNavigate.current = false;
      return;
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'navigate', tab: mainTab, subTab }));
    }
  }, []);

  // Send navigation messages when user changes tab
  const handleTabChange = useCallback((newTab: Tab) => {
    setTab(newTab);
    if (newTab !== 'captures') setAnalyzingCaptureId(null);
    if (newTab !== 'streams') setSelectedStreamId(null);
    sendNavigate(newTab);
  }, [sendNavigate]);

  const handleImpSubTabChange = useCallback((sub: ImpairmentSubTab) => {
    setImpSubTab(sub);
    sendNavigate('impairments', sub);
  }, [sendNavigate]);

  const handleSysSubTabChange = useCallback((sub: SystemSubTab) => {
    setSysSubTab(sub);
    sendNavigate('system', sub);
  }, [sendNavigate]);

  // Filter tabs based on feature flags
  const visibleTabs = TABS.filter(t => {
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
  const visibleSysSubTabs = SYS_SUBTABS;

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
                  tab === t.id
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
        {tab === 'sessions' && <SessionPanel />}

        {/* Impairments — sub-tabbed, filtered by feature flags */}
        {tab === 'impairments' && (
          <div>
            <SubTabNav tabs={visibleImpSubTabs} active={impSubTab} onChange={handleImpSubTabChange} />
            {impSubTab === 'profiles' && isEnabled('impairments_profiles') && <ProfileManager />}
            {impSubTab === 'network' && isEnabled('impairments_network') && <ImpairmentPanel />}
            {impSubTab === 'wifi' && isEnabled('impairments_wifi') && <WifiImpairmentPanel />}
            {impSubTab === 'dns' && isEnabled('dns_simulation') && <DnsPanel />}
            {impSubTab === 'teleport' && isEnabled('teleport') && <TeleportPanel />}
          </div>
        )}

        {/* ADB */}
        {tab === 'adb' && isEnabled('adb') && <AdbPanel />}

        {/* Captures */}
        {tab === 'captures' && (
          analyzingCaptureId ? (
            <CaptureAnalysis
              captureId={analyzingCaptureId}
              onBack={() => setAnalyzingCaptureId(null)}
            />
          ) : (
            <CaptureManager
              onAnalyze={(id) => setAnalyzingCaptureId(id)}
            />
          )
        )}

        {/* Streams */}
        {tab === 'streams' && (
          selectedStreamId ? (
            <StreamDetail
              sessionId={selectedStreamId}
              onBack={() => setSelectedStreamId(null)}
            />
          ) : (
            <div className="space-y-6">
              <ProxySettings />
              <StreamMonitor onSelect={(id) => setSelectedStreamId(id)} />
              <VideoProbe />
            </div>
          )
        )}

        {/* Sharing */}
        {tab === 'sharing' && <SharePanel />}

        {/* System — sub-tabbed, filtered by feature flags */}
        {tab === 'system' && (
          <div>
            <SubTabNav tabs={visibleSysSubTabs} active={sysSubTab} onChange={handleSysSubTabChange} />
            {sysSubTab === 'overview' && (
              <div className="space-y-6">
                <SystemInfo />
                <NetworkStatus />
              </div>
            )}
            {sysSubTab === 'network' && <NetworkConfigPanel />}
            {sysSubTab === 'tools' && (
              <div className="space-y-6">
                <HwValidationPanel />
                <WifiScanner />
                <SpeedTest />
              </div>
            )}
            {sysSubTab === 'settings' && (
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
