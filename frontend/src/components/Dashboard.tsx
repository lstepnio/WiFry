import StatusBar from './StatusBar';
import DashboardPanels from './dashboard/DashboardPanels';
import { DashboardHeader } from './dashboard/DashboardNavigation';
import {
  DEFAULT_NAV_STATE,
  getVisibleImpairmentSubTabs,
  getVisibleSelection,
  getVisibleSystemSubTabs,
  getVisibleTabs,
} from './dashboard/config';
import { useDashboardNavigation } from './dashboard/useDashboardNavigation';
import { useFeatureFlags } from '../hooks/useFeatureFlags';

/*
 * 6 main tabs (fits nav without overflow):
 * 1. Sessions     — Start here
 * 2. Impairments  — Main activity (sub-tabs: Profiles, Network, WiFi, DNS, Teleport)
 * 3. ADB          — Device control
 * 4. Captures     — Packet capture + AI
 * 5. Streams      — HLS/DASH monitoring
 * 6. System       — Setup, remote access, and admin tools (sub-tabs)
 */

export default function Dashboard() {
  const { isEnabled } = useFeatureFlags();
  const collaborationEnabled = isEnabled('collaboration');
  const remoteAccessEnabled = isEnabled('sharing_tunnel') || collaborationEnabled;

  const {
    tab,
    impSubTab,
    sysSubTab,
    analyzingCaptureId,
    selectedStreamId,
    handleTabChange,
    handleImpairmentSubTabChange,
    handleSystemSubTabChange,
    handleAnalyze,
    handleStreamSelect,
  } = useDashboardNavigation({ collaborationEnabled });

  const visibleTabs = getVisibleTabs(isEnabled);
  const visibleImpairmentSubTabs = getVisibleImpairmentSubTabs(isEnabled);
  const visibleSystemSubTabs = getVisibleSystemSubTabs(remoteAccessEnabled);

  const currentTab = getVisibleSelection(tab, visibleTabs, 'system');
  const currentImpairmentSubTab = getVisibleSelection(
    impSubTab,
    visibleImpairmentSubTabs,
    DEFAULT_NAV_STATE.impSubTab,
  );
  const currentSystemSubTab = getVisibleSelection(
    sysSubTab,
    visibleSystemSubTabs,
    DEFAULT_NAV_STATE.sysSubTab,
  );

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <DashboardHeader tabs={visibleTabs} currentTab={currentTab} onTabChange={handleTabChange} />
      <StatusBar />

      <main className="mx-auto max-w-6xl p-6">
        <DashboardPanels
          currentTab={currentTab}
          currentImpairmentSubTab={currentImpairmentSubTab}
          currentSystemSubTab={currentSystemSubTab}
          visibleImpairmentSubTabs={visibleImpairmentSubTabs}
          visibleSystemSubTabs={visibleSystemSubTabs}
          remoteAccessEnabled={remoteAccessEnabled}
          analyzingCaptureId={analyzingCaptureId}
          selectedStreamId={selectedStreamId}
          isEnabled={isEnabled}
          onImpairmentSubTabChange={handleImpairmentSubTabChange}
          onSystemSubTabChange={handleSystemSubTabChange}
          onAnalyze={handleAnalyze}
          onStreamSelect={handleStreamSelect}
        />
      </main>
    </div>
  );
}
