/**
 * Video Quality Probe — analyze media segments with ffprobe.
 * Shows codec info, bitrate, resolution, keyframe intervals.
 */

import { useState } from 'react';

interface StreamInfo {
  index: number;
  codec_type: string;
  codec_name: string;
  profile: string;
  level: string;
  width: number;
  height: number;
  frame_rate: number;
  bit_rate: number;
  sample_rate: number;
  channels: number;
}

interface SegmentAnalysis {
  path: string;
  file_size_bytes: number;
  duration_secs: number;
  actual_bitrate_bps: number;
  format_name: string;
  streams: StreamInfo[];
  keyframe_count: number;
  keyframe_interval_secs: number;
  errors: string[];
  warnings: string[];
}

interface ProbeResult {
  segments_analyzed: number;
  total_duration_secs: number;
  avg_bitrate_bps: number;
  max_bitrate_bps: number;
  min_bitrate_bps: number;
  video_codec: string;
  video_resolution: string;
  video_profile: string;
  avg_keyframe_interval_secs: number;
  audio_codec: string;
  audio_channels: number;
  audio_sample_rate: number;
  total_errors: number;
  total_warnings: number;
  segments: SegmentAnalysis[];
}

function formatBitrate(bps: number): string {
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`;
  if (bps >= 1_000) return `${(bps / 1_000).toFixed(0)} kbps`;
  return `${bps} bps`;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(0)} KB`;
  return `${bytes} B`;
}

function StatBox({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-lg font-semibold text-white">{value}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

export default function VideoProbe() {
  const [paths, setPaths] = useState('');
  const [probing, setProbing] = useState(false);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [singleResult, setSingleResult] = useState<SegmentAnalysis | null>(null);
  const [error, setError] = useState('');
  const [segmentDir, setSegmentDir] = useState('/var/lib/wifry/segments');
  const [discoveredFiles, setDiscoveredFiles] = useState<string[]>([]);
  const [mode, setMode] = useState<'url' | 'files'>('url');
  const [streamUrl, setStreamUrl] = useState('');
  const [maxSegments, setMaxSegments] = useState(5);
  const [manifestInfo, setManifestInfo] = useState<Record<string, unknown> | null>(null);

  const probeUrl = async () => {
    if (!streamUrl.trim()) { setError('Enter a URL'); return; }
    setProbing(true);
    setError('');
    setResult(null);
    setSingleResult(null);
    setManifestInfo(null);
    try {
      const res = await fetch('/api/v1/probe/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: streamUrl.trim(), max_segments: maxSegments }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setManifestInfo(data.manifest || null);
      setResult(data as ProbeResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Probe failed');
    } finally {
      setProbing(false);
    }
  };

  const discoverSegments = async () => {
    setError('');
    try {
      const res = await fetch('/api/v1/remote/exec', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: `find ${segmentDir} -type f \\( -name "*.ts" -o -name "*.m4s" -o -name "*.mp4" -o -name "*.m4v" -o -name "*.m4a" \\) | head -50 | sort` }),
      });
      const data = await res.json();
      if (data.stdout) {
        const files = data.stdout.split('\n').filter((f: string) => f.trim());
        setDiscoveredFiles(files);
        setPaths(files.join('\n'));
      } else {
        setDiscoveredFiles([]);
        setError('No media segments found in ' + segmentDir);
      }
    } catch {
      setError('Failed to discover segments');
    }
  };

  const probeSingle = async (path: string) => {
    setProbing(true);
    setError('');
    setSingleResult(null);
    setResult(null);
    try {
      const res = await fetch(`/api/v1/probe/segment?path=${encodeURIComponent(path)}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SegmentAnalysis = await res.json();
      setSingleResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Probe failed');
    } finally {
      setProbing(false);
    }
  };

  const probeMultiple = async () => {
    const pathList = paths.split('\n').map(p => p.trim()).filter(p => p);
    if (pathList.length === 0) {
      setError('Enter at least one file path');
      return;
    }

    setProbing(true);
    setError('');
    setResult(null);
    setSingleResult(null);
    try {
      const res = await fetch('/api/v1/probe/segments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pathList),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ProbeResult = await res.json();
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Probe failed');
    } finally {
      setProbing(false);
    }
  };

  const activeResult = result || (singleResult ? {
    segments_analyzed: 1,
    total_duration_secs: singleResult.duration_secs,
    avg_bitrate_bps: singleResult.actual_bitrate_bps,
    max_bitrate_bps: singleResult.actual_bitrate_bps,
    min_bitrate_bps: singleResult.actual_bitrate_bps,
    video_codec: singleResult.streams.find(s => s.codec_type === 'video')?.codec_name || '',
    video_resolution: (() => { const v = singleResult.streams.find(s => s.codec_type === 'video'); return v ? `${v.width}x${v.height}` : ''; })(),
    video_profile: singleResult.streams.find(s => s.codec_type === 'video')?.profile || '',
    avg_keyframe_interval_secs: singleResult.keyframe_interval_secs,
    audio_codec: singleResult.streams.find(s => s.codec_type === 'audio')?.codec_name || '',
    audio_channels: singleResult.streams.find(s => s.codec_type === 'audio')?.channels || 0,
    audio_sample_rate: singleResult.streams.find(s => s.codec_type === 'audio')?.sample_rate || 0,
    total_errors: singleResult.errors.length,
    total_warnings: singleResult.warnings.length,
    segments: [singleResult],
  } as ProbeResult : null);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Video Quality Probe</h2>
      <p className="mt-1 text-sm text-gray-500">
        Analyze HLS/DASH streams or local media segments for codec info, bitrate, resolution, and keyframe intervals.
      </p>

      {/* Mode toggle */}
      <div className="mt-4 flex gap-2">
        <button onClick={() => setMode('url')}
          className={`rounded-lg px-4 py-1.5 text-sm font-medium ${mode === 'url' ? 'bg-blue-600 text-white' : 'border border-gray-600 text-gray-400'}`}>
          Stream URL
        </button>
        <button onClick={() => setMode('files')}
          className={`rounded-lg px-4 py-1.5 text-sm font-medium ${mode === 'files' ? 'bg-blue-600 text-white' : 'border border-gray-600 text-gray-400'}`}>
          Local Files
        </button>
      </div>

      {mode === 'url' && (
        <div className="mt-4">
          <label className="mb-1 block text-xs text-gray-500">HLS / DASH / Media URL</label>
          <input
            type="text"
            value={streamUrl}
            onChange={e => setStreamUrl(e.target.value)}
            placeholder="https://example.com/stream.m3u8"
            className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />
          <div className="mt-2 flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">Max segments:</label>
              <input type="number" value={maxSegments} onChange={e => setMaxSegments(Number(e.target.value))}
                min={1} max={20}
                className="w-16 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white" />
            </div>
            <button
              onClick={probeUrl}
              disabled={probing || !streamUrl.trim()}
              className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {probing ? 'Fetching & Analyzing...' : 'Analyze Stream'}
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-600">
            Supports .m3u8 (HLS master/media), .mpd (DASH), or direct .ts/.mp4/.m4s URLs
          </p>
        </div>
      )}

      {mode === 'files' && (
        <>
          {/* Segment discovery */}
          <div className="mt-4 flex items-end gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-xs text-gray-500">Segment Directory</label>
              <input
                type="text"
                value={segmentDir}
                onChange={e => setSegmentDir(e.target.value)}
                className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
            </div>
            <button
              onClick={discoverSegments}
              className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              Discover Files
            </button>
          </div>

          {/* File paths */}
          <div className="mt-3">
            <label className="mb-1 block text-xs text-gray-500">
              File Paths (one per line) {discoveredFiles.length > 0 && `\u2014 ${discoveredFiles.length} found`}
            </label>
            <textarea
              value={paths}
              onChange={e => setPaths(e.target.value)}
              rows={4}
              placeholder="/var/lib/wifry/segments/example.ts"
              className="w-full rounded border border-gray-300 bg-white px-3 py-2 font-mono text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-white"
            />
          </div>

          {/* Action buttons */}
          <div className="mt-3 flex gap-3">
            <button
              onClick={probeMultiple}
              disabled={probing || !paths.trim()}
              className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {probing ? 'Analyzing...' : 'Analyze All'}
            </button>
            {paths.trim().split('\n').length === 1 && paths.trim() && (
              <button
                onClick={() => probeSingle(paths.trim())}
                disabled={probing}
                className="rounded-lg border border-blue-300 px-4 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50 dark:border-blue-700 dark:text-blue-400"
              >
                Analyze Single
              </button>
            )}
          </div>
        </>
      )}

      {error && (
        <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Manifest info */}
      {manifestInfo && (
        <div className="mt-4 rounded-lg border border-gray-700 bg-gray-800/50 p-3">
          <div className="text-xs font-medium text-gray-400">Manifest</div>
          <div className="mt-1 flex flex-wrap gap-4 text-xs text-gray-500">
            <span>Type: <span className="text-gray-300">{String(manifestInfo.type || '').toUpperCase()}</span></span>
            {'variants' in manifestInfo && <span>Variants: <span className="text-gray-300">{String(manifestInfo.variants)}</span></span>}
            {'segments_total' in manifestInfo && <span>Total segments: <span className="text-gray-300">{String(manifestInfo.segments_total)}</span></span>}
            {'selected' in manifestInfo && manifestInfo.selected != null && (
              <span>Selected: <span className="text-gray-300">{String((manifestInfo.selected as Record<string, string>).resolution)} @ {String((manifestInfo.selected as Record<string, string>).bandwidth)} bps</span></span>
            )}
          </div>
        </div>
      )}

      {/* Results */}
      {activeResult && (
        <div className="mt-6">
          {/* Summary stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {activeResult.video_codec && (
              <StatBox label="Video Codec" value={activeResult.video_codec.toUpperCase()} sub={activeResult.video_profile} />
            )}
            {activeResult.video_resolution && (
              <StatBox label="Resolution" value={activeResult.video_resolution} />
            )}
            <StatBox label="Avg Bitrate" value={formatBitrate(activeResult.avg_bitrate_bps)}
              sub={activeResult.min_bitrate_bps !== activeResult.max_bitrate_bps
                ? `${formatBitrate(activeResult.min_bitrate_bps)} \u2013 ${formatBitrate(activeResult.max_bitrate_bps)}` : undefined} />
            <StatBox label="Segments" value={String(activeResult.segments_analyzed)}
              sub={`${activeResult.total_duration_secs.toFixed(1)}s total`} />
            {activeResult.avg_keyframe_interval_secs > 0 && (
              <StatBox label="Keyframe Interval" value={`${activeResult.avg_keyframe_interval_secs.toFixed(2)}s`} />
            )}
            {activeResult.audio_codec && (
              <StatBox label="Audio" value={activeResult.audio_codec.toUpperCase()}
                sub={`${activeResult.audio_channels}ch ${activeResult.audio_sample_rate ? (activeResult.audio_sample_rate / 1000).toFixed(0) + 'kHz' : ''}`} />
            )}
            {activeResult.total_errors > 0 && (
              <StatBox label="Errors" value={String(activeResult.total_errors)} />
            )}
            {activeResult.total_warnings > 0 && (
              <StatBox label="Warnings" value={String(activeResult.total_warnings)} />
            )}
          </div>

          {/* Per-segment details */}
          {activeResult.segments.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-2 text-sm font-medium text-gray-400">Segment Details</h3>
              <div className="space-y-1">
                {activeResult.segments.map((seg, i) => (
                  <div key={i} className={`rounded px-3 py-2 text-sm ${
                    seg.errors.length > 0 ? 'border border-red-500/20 bg-red-500/5' : 'bg-gray-800/50'
                  }`}>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-gray-400">{seg.path.split('/').pop()}</span>
                      <div className="flex gap-4 text-xs text-gray-500">
                        <span>{formatBytes(seg.file_size_bytes)}</span>
                        <span>{seg.duration_secs.toFixed(2)}s</span>
                        <span>{formatBitrate(seg.actual_bitrate_bps)}</span>
                        <span>{seg.format_name}</span>
                      </div>
                    </div>
                    {seg.streams.map((s, j) => (
                      <div key={j} className="mt-1 text-xs text-gray-500">
                        {s.codec_type === 'video' && (
                          <span>{s.codec_name} {s.profile} {s.width}x{s.height} @{s.frame_rate}fps</span>
                        )}
                        {s.codec_type === 'audio' && (
                          <span>{s.codec_name} {s.channels}ch {s.sample_rate}Hz</span>
                        )}
                      </div>
                    ))}
                    {seg.errors.map((e, j) => (
                      <div key={`e${j}`} className="mt-1 text-xs text-red-400">{e}</div>
                    ))}
                    {seg.warnings.map((w, j) => (
                      <div key={`w${j}`} className="mt-1 text-xs text-yellow-400">{w}</div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
