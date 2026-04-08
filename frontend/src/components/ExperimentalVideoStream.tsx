/**
 * EXPERIMENTAL_VIDEO_CAPTURE — Minimal dev panel for live HDMI video stream.
 *
 * Shows device status, start/stop controls, and an MJPEG <img> feed.
 * Only rendered when the 'experimental_video_capture' feature flag is enabled.
 *
 * Removal: delete this file and its import in DashboardPanels.tsx.
 */

import { useCallback, useEffect, useState } from 'react';
import { getVideoStatus, startVideoStream, stopVideoStream } from '../api/client';

interface VideoState {
  streaming: boolean;
  clients: number;
  device: Record<string, unknown>;
}

export default function ExperimentalVideoStream() {
  const [state, setState] = useState<VideoState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await getVideoStatus();
      setState(s);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch video status');
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleStart = async () => {
    setLoading(true);
    setError(null);
    try {
      await startVideoStream();
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start stream');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    setError(null);
    try {
      await stopVideoStream();
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to stop stream');
    } finally {
      setLoading(false);
    }
  };

  const deviceState = (state?.device?.state as string) || 'unknown';
  const streaming = state?.streaming ?? false;

  return (
    <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-4 dark:border-yellow-700 dark:bg-yellow-900/20">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-lg">🧪</span>
        <h3 className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
          Live Video Stream
        </h3>
        <span className="rounded bg-yellow-200 px-1.5 py-0.5 text-[10px] font-medium text-yellow-700 dark:bg-yellow-800 dark:text-yellow-300">
          EXPERIMENTAL
        </span>
      </div>

      {error && (
        <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-900/30 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="mb-3 flex items-center gap-3 text-xs text-gray-600 dark:text-gray-400">
        <span>
          Device:{' '}
          <span className={deviceState === 'streaming' ? 'font-medium text-green-600 dark:text-green-400' : ''}>
            {deviceState}
          </span>
        </span>
        {state?.device?.path != null && <span className="font-mono">{String(state.device.path)}</span>}
        {streaming && <span>Clients: {state?.clients ?? 0}</span>}
      </div>

      <div className="mb-3 flex gap-2">
        <button
          onClick={handleStart}
          disabled={loading || streaming}
          className="rounded bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {loading && !streaming ? 'Starting...' : 'Start Stream'}
        </button>
        <button
          onClick={handleStop}
          disabled={loading || !streaming}
          className="rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          Stop Stream
        </button>
        <button
          onClick={refresh}
          className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
        >
          Refresh
        </button>
      </div>

      {streaming && (
        <div className="overflow-hidden rounded border border-gray-200 bg-black dark:border-gray-700">
          <img
            src="/api/v1/experimental/video/stream"
            alt="Live HDMI video stream"
            className="w-full"
            style={{ maxHeight: '480px', objectFit: 'contain' }}
          />
        </div>
      )}

      {!streaming && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Click &quot;Start Stream&quot; to begin live HDMI video capture. Requires a UVC capture device (e.g. Elgato Cam Link 4K).
        </p>
      )}
    </div>
  );
}
