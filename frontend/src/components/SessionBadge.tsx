/**
 * Small badge showing which test session artifacts will be linked to.
 * Shows green "Recording to: Session Name" when active, gray hint when not.
 */
import { useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import type { ActiveSessionInfo } from '../types';

export default function SessionBadge() {
  const fetcher = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/sessions/active');
      return res.ok ? res.json() : null;
    } catch { return null; }
  }, []);
  const { data: session } = useApi<ActiveSessionInfo | null>(fetcher, 5000);

  if (session?.active_session_id) {
    return (
      <div className="flex items-center gap-1.5 rounded bg-green-900/30 px-2 py-0.5 text-xs">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
        <span className="text-green-400">Recording to: {session.session_name}</span>
      </div>
    );
  }

  return (
    <div className="rounded bg-gray-800/50 px-2 py-0.5 text-xs text-gray-600">
      No active session — results won't be linked
    </div>
  );
}
