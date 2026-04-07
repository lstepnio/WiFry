import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearImpairment, getFeatureFlags } from './client';

const fetchMock = vi.fn();

describe('api client', () => {
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it('prefixes requests with the API base path', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ sessions: { enabled: true } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getFeatureFlags();

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/system/features', expect.any(Object));
  });

  it('handles empty successful responses for void requests', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(clearImpairment('wlan0')).resolves.toBeUndefined();
  });
});
