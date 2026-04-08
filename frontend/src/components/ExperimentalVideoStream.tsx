/**
 * EXPERIMENTAL_VIDEO_CAPTURE — Live HDMI video stream with AI frame analysis.
 *
 * Shows device status, start/stop controls, MJPEG feed, and a one-shot
 * "Analyze Frame" button that sends the current frame to AI vision to
 * identify STB screen type, focused element, and navigation state.
 *
 * Only rendered when the 'experimental_video_capture' feature flag is enabled.
 * Removal: delete this file and its import in DashboardPanels.tsx.
 */

import { useCallback, useEffect, useState } from 'react';
import { analyzeVideoFrame, getVideoStatus, startVideoStream, stopVideoStream } from '../api/client';
import type { FrameAnalysisResult } from '../types';

interface VideoState {
  streaming: boolean;
  clients: number;
  device: Record<string, unknown>;
}

const SCREEN_TYPE_COLORS: Record<string, string> = {
  home: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  settings: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
  app_launcher: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300',
  content_details: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-300',
  player: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  search: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-300',
  menu: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
  error: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
  loading: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
  unknown: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
};

const CONFIDENCE_COLORS: Record<string, string> = {
  high: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  medium: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  low: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

export default function ExperimentalVideoStream() {
  const [state, setState] = useState<VideoState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<FrameAnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

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

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const result = await analyzeVideoFrame();
      setAnalysisResult(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to analyze frame');
    } finally {
      setAnalyzing(false);
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
          onClick={handleAnalyze}
          disabled={!streaming || analyzing}
          className="rounded bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {analyzing ? 'Analyzing...' : '🔍 Analyze Frame'}
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

      {!streaming && !analysisResult && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Click &quot;Start Stream&quot; to begin live HDMI video capture. Requires a UVC capture device (e.g. Elgato Cam Link 4K).
        </p>
      )}

      {/* EXPERIMENTAL_VIDEO_CAPTURE — Analysis Results */}
      {analysisResult && <AnalysisResultPanel result={analysisResult} />}
    </div>
  );
}

// EXPERIMENTAL_VIDEO_CAPTURE — Analysis result display component
function AnalysisResultPanel({ result }: { result: FrameAnalysisResult }) {
  if (result.error) {
    return (
      <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-900/30">
        <h4 className="mb-1 text-xs font-medium text-red-700 dark:text-red-300">Analysis Error</h4>
        <p className="text-xs text-red-600 dark:text-red-400">{result.error}</p>
        <AnalysisMetadata result={result} />
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {/* Screen Type + Title */}
      <div className="rounded border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-2 flex items-center gap-2">
          <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400">Screen</h4>
          <span className={`rounded px-2 py-0.5 text-[10px] font-semibold ${SCREEN_TYPE_COLORS[result.screen_type] || SCREEN_TYPE_COLORS.unknown}`}>
            {result.screen_type}
          </span>
          {result.screen_title && (
            <span className="text-sm font-medium text-gray-900 dark:text-white">{result.screen_title}</span>
          )}
        </div>

        {/* Navigation Path */}
        {result.navigation_path && result.navigation_path.length > 0 && (
          <div className="mb-2 flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
            <span className="font-medium">Path:</span>
            {result.navigation_path.map((step, i) => (
              <span key={i} className="flex items-center gap-1">
                {i > 0 && <span className="text-gray-400">›</span>}
                <span className="text-gray-700 dark:text-gray-300">{step}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Focused Element */}
      {result.focused_element && (
        <div className="rounded border border-purple-200 bg-purple-50 p-3 dark:border-purple-800 dark:bg-purple-900/20">
          <div className="mb-1 flex items-center gap-2">
            <h4 className="text-xs font-medium text-purple-700 dark:text-purple-300">Focused Element</h4>
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${CONFIDENCE_COLORS[result.focused_element.confidence] || ''}`}>
              {result.focused_element.confidence}
            </span>
          </div>
          <div className="mb-1 text-sm font-semibold text-purple-900 dark:text-purple-100">
            &ldquo;{result.focused_element.label}&rdquo;
          </div>
          <div className="flex gap-3 text-[11px] text-purple-600 dark:text-purple-400">
            <span>Type: {result.focused_element.element_type}</span>
            <span>Position: {result.focused_element.position}</span>
          </div>
        </div>
      )}

      {/* Visible Text Summary */}
      {result.visible_text_summary && (
        <div className="rounded border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
          <h4 className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Visible Text</h4>
          <p className="text-xs text-gray-700 dark:text-gray-300">{result.visible_text_summary}</p>
        </div>
      )}

      {/* Raw Description */}
      {result.raw_description && (
        <div className="rounded border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
          <h4 className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">AI Description</h4>
          <p className="text-xs text-gray-700 dark:text-gray-300">{result.raw_description}</p>
        </div>
      )}

      <AnalysisMetadata result={result} />
    </div>
  );
}

function AnalysisMetadata({ result }: { result: FrameAnalysisResult }) {
  return (
    <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-gray-500 dark:text-gray-500">
      {result.provider && <span>Provider: {result.provider}</span>}
      {result.model && <span>Model: {result.model}</span>}
      {result.tokens_used > 0 && <span>Tokens: {result.tokens_used.toLocaleString()}</span>}
      {result.analyzed_at && <span>At: {new Date(result.analyzed_at).toLocaleString()}</span>}
    </div>
  );
}
