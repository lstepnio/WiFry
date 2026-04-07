/**
 * Persistent status bar showing at-a-glance state across all tabs.
 * Always visible below the header.
 */
import { useCallback } from 'react';
import { getActiveSession, getImpairments, getStreams } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { ActiveSessionInfo, InterfaceImpairmentState, StreamSessionSummary } from '../types';

export default function StatusBar() {
  const sessionFetcher = useCallback(async () => {
    try {
      return await getActiveSession();
    } catch {
      return null;
    }
  }, []);
  const { data: session } = useApi<ActiveSessionInfo | null>(sessionFetcher, 5000);

  const impairmentFetcher = useCallback(async () => {
    try {
      return await getImpairments();
    } catch {
      return [];
    }
  }, []);
  const { data: impairments } = useApi<InterfaceImpairmentState[]>(impairmentFetcher, 5000);

  const streamFetcher = useCallback(async () => {
    try {
      return await getStreams();
    } catch {
      return [];
    }
  }, []);
  const { data: streams } = useApi<StreamSessionSummary[]>(streamFetcher, 5000);

  const activeImpairments = (impairments ?? []).filter((impairment) => impairment.active);
  const activeStreams = (streams ?? []).filter((stream) => stream.active);
  const activeSession = session?.active_session_id;

  const hasAnything = activeSession || activeImpairments.length > 0 || activeStreams.length > 0;

  if (!hasAnything) return null;

  return (
    <div className="border-b border-gray-800 bg-gray-900/80 px-6 py-1.5">
      <div className="mx-auto flex max-w-6xl items-center gap-4 text-xs">
        {activeSession && (
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" />
            <span className="text-gray-400">Session:</span>
            <span className="font-medium text-green-400">{session?.session_name || activeSession}</span>
          </div>
        )}
        {activeImpairments.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-orange-500" />
            <span className="text-gray-400">Impairments active on</span>
            <span className="font-medium text-orange-400">{activeImpairments.map((impairment) => impairment.interface).join(', ')}</span>
          </div>
        )}
        {activeStreams.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-purple-500" />
            <span className="font-medium text-purple-400">{activeStreams.length} stream{activeStreams.length > 1 ? 's' : ''}</span>
          </div>
        )}
      </div>
    </div>
  );
}
