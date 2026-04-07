import { useCallback, useEffect, useRef, useState } from 'react';
import { activateGremlin, deactivateGremlin, getGremlinStatus } from '../api/client';
import type { GremlinStatus } from '../types';

const KONAMI = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];

const INTENSITY_LABELS = ['', 'Mild', 'Medium', 'Severe', 'Extreme'];
const INTENSITY_COLORS = ['', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-600'];

export default function Gremlin() {
  const [revealed, setRevealed] = useState(false);
  const [status, setStatus] = useState<GremlinStatus | null>(null);
  const [toggling, setToggling] = useState(false);
  const [intensity, setIntensity] = useState(2);
  const seqRef = useRef<string[]>([]);

  const fetchStatus = useCallback(async () => {
    try {
      const nextStatus = await getGremlinStatus();
      setStatus(nextStatus);
      setIntensity(nextStatus.intensity || 2);
    } catch {
      // Ignore status polling failures while hidden.
    }
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      seqRef.current.push(e.key);
      if (seqRef.current.length > KONAMI.length) {
        seqRef.current = seqRef.current.slice(-KONAMI.length);
      }
      if (seqRef.current.length === KONAMI.length &&
          seqRef.current.every((k, i) => k === KONAMI[i])) {
        setRevealed(true);
        seqRef.current = [];
        fetchStatus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [fetchStatus]);

  const toggle = async () => {
    setToggling(true);
    try {
      if (status?.active) {
        setStatus(await deactivateGremlin());
      } else {
        setStatus(await activateGremlin(intensity));
      }
    } catch (e) {
      alert('Gremlin error: ' + e);
    } finally {
      setToggling(false);
    }
  };

  const updateIntensity = async (val: number) => {
    setIntensity(val);
    if (status?.active) {
      // Re-activate with new intensity
      setStatus(await activateGremlin(val));
    }
  };

  if (!revealed) return null;

  const details = status?.details;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 overflow-hidden rounded-xl border border-purple-500 bg-gray-900 shadow-2xl shadow-purple-900/50">
      <div className="flex items-center justify-between bg-purple-900/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">&#x1F9EA;</span>
          <span className="text-sm font-bold text-purple-200">Network Chaos Mode</span>
        </div>
        <button onClick={() => setRevealed(false)} className="text-purple-400 hover:text-purple-200">&#x2715;</button>
      </div>

      <div className="p-4">
        {status && (
          <>
            <div className={`mb-3 rounded-lg px-3 py-2 text-center text-sm font-medium ${
              status.active
                ? 'bg-red-900/40 text-red-300 border border-red-700'
                : 'bg-gray-800 text-gray-400 border border-gray-700'
            }`}>
              {status.message}
            </div>

            {/* Intensity slider */}
            <div className="mb-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs text-gray-400">Chaos Intensity</span>
                <span className={`text-xs font-bold ${INTENSITY_COLORS[intensity]}`}>
                  {INTENSITY_LABELS[intensity]}
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={4}
                step={1}
                value={intensity}
                onChange={(e) => updateIntensity(Number(e.target.value))}
                className="w-full accent-purple-500"
              />
              <div className="flex justify-between text-[9px] text-gray-600">
                <span>Mild</span>
                <span>Medium</span>
                <span>Severe</span>
                <span>Extreme</span>
              </div>
            </div>

            {/* Details */}
            {details && (
              <div className="mb-3 space-y-1 rounded-lg border border-gray-700 bg-gray-800/50 p-2 text-xs text-purple-300">
                <div className="flex justify-between"><span>Packet drop:</span><span className="font-mono">{details.drop_pct}%</span></div>
                <div className="flex justify-between"><span>TLS delay:</span><span className="font-mono">{details.tls_delay_ms}ms +/-{details.tls_jitter_ms}ms</span></div>
                <div className="flex justify-between"><span>Stream stall:</span><span className="font-mono">every {details.stall_interval}</span></div>
                {status.stall_count > 0 && (
                  <div className="flex justify-between text-red-400"><span>Stalls triggered:</span><span className="font-mono">{status.stall_count}</span></div>
                )}
              </div>
            )}

            <button
              onClick={toggle}
              disabled={toggling}
              className={`w-full rounded-lg py-2 text-sm font-medium text-white disabled:opacity-50 ${
                status.active
                  ? 'bg-gray-700 hover:bg-gray-600'
                  : 'bg-purple-600 hover:bg-purple-700'
              }`}
            >
              {toggling ? '...' : status.active ? 'Disable Chaos' : 'Enable Chaos'}
            </button>
          </>
        )}

        {!status && <div className="text-center text-sm text-gray-500">Loading...</div>}
      </div>
    </div>
  );
}
