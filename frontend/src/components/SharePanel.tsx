import { useCallback, useState } from 'react';
import { useApi } from '../hooks/useApi';

interface TunnelStatus {
  active: boolean;
  url: string | null;
  started_at: string | null;
  share_url: string | null;
  message: string;
}

interface UploadResult {
  success: boolean;
  link?: string;
  filename?: string;
  size_bytes?: number;
  files_bundled?: number;
  expires?: string;
  uploaded_at?: string;
  error?: string;
}

const CATEGORIES = ['captures', 'reports', 'logs', 'hdmi', 'segments'] as const;
const EXPIRY_OPTIONS = [
  { value: '15m', label: '15 minutes' },
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '6h', label: '6 hours' },
  { value: '12h', label: '12 hours' },
  { value: '1d', label: '1 day' },
] as const;

export default function SharePanel() {
  const fetcher = useCallback(async () => {
    const res = await fetch('/api/v1/tunnel/status');
    return res.json();
  }, []);
  const { data: status, refresh } = useApi<TunnelStatus>(fetcher, 5000);

  const historyFetcher = useCallback(async () => {
    const res = await fetch('/api/v1/fileio/history');
    return res.json();
  }, []);
  const { data: history, refresh: refreshHistory } = useApi<UploadResult[]>(historyFetcher);

  const [toggling, setToggling] = useState(false);
  const [copied, setCopied] = useState('');
  const [uploading, setUploading] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<UploadResult | null>(null);
  const [expiry, setExpiry] = useState('15m');

  const toggleTunnel = async () => {
    setToggling(true);
    try {
      const endpoint = status?.active ? 'stop' : 'start';
      await fetch(`/api/v1/tunnel/${endpoint}`, { method: 'POST' });
      refresh();
    } catch { alert('Tunnel error'); }
    finally { setToggling(false); }
  };

  const copyUrl = (url: string, id: string) => {
    try {
      navigator.clipboard.writeText(url);
    } catch {
      // Fallback for non-HTTPS contexts
      const ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(id);
    setTimeout(() => setCopied(''), 2000);
  };

  const uploadCategory = async (category: string) => {
    setUploading(category);
    setLastUpload(null);
    try {
      const res = await fetch('/api/v1/fileio/upload-category', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category, expires: expiry }),
      });
      const data = await res.json();
      setLastUpload(data);
      refreshHistory();
    } catch { alert('Upload failed'); }
    finally { setUploading(null); }
  };

  return (
    <div className="space-y-4">
      {/* Cloudflare Tunnel */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Share Diagnostics</h2>
            <p className="text-xs text-gray-500">Share data with your team via tunnel or file upload</p>
          </div>
        </div>

        {/* Cloudflare Tunnel Section */}
        <div className="mb-4 rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-300">Cloudflare Quick Tunnel</h3>
            <button onClick={toggleTunnel} disabled={toggling}
              className={`rounded-lg px-4 py-1.5 text-xs font-medium text-white disabled:opacity-50 ${status?.active ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'}`}>
              {toggling ? '...' : status?.active ? 'Stop' : 'Start Tunnel'}
            </button>
          </div>
          {status?.active && status.url ? (
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-gray-900 px-3 py-1.5 font-mono text-xs text-green-300">{status.url}</code>
              <button onClick={() => copyUrl(status.url!, 'tunnel')}
                className="rounded bg-green-600 px-2 py-1.5 text-xs text-white hover:bg-green-700">
                {copied === 'tunnel' ? 'Copied!' : 'Copy'}
              </button>
            </div>
          ) : (
            <p className="text-xs text-gray-500">Creates a live tunnel for real-time browsing of all diagnostics. Requires cloudflared.</p>
          )}
        </div>

        {/* File.io Upload Section */}
        <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-300">Quick Upload (file.io)</h3>
          <div className="mb-3 flex items-center gap-2">
            <span className="text-xs text-gray-500">Link expires in:</span>
            <select value={expiry} onChange={(e) => setExpiry(e.target.value)}
              className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-white">
              {EXPIRY_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <span className="text-xs text-gray-600">Single-use download link</span>
          </div>

          <div className="flex flex-wrap gap-2">
            {CATEGORIES.map(cat => (
              <button
                key={cat}
                onClick={() => uploadCategory(cat)}
                disabled={uploading === cat}
                className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-1.5 text-xs font-medium capitalize text-gray-300 hover:bg-gray-600 disabled:opacity-50"
              >
                {uploading === cat ? 'Uploading...' : `Upload ${cat}`}
              </button>
            ))}
          </div>

          {/* Last upload result */}
          {lastUpload && (
            <div className={`mt-3 rounded-lg p-3 ${lastUpload.success ? 'border border-green-700 bg-green-950/30' : 'border border-red-700 bg-red-950/30'}`}>
              {lastUpload.success ? (
                <>
                  <div className="mb-1 text-xs font-medium text-green-400">Upload successful!</div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 rounded bg-gray-900 px-3 py-1.5 font-mono text-xs text-green-300">{lastUpload.link}</code>
                    <button onClick={() => copyUrl(lastUpload.link!, 'fileio')}
                      className="rounded bg-green-600 px-2 py-1.5 text-xs text-white hover:bg-green-700">
                      {copied === 'fileio' ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    {lastUpload.filename}
                    {lastUpload.files_bundled ? ` (${lastUpload.files_bundled} files)` : ''}
                    {' — expires in '}{lastUpload.expires}
                    {' — single-use download link'}
                  </div>
                </>
              ) : (
                <div className="text-xs text-red-400">{lastUpload.error}</div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Upload history */}
      {(history ?? []).length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <h3 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">Recent Uploads</h3>
          <div className="space-y-2">
            {(history ?? []).slice(0, 10).map((u, i) => (
              <div key={i} className="flex items-center justify-between rounded border border-gray-700 bg-gray-800/50 px-3 py-2">
                <div>
                  <span className="text-xs font-medium text-gray-300">{u.filename}</span>
                  {u.files_bundled && <span className="ml-2 text-xs text-gray-500">({u.files_bundled} files)</span>}
                  <div className="text-[10px] text-gray-500">{u.uploaded_at ? new Date(u.uploaded_at).toLocaleString() : ''}</div>
                </div>
                {u.link && (
                  <button onClick={() => copyUrl(u.link!, `h-${i}`)}
                    className="rounded bg-gray-700 px-2 py-1 text-xs text-gray-300 hover:bg-gray-600">
                    {copied === `h-${i}` ? 'Copied!' : 'Copy Link'}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
