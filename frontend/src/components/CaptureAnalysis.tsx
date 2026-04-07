import { useCallback, useEffect, useState } from 'react';
import type { AnalysisResult, SystemSettings } from '../types';
import * as api from '../api/client';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'border-red-500 bg-red-50 dark:bg-red-950',
  high: 'border-orange-500 bg-orange-50 dark:bg-orange-950',
  medium: 'border-yellow-500 bg-yellow-50 dark:bg-yellow-950',
  low: 'border-green-500 bg-green-50 dark:bg-green-950',
};

const SEVERITY_BADGE: Record<string, string> = {
  critical: 'bg-red-600 text-white',
  high: 'bg-orange-500 text-white',
  medium: 'bg-yellow-500 text-white',
  low: 'bg-green-600 text-white',
};

export default function CaptureAnalysis({
  captureId,
  onBack,
}: {
  captureId: string;
  onBack: () => void;
}) {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    fetch('/api/v1/system/settings').then(r => r.json()).then((s: SystemSettings) => {
      setAiConfigured(s.anthropic_api_key_set || s.openai_api_key_set);
    }).catch(() => setAiConfigured(false));
  }, []);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.analyzeCapture(captureId);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [captureId]);

  const loadExisting = useCallback(async () => {
    try {
      const r = await api.getAnalysis(captureId);
      setResult(r);
    } catch {
      // No existing analysis — that's fine
    }
  }, [captureId]);

  // Load existing analysis on mount
  useEffect(() => {
    loadExisting();
  }, [loadExisting]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            &larr; Back
          </button>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            AI Analysis — {captureId}
          </h2>
        </div>
        <button
          onClick={runAnalysis}
          disabled={loading || aiConfigured === false}
          className="rounded-lg bg-purple-600 px-5 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          title={aiConfigured === false ? 'Configure an AI API key in System > App Settings' : ''}
        >
          {loading ? 'Analyzing...' : result ? 'Re-analyze' : 'Run Analysis'}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-700 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-12 text-center text-gray-500">
          <div className="mb-2 text-2xl">Analyzing capture data...</div>
          <p className="text-sm">Extracting statistics and sending to AI for analysis</p>
        </div>
      )}

      {result && !loading && (
        <>
          {/* Summary */}
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">Summary</h3>
            <p className="text-gray-900 dark:text-white">{result.summary}</p>
            <div className="mt-3 flex gap-4 text-xs text-gray-500">
              <span>Provider: {result.provider}</span>
              <span>Model: {result.model}</span>
              {result.tokens_used > 0 && <span>Tokens: {result.tokens_used}</span>}
              {result.analyzed_at && <span>At: {new Date(result.analyzed_at).toLocaleString()}</span>}
            </div>
          </div>

          {/* Issues */}
          {result.issues.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">
                Issues ({result.issues.length})
              </h3>
              {result.issues.map((issue, i) => (
                <div
                  key={i}
                  className={`rounded-lg border-l-4 p-4 ${SEVERITY_COLORS[issue.severity] || 'border-gray-300 bg-gray-50 dark:bg-gray-800'}`}
                >
                  <div className="mb-2 flex items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${SEVERITY_BADGE[issue.severity] || 'bg-gray-500 text-white'}`}>
                      {issue.severity}
                    </span>
                    <span className="rounded bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                      {issue.category}
                    </span>
                  </div>
                  <p className="mb-2 text-sm text-gray-800 dark:text-gray-200">
                    {issue.description}
                  </p>
                  {issue.affected_flows.length > 0 && (
                    <div className="mb-2 text-xs text-gray-500">
                      <span className="font-medium">Flows: </span>
                      {issue.affected_flows.map((f, j) => (
                        <span key={j} className="mr-2 font-mono">{f}</span>
                      ))}
                    </div>
                  )}
                  {issue.recommendation && (
                    <div className="text-sm text-gray-600 dark:text-gray-400">
                      <span className="font-medium">Recommendation: </span>
                      {issue.recommendation}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Statistics */}
          {Object.keys(result.statistics).length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
              <h3 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">Statistics</h3>
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                {Object.entries(result.statistics).map(([key, value]) => (
                  <div key={key}>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {key.replace(/_/g, ' ')}
                    </div>
                    <div className="font-medium text-gray-900 dark:text-white">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {!result && !loading && !error && aiConfigured === false && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-6 text-center">
          <p className="mb-2 text-lg font-medium text-yellow-400">AI Analysis Not Configured</p>
          <p className="mb-4 text-sm text-gray-400">
            To analyze packet captures with AI, configure an API key in settings.
          </p>
          <p className="text-xs text-gray-500">
            Go to <span className="font-medium text-white">System</span> &rarr; <span className="font-medium text-white">App Settings</span> and enter your Anthropic or OpenAI API key.
          </p>
        </div>
      )}

      {!result && !loading && !error && aiConfigured !== false && (
        <div className="py-12 text-center text-gray-500">
          <p className="mb-2 text-lg">No analysis yet</p>
          <p className="text-sm">Click "Run Analysis" to analyze this capture with AI</p>
        </div>
      )}
    </div>
  );
}
