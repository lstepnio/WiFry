import AdbPanel from '../AdbPanel';
import CaptureAnalysis from '../CaptureAnalysis';
import CaptureManager from '../CaptureManager';
import DnsPanel from '../DnsPanel';
import FeatureFlagsPanel from '../FeatureFlagsPanel';
import HwValidationPanel from '../HwValidationPanel';
import ImpairmentPanel from '../ImpairmentPanel';
import NetworkConfigPanel from '../NetworkConfigPanel';
import NetworkStatus from '../NetworkStatus';
import ProfileManager from '../ProfileManager';
import ProxySettings from '../ProxySettings';
import SessionPanel from '../SessionPanel';
import SettingsPanel from '../SettingsPanel';
import SharePanel from '../SharePanel';
import SpeedTest from '../SpeedTest';
import StreamDetail from '../StreamDetail';
import StreamMonitor from '../StreamMonitor';
import SystemInfo from '../SystemInfo';
import TeleportPanel from '../TeleportPanel';
import ExperimentalVideoStream from '../ExperimentalVideoStream'; // EXPERIMENTAL_VIDEO_CAPTURE
import StbAutomationPanel from '../StbAutomationPanel'; // STB_AUTOMATION
import VideoProbe from '../VideoProbe';
import WifiImpairmentPanel from '../WifiImpairmentPanel';
import WifiScanner from '../WifiScanner';
import { SubTabNav } from './DashboardNavigation';
import type { DashboardTabOption, ImpairmentSubTab, SystemSubTab, Tab } from './config';

interface DashboardPanelsProps {
  currentTab: Tab;
  currentImpairmentSubTab: ImpairmentSubTab;
  currentSystemSubTab: SystemSubTab;
  visibleImpairmentSubTabs: DashboardTabOption<ImpairmentSubTab>[];
  visibleSystemSubTabs: DashboardTabOption<SystemSubTab>[];
  remoteAccessEnabled: boolean;
  analyzingCaptureId: string | null;
  selectedStreamId: string | null;
  isEnabled: (flagName: string) => boolean;
  onImpairmentSubTabChange: (tab: ImpairmentSubTab) => void;
  onSystemSubTabChange: (tab: SystemSubTab) => void;
  onAnalyze: (captureId: string | null) => void;
  onStreamSelect: (streamId: string | null) => void;
}

export default function DashboardPanels({
  currentTab,
  currentImpairmentSubTab,
  currentSystemSubTab,
  visibleImpairmentSubTabs,
  visibleSystemSubTabs,
  remoteAccessEnabled,
  analyzingCaptureId,
  selectedStreamId,
  isEnabled,
  onImpairmentSubTabChange,
  onSystemSubTabChange,
  onAnalyze,
  onStreamSelect,
}: DashboardPanelsProps) {
  if (currentTab === 'sessions') {
    return <SessionPanel />;
  }

  if (currentTab === 'impairments') {
    return (
      <div>
        <SubTabNav
          tabs={visibleImpairmentSubTabs}
          active={currentImpairmentSubTab}
          onChange={onImpairmentSubTabChange}
        />
        {currentImpairmentSubTab === 'profiles' && isEnabled('impairments_profiles') && <ProfileManager />}
        {currentImpairmentSubTab === 'network' && isEnabled('impairments_network') && <ImpairmentPanel />}
        {currentImpairmentSubTab === 'wifi' && isEnabled('impairments_wifi') && <WifiImpairmentPanel />}
        {currentImpairmentSubTab === 'dns' && isEnabled('dns_simulation') && <DnsPanel />}
        {currentImpairmentSubTab === 'teleport' && isEnabled('teleport') && <TeleportPanel />}
      </div>
    );
  }

  if (currentTab === 'adb') {
    return isEnabled('adb') ? <AdbPanel /> : null;
  }

  if (currentTab === 'stb_automation') {
    return isEnabled('stb_automation') ? <StbAutomationPanel /> : null;
  }

  if (currentTab === 'captures') {
    return analyzingCaptureId ? (
      <CaptureAnalysis captureId={analyzingCaptureId} onBack={() => onAnalyze(null)} />
    ) : (
      <CaptureManager onAnalyze={onAnalyze} />
    );
  }

  if (currentTab === 'streams') {
    return selectedStreamId ? (
      <StreamDetail sessionId={selectedStreamId} onBack={() => onStreamSelect(null)} />
    ) : (
      <div className="space-y-6">
        <ProxySettings />
        <StreamMonitor onSelect={onStreamSelect} />
        <VideoProbe />
      </div>
    );
  }

  return (
    <div>
      <SubTabNav tabs={visibleSystemSubTabs} active={currentSystemSubTab} onChange={onSystemSubTabChange} />
      {currentSystemSubTab === 'overview' && (
        <div className="space-y-6">
          <SystemInfo />
          <NetworkStatus />
        </div>
      )}
      {currentSystemSubTab === 'network' && <NetworkConfigPanel />}
      {currentSystemSubTab === 'remote' && remoteAccessEnabled && <SharePanel />}
      {currentSystemSubTab === 'tools' && (
        <div className="space-y-6">
          <HwValidationPanel />
          <WifiScanner />
          <SpeedTest />
          {/* EXPERIMENTAL_VIDEO_CAPTURE — Only shown when flag is enabled */}
          {isEnabled('experimental_video_capture') && <ExperimentalVideoStream />}
        </div>
      )}
      {currentSystemSubTab === 'settings' && (
        <div className="space-y-6">
          <SettingsPanel />
          <FeatureFlagsPanel />
        </div>
      )}
    </div>
  );
}
