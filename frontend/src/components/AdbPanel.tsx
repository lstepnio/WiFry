import { useCallback, useState } from 'react';
import type { AdbDevice, AdbShellResult, LogcatLine, LogcatSession } from '../types';
import * as api from '../api/client';
import { useApi } from '../hooks/useApi';
import { useConfirm } from '../hooks/useConfirm';
import { useNotification } from '../hooks/useNotification';

const STATE_COLORS: Record<string, string> = {
  connected: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  disconnected: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  offline: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  unauthorized: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

const LEVEL_COLORS: Record<string, string> = {
  V: 'text-gray-400',
  D: 'text-blue-400',
  I: 'text-green-400',
  W: 'text-yellow-400',
  E: 'text-red-400',
  F: 'text-red-600 font-bold',
};

// Remote button styling helpers
const btnBase = "flex items-center justify-center rounded font-medium transition-colors active:scale-95";
const btnSmall = `${btnBase} text-xs h-9 w-16`;
const btnMedium = `${btnBase} text-xs h-10 w-20`;
const btnLarge = `${btnBase} text-sm h-12 w-12`;
const btnOk = `${btnBase} text-sm h-14 w-14 rounded-full`;
const btnDark = "border border-gray-600 bg-gray-700 text-gray-200 hover:bg-gray-600 dark:bg-gray-700 dark:hover:bg-gray-600";
const btnAccent = "border border-blue-600 bg-blue-700 text-white hover:bg-blue-600";
const btnRed = "border border-red-700 bg-red-800 text-red-200 hover:bg-red-700";
const btnGreen = "border border-green-700 bg-green-800 text-green-200 hover:bg-green-700";

interface AdbFile {
  filename: string;
  path: string;
  type: string;
  size_bytes: number;
  created_at: string;
}

function DataCollection({ serial, onShellCmd }: { serial: string; onShellCmd: (cmd: string) => void }) {
  const confirmAction = useConfirm();
  const { notify } = useNotification();
  const filesFetcher = useCallback(async () => {
    const res = await fetch('/api/v1/adb/files');
    return res.json();
  }, []);
  const { data: files, refresh: refreshFiles } = useApi<AdbFile[]>(filesFetcher, 5000);
  const [capturing, setCapturing] = useState<string | null>(null);
  const [sharing, setSharing] = useState<string | null>(null);

  const takeScreenshot = async () => {
    setCapturing('screenshot');
    try {
      const res = await fetch(`/api/v1/adb/screencap/${encodeURIComponent(serial)}`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      refreshFiles();
    } catch { notify('Screenshot failed', 'error'); }
    finally { setCapturing(null); }
  };

  const takeBugreport = async () => {
    setCapturing('bugreport');
    try {
      const res = await fetch(`/api/v1/adb/bugreport/${encodeURIComponent(serial)}`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      refreshFiles();
    } catch { notify('Bugreport failed', 'error'); }
    finally { setCapturing(null); }
  };

  const downloadFile = (filename: string) => {
    window.open(`/api/v1/adb/files/download/${encodeURIComponent(filename)}`, '_blank');
  };

  const shareFile = async (path: string, filename: string) => {
    setSharing(filename);
    try {
      const res = await fetch('/api/v1/fileio/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: path, expires: '15m' }),
      });
      const data = await res.json();
      if (data.link) {
        navigator.clipboard.writeText(data.link);
        notify(`Link copied: ${data.link} (expires in 15 min, single download)`, 'success');
      } else {
        notify(data.error || 'Share failed', 'error');
      }
    } catch { notify('Share failed', 'error'); }
    finally { setSharing(null); }
  };

  const deleteFile = async (filename: string) => {
    if (!await confirmAction({ title: 'Delete File', message: `Delete ${filename}?`, confirmLabel: 'Delete', confirmTone: 'danger' })) return;
    await fetch(`/api/v1/adb/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    refreshFiles();
  };

  const deleteAllFiles = async () => {
    const allFiles = files ?? [];
    if (allFiles.length === 0) return;
    if (!await confirmAction({ title: 'Delete All Files', message: `Delete all ${allFiles.length} saved file(s)?`, confirmLabel: 'Delete All', confirmTone: 'danger' })) return;
    try {
      for (const f of allFiles) {
        await fetch(`/api/v1/adb/files/${encodeURIComponent(f.filename)}`, { method: 'DELETE' });
      }
      refreshFiles();
    } catch {
      notify('Failed to delete some files', 'error');
      refreshFiles();
    }
  };

  const formatBytes = (b: number) => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : b >= 1024 ? `${(b / 1024).toFixed(1)} KB` : `${b} B`;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h3 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">Data Collection — {serial}</h3>

      {/* Capture buttons */}
      <div className="mb-4 flex flex-wrap gap-2">
        <button onClick={takeScreenshot} disabled={capturing === 'screenshot'}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {capturing === 'screenshot' ? 'Capturing...' : 'Screenshot'}
        </button>
        <button onClick={takeBugreport} disabled={capturing === 'bugreport'}
          className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50">
          {capturing === 'bugreport' ? 'Capturing...' : 'Bug Report'}
        </button>
        <button onClick={() => onShellCmd('dumpsys media.player')}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300">
          Dump Media Player
        </button>
        <button onClick={() => onShellCmd('dumpsys netstats')}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300">
          Dump Net Stats
        </button>
      </div>

      {/* Saved files */}
      {(files ?? []).length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-medium text-gray-500">Saved Files ({(files ?? []).length})</h4>
            <button onClick={deleteAllFiles}
              className="rounded border border-red-700 px-2 py-1 text-[10px] font-medium text-red-400 hover:bg-red-900">
              Delete All Files
            </button>
          </div>
          <div className="space-y-1">
            {(files ?? []).map(f => (
              <div key={f.filename} className="flex items-center justify-between rounded border border-gray-700 bg-gray-800/50 px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${f.type === 'screenshot' ? 'bg-blue-900 text-blue-300' : f.type === 'bugreport' ? 'bg-orange-900 text-orange-300' : 'bg-gray-700 text-gray-400'}`}>
                    {f.type}
                  </span>
                  <span className="text-xs text-gray-300">{f.filename}</span>
                  <span className="text-xs text-gray-600">{formatBytes(f.size_bytes)}</span>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => downloadFile(f.filename)}
                    className="rounded bg-gray-700 px-2 py-1 text-[10px] text-gray-300 hover:bg-gray-600">Download</button>
                  <button onClick={() => shareFile(f.path, f.filename)} disabled={sharing === f.filename}
                    className="rounded bg-green-700 px-2 py-1 text-[10px] text-green-200 hover:bg-green-600 disabled:opacity-50">
                    {sharing === f.filename ? '...' : 'Share'}
                  </button>
                  <button onClick={() => deleteFile(f.filename)}
                    className="rounded bg-red-900 px-2 py-1 text-[10px] text-red-300 hover:bg-red-800">Delete</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AdbPanel() {
  const { notify } = useNotification();
  const deviceFetcher = useCallback(() => api.getAdbDevices(), []);
  const { data: devices, refresh: refreshDevices } = useApi<AdbDevice[]>(deviceFetcher, 5000);

  const [connectIp, setConnectIp] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState<string | null>(null);
  const [shellCmd, setShellCmd] = useState('');
  const [shellOutput, setShellOutput] = useState<AdbShellResult | null>(null);
  const [shellRunning, setShellRunning] = useState(false);

  // Logcat
  const [activeLogcat, setActiveLogcat] = useState<LogcatSession | null>(null);
  const logcatFetcher = useCallback(
    () => activeLogcat ? api.getLogcatLines(activeLogcat.id, 100) : Promise.resolve([]),
    [activeLogcat],
  );
  const { data: logcatLines } = useApi<LogcatLine[]>(logcatFetcher, activeLogcat ? 2000 : 0);
  const [logcatTagFilter, setLogcatTagFilter] = useState('');

  const handleConnect = async () => {
    if (!connectIp) return;
    setConnecting(true);
    try {
      await api.connectAdbDevice(connectIp);
      setConnectIp('');
      refreshDevices();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Connection failed', 'error');
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async (serial: string) => {
    await api.disconnectAdbDevice(serial);
    if (selectedDevice === serial) setSelectedDevice(null);
    refreshDevices();
  };

  const handleShell = async () => {
    if (!selectedDevice || !shellCmd) return;
    setShellRunning(true);
    try {
      const result = await api.adbShell(selectedDevice, shellCmd);
      setShellOutput(result);
    } catch (e) {
      setShellOutput({ serial: selectedDevice, command: shellCmd, stdout: '', stderr: String(e), exit_code: -1 });
    } finally {
      setShellRunning(false);
    }
  };

  const handleKey = async (keycode: string) => {
    if (!selectedDevice) return;
    try {
      await api.adbSendKey(selectedDevice, keycode);
    } catch {
      // silent for key events
    }
  };

  const handleStartLogcat = async () => {
    if (!selectedDevice) return;
    try {
      const session = await api.startLogcat(selectedDevice);
      setActiveLogcat(session);
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Failed to start logcat', 'error');
    }
  };

  const handleStopLogcat = async () => {
    if (!activeLogcat) return;
    await api.stopLogcat(activeLogcat.id);
    setActiveLogcat(null);
  };

  const filteredLogcat = logcatTagFilter
    ? (logcatLines ?? []).filter(l => l.tag.toLowerCase().includes(logcatTagFilter.toLowerCase()))
    : (logcatLines ?? []);

  return (
    <div className="space-y-4">
      {/* Connect */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">ADB Devices</h2>

        <div className="mb-4 flex gap-2">
          <input
            value={connectIp}
            onChange={(e) => setConnectIp(e.target.value)}
            placeholder="192.168.4.10"
            onKeyDown={(e) => e.key === 'Enter' && handleConnect()}
            className="w-48 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />
          <button
            onClick={handleConnect}
            disabled={connecting || !connectIp}
            className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {connecting ? 'Connecting...' : 'Connect'}
          </button>
        </div>

        <div className="space-y-2">
          {(devices ?? []).map((d) => (
            <div
              key={d.serial}
              onClick={() => d.state === 'connected' && setSelectedDevice(d.serial)}
              className={`flex cursor-pointer items-center justify-between rounded-lg border px-4 py-3 ${
                selectedDevice === d.serial ? 'border-blue-500 bg-blue-50 dark:bg-blue-950' : 'border-gray-100 bg-gray-50 dark:border-gray-700 dark:bg-gray-800'
              }`}
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-gray-900 dark:text-white">{d.serial}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATE_COLORS[d.state] || ''}`}>{d.state}</span>
                </div>
                {d.model && (
                  <div className="text-xs text-gray-500">{d.manufacturer} {d.model} — Android {d.android_version}</div>
                )}
              </div>
              {d.state === 'connected' && (
                <button
                  onClick={(e) => { e.stopPropagation(); handleDisconnect(d.serial); }}
                  className="rounded border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
                >
                  Disconnect
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {selectedDevice && (
        <>
          {/* Remote control */}
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="mb-4 text-sm font-medium text-gray-500 dark:text-gray-400">Remote Control — {selectedDevice}</h3>

            <div className="mx-auto flex max-w-xs flex-col items-center gap-5 rounded-2xl bg-gray-800 px-6 py-6 dark:bg-gray-950">

              {/* Top row: Power, Guide, Info */}
              <div className="flex w-full justify-between">
                <button onClick={() => handleKey('power')} className={`${btnSmall} ${btnRed}`}>Power</button>
                <button onClick={() => handleKey('guide')} className={`${btnSmall} ${btnDark}`}>Guide</button>
                <button onClick={() => handleKey('info')} className={`${btnSmall} ${btnDark}`}>Info</button>
              </div>

              {/* D-pad + OK */}
              <div className="flex flex-col items-center gap-1">
                <button onClick={() => handleKey('up')} className={`${btnLarge} ${btnDark}`}>&#x25B2;</button>
                <div className="flex items-center gap-1">
                  <button onClick={() => handleKey('left')} className={`${btnLarge} ${btnDark}`}>&#x25C0;</button>
                  <button onClick={() => handleKey('enter')} className={`${btnOk} ${btnAccent}`}>OK</button>
                  <button onClick={() => handleKey('right')} className={`${btnLarge} ${btnDark}`}>&#x25B6;</button>
                </div>
                <button onClick={() => handleKey('down')} className={`${btnLarge} ${btnDark}`}>&#x25BC;</button>
              </div>

              {/* Back, Home, Menu row */}
              <div className="flex w-full justify-between">
                <button onClick={() => handleKey('back')} className={`${btnMedium} ${btnDark}`}>Back</button>
                <button onClick={() => handleKey('home')} className={`${btnMedium} ${btnDark}`}>Home</button>
                <button onClick={() => handleKey('menu')} className={`${btnMedium} ${btnDark}`}>Menu</button>
              </div>

              {/* Divider */}
              <div className="w-full border-t border-gray-700" />

              {/* Media controls */}
              <div className="flex w-full justify-between">
                <button onClick={() => handleKey('rewind')} className={`${btnSmall} ${btnDark}`}>&#x23EA;</button>
                <button onClick={() => handleKey('play_pause')} className={`${btnSmall} ${btnGreen}`}>&#x23EF;</button>
                <button onClick={() => handleKey('stop')} className={`${btnSmall} ${btnDark}`}>&#x23F9;</button>
                <button onClick={() => handleKey('fast_forward')} className={`${btnSmall} ${btnDark}`}>&#x23E9;</button>
              </div>

              {/* Volume + Channel */}
              <div className="flex w-full justify-between gap-6">
                <div className="flex flex-col items-center gap-1">
                  <span className="text-[10px] uppercase text-gray-500">Volume</span>
                  <button onClick={() => handleKey('volume_up')} className={`${btnSmall} ${btnDark}`}>Vol +</button>
                  <button onClick={() => handleKey('mute')} className={`${btnSmall} ${btnRed}`}>Mute</button>
                  <button onClick={() => handleKey('volume_down')} className={`${btnSmall} ${btnDark}`}>Vol -</button>
                </div>
                <div className="flex flex-col items-center gap-1">
                  <span className="text-[10px] uppercase text-gray-500">Channel</span>
                  <button onClick={() => handleKey('channel_up')} className={`${btnSmall} ${btnDark}`}>CH +</button>
                  <div className="h-9" />
                  <button onClick={() => handleKey('channel_down')} className={`${btnSmall} ${btnDark}`}>CH -</button>
                </div>
              </div>

            </div>
          </div>

          {/* Data Collection */}
          <DataCollection serial={selectedDevice} onShellCmd={(cmd) => { setShellCmd(cmd); handleShell(); }} />

          {/* Shell */}
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">Shell</h3>
            <div className="flex gap-2">
              <input
                value={shellCmd}
                onChange={(e) => setShellCmd(e.target.value)}
                placeholder="dumpsys media.player"
                onKeyDown={(e) => e.key === 'Enter' && handleShell()}
                className="flex-1 rounded border border-gray-300 bg-white px-3 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              />
              <button
                onClick={handleShell}
                disabled={shellRunning}
                className="rounded-lg bg-gray-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              >
                Run
              </button>
            </div>
            {shellOutput && (
              <pre className="mt-3 max-h-64 overflow-auto rounded bg-gray-950 p-3 font-mono text-xs text-green-400">
                <span className="text-gray-500">$ {shellOutput.command}</span>
                {'\n'}{shellOutput.stdout}
                {shellOutput.stderr && <span className="text-red-400">{'\n'}{shellOutput.stderr}</span>}
              </pre>
            )}
          </div>

          {/* Logcat */}
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">
                Logcat {activeLogcat && `(${activeLogcat.line_count} lines)`}
              </h3>
              <div className="flex gap-2">
                <input
                  value={logcatTagFilter}
                  onChange={(e) => setLogcatTagFilter(e.target.value)}
                  placeholder="Filter by tag..."
                  className="w-40 rounded border border-gray-300 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                />
                {!activeLogcat ? (
                  <button onClick={handleStartLogcat} className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700">
                    Start
                  </button>
                ) : (
                  <button onClick={handleStopLogcat} className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700">
                    Stop
                  </button>
                )}
              </div>
            </div>
            <div className="max-h-80 overflow-auto rounded bg-gray-950 p-2 font-mono text-xs">
              {filteredLogcat.length === 0 ? (
                <span className="text-gray-500">No logcat output. Start a logcat session above.</span>
              ) : (
                filteredLogcat.map((line, i) => (
                  <div key={i} className={LEVEL_COLORS[line.level] || 'text-gray-400'}>
                    <span className="text-gray-600">{line.timestamp} </span>
                    <span className="text-gray-500">{line.pid}/{line.tid} </span>
                    <span className="font-bold">{line.level} </span>
                    <span className="text-cyan-400">{line.tag}: </span>
                    {line.message}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
