/**
 * Persistent status bar showing at-a-glance state across all tabs.
 * Always visible below the header.
 */
import { useCallback } from 'react';
import { useApi } from '../hooks/useApi';

export default function StatusBar() {
  const sessionFetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/sessions/active'); return r.ok ? r.json() : null; } catch { return null; }
  }, []);
  const { data: session } = useApi(sessionFetcher, 5000);

  const impFetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/impairments'); return r.ok ? r.json() : []; } catch { return []; }
  }, []);
  const { data: impairments } = useApi(impFetcher, 5000);

  const streamFetcher = useCallback(async () => {
    try { const r = await fetch('/api/v1/streams'); return r.ok ? r.json() : []; } catch { return []; }
  }, []);
  const { data: streams } = useApi(streamFetcher, 5000);

  const activeImps = (impairments as any[] ?? []).filter((i: any) => i.active);
  const activeStreams = (streams as any[] ?? []).filter((s: any) => s.active);
  const activeSession = (session as any)?.active_session_id;

  const hasAnything = activeSession || activeImps.length > 0 || activeStreams.length > 0;

  if (!hasAnything) return null;

  return (
    <div className="border-b border-gray-800 bg-gray-900/80 px-6 py-1.5">
      <div className="mx-auto flex max-w-6xl items-center gap-4 text-xs">
        {activeSession && (
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" />
            <span className="text-gray-400">Session:</span>
            <span className="font-medium text-green-400">{(session as any)?.session_name || activeSession}</span>
          </div>
        )}
        {activeImps.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-orange-500" />
            <span className="text-gray-400">Impairments active on</span>
            <span className="font-medium text-orange-400">{activeImps.map((i: any) => i.interface).join(', ')}</span>
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
