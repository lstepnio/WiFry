import { useCallback, useEffect, useRef, useState } from 'react';
import type { ImpairmentSubTab, NavState, SystemSubTab, Tab } from './config';
import { DEFAULT_NAV_STATE, normalizeNavState } from './config';

interface UseDashboardNavigationOptions {
  collaborationEnabled: boolean;
}

export function useDashboardNavigation({ collaborationEnabled }: UseDashboardNavigationOptions) {
  const [tab, setTab] = useState<Tab>(DEFAULT_NAV_STATE.tab);
  const [impSubTab, setImpSubTab] = useState<ImpairmentSubTab>(DEFAULT_NAV_STATE.impSubTab);
  const [sysSubTab, setSysSubTab] = useState<SystemSubTab>(DEFAULT_NAV_STATE.sysSubTab);
  const [analyzingCaptureId, setAnalyzingCaptureId] = useState<string | null>(DEFAULT_NAV_STATE.analyzingCaptureId);
  const [selectedStreamId, setSelectedStreamId] = useState<string | null>(DEFAULT_NAV_STATE.selectedStreamId);
  const wsRef = useRef<WebSocket | null>(null);
  const isRemoteUpdate = useRef(false);
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

  const handleTabChange = useCallback((nextTab: Tab) => {
    setTab(nextTab);
    if (nextTab !== 'captures') setAnalyzingCaptureId(null);
    if (nextTab !== 'streams') setSelectedStreamId(null);
    navStateRef.current = {
      ...navStateRef.current,
      tab: nextTab,
      analyzingCaptureId: nextTab === 'captures' ? navStateRef.current.analyzingCaptureId : null,
      selectedStreamId: nextTab === 'streams' ? navStateRef.current.selectedStreamId : null,
    };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleImpairmentSubTabChange = useCallback((nextSubTab: ImpairmentSubTab) => {
    setImpSubTab(nextSubTab);
    navStateRef.current = { ...navStateRef.current, impSubTab: nextSubTab };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleSystemSubTabChange = useCallback((nextSubTab: SystemSubTab) => {
    setSysSubTab(nextSubTab);
    navStateRef.current = { ...navStateRef.current, sysSubTab: nextSubTab };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleAnalyze = useCallback((captureId: string | null) => {
    setAnalyzingCaptureId(captureId);
    navStateRef.current = { ...navStateRef.current, analyzingCaptureId: captureId };
    broadcastNavState();
  }, [broadcastNavState]);

  const handleStreamSelect = useCallback((streamId: string | null) => {
    setSelectedStreamId(streamId);
    navStateRef.current = { ...navStateRef.current, selectedStreamId: streamId };
    broadcastNavState();
  }, [broadcastNavState]);

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
          const message = JSON.parse(event.data);
          if (message.type === 'navigate' && message.state) {
            isRemoteUpdate.current = true;
            const nextState = normalizeNavState(message.state);
            setTab(nextState.tab);
            setImpSubTab(nextState.impSubTab);
            setSysSubTab(nextState.sysSubTab);
            setAnalyzingCaptureId(nextState.analyzingCaptureId);
            setSelectedStreamId(nextState.selectedStreamId);
            navStateRef.current = nextState;
          } else if (message.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
          }
        } catch {
          // Ignore malformed collaboration messages.
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (alive) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      alive = false;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [collaborationEnabled]);

  return {
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
  };
}
