import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useApi } from './useApi';

describe('useApi', () => {
  it('loads data and supports manual refresh', async () => {
    const fetcher = vi
      .fn<(signal: AbortSignal) => Promise<string>>()
      .mockResolvedValueOnce('alpha')
      .mockResolvedValueOnce('beta');

    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBe('alpha');
    expect(result.current.error).toBeNull();

    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => {
      expect(result.current.data).toBe('beta');
    });

    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('captures fetcher errors', async () => {
    const fetcher = vi.fn<(signal: AbortSignal) => Promise<string>>().mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe('boom');
  });
});
