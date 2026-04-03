import { useState } from 'react';

interface WifiNetwork {
  ssid: string;
  bssid: string;
  channel: number;
  frequency_mhz: number;
  signal_dbm: number;
  security: string;
  band: string;
  width: string;
}

interface ChannelInfo {
  channel: number;
  frequency_mhz: number;
  band: string;
  network_count: number;
  strongest_signal_dbm: number;
  networks: string[];
}

interface ScanData {
  scan_interface: string;
  our_channel: number;
  our_band: string;
  network_count: number;
  networks: WifiNetwork[];
  channels_2g: ChannelInfo[];
  channels_5g: ChannelInfo[];
}

function signalColor(dbm: number): string {
  if (dbm >= -50) return 'bg-green-500';
  if (dbm >= -65) return 'bg-yellow-500';
  if (dbm >= -75) return 'bg-orange-500';
  return 'bg-red-500';
}

function signalBarWidth(dbm: number): number {
  // Map -90dBm...-20dBm to 0...100%
  return Math.max(0, Math.min(100, ((dbm + 90) / 70) * 100));
}

export default function WifiScanner() {
  const [data, setData] = useState<ScanData | null>(null);
  const [scanning, setScanning] = useState(false);

  const scan = async () => {
    setScanning(true);
    try {
      const res = await fetch('/api/v1/wifi/scan');
      setData(await res.json());
    } catch (e) {
      alert('Scan failed');
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">WiFi Environment</h2>
          <button
            onClick={scan}
            disabled={scanning}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {scanning ? 'Scanning...' : 'Scan'}
          </button>
        </div>

        {!data && !scanning && (
          <p className="py-8 text-center text-sm text-gray-500">Click Scan to survey the WiFi environment.</p>
        )}

        {data && (
          <>
            <div className="mb-4 flex gap-4 text-sm">
              <span className="text-gray-500">Interface: <strong className="text-gray-900 dark:text-white">{data.scan_interface}</strong></span>
              <span className="text-gray-500">Our channel: <strong className="text-blue-500">{data.our_channel} ({data.our_band})</strong></span>
              <span className="text-gray-500">Networks found: <strong className="text-gray-900 dark:text-white">{data.network_count}</strong></span>
            </div>

            {/* Channel utilization bars */}
            <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">2.4 GHz Channels</h3>
            <div className="mb-4 flex items-end gap-1" style={{ height: '80px' }}>
              {data.channels_2g.filter(c => [1,2,3,4,5,6,7,8,9,10,11].includes(c.channel)).map(c => {
                const height = c.network_count > 0 ? Math.max(20, Math.min(100, c.network_count * 25)) : 4;
                const isOurs = c.channel === data.our_channel && data.our_band === '2.4GHz';
                return (
                  <div key={c.channel} className="flex flex-1 flex-col items-center gap-1">
                    <div
                      className={`w-full rounded-t transition-all ${isOurs ? 'bg-blue-500' : c.network_count > 3 ? 'bg-red-500' : c.network_count > 1 ? 'bg-yellow-500' : c.network_count > 0 ? 'bg-green-500' : 'bg-gray-700'}`}
                      style={{ height: `${height}%` }}
                      title={`Ch ${c.channel}: ${c.network_count} networks`}
                    />
                    <span className={`text-[10px] ${isOurs ? 'font-bold text-blue-400' : 'text-gray-500'}`}>{c.channel}</span>
                  </div>
                );
              })}
            </div>

            {data.channels_5g.some(c => c.network_count > 0) && (
              <>
                <h3 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">5 GHz Channels</h3>
                <div className="mb-4 flex items-end gap-1" style={{ height: '80px' }}>
                  {data.channels_5g.filter(c => c.network_count > 0 || [36,40,44,48,149,153,157,161,165].includes(c.channel)).map(c => {
                    const height = c.network_count > 0 ? Math.max(20, Math.min(100, c.network_count * 30)) : 4;
                    const isOurs = c.channel === data.our_channel && data.our_band === '5GHz';
                    return (
                      <div key={c.channel} className="flex flex-1 flex-col items-center gap-1">
                        <div
                          className={`w-full rounded-t ${isOurs ? 'bg-blue-500' : c.network_count > 2 ? 'bg-red-500' : c.network_count > 0 ? 'bg-green-500' : 'bg-gray-700'}`}
                          style={{ height: `${height}%` }}
                          title={`Ch ${c.channel}: ${c.network_count} networks`}
                        />
                        <span className={`text-[10px] ${isOurs ? 'font-bold text-blue-400' : 'text-gray-500'}`}>{c.channel}</span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            {/* Network table */}
            <h3 className="mb-2 mt-4 text-sm font-medium text-gray-500 dark:text-gray-400">Detected Networks</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-gray-200 text-gray-500 dark:border-gray-700">
                  <tr>
                    <th className="py-2 pr-3">SSID</th>
                    <th className="py-2 pr-3">Ch</th>
                    <th className="py-2 pr-3">Band</th>
                    <th className="py-2 pr-3">Signal</th>
                    <th className="py-2 pr-3">Security</th>
                    <th className="py-2">BSSID</th>
                  </tr>
                </thead>
                <tbody>
                  {data.networks.sort((a, b) => b.signal_dbm - a.signal_dbm).map((n, i) => (
                    <tr key={i} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="py-1.5 pr-3 font-medium text-gray-900 dark:text-white">{n.ssid || '(hidden)'}</td>
                      <td className="py-1.5 pr-3">{n.channel}</td>
                      <td className="py-1.5 pr-3">{n.band}</td>
                      <td className="py-1.5 pr-3">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-16 overflow-hidden rounded-full bg-gray-700">
                            <div className={`h-full rounded-full ${signalColor(n.signal_dbm)}`} style={{ width: `${signalBarWidth(n.signal_dbm)}%` }} />
                          </div>
                          <span>{n.signal_dbm} dBm</span>
                        </div>
                      </td>
                      <td className="py-1.5 pr-3">{n.security}</td>
                      <td className="py-1.5 font-mono text-gray-500">{n.bssid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
