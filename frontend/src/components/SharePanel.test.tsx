import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SharePanel from './SharePanel';
import { jsonResponse, renderWithNotifications } from '../test/testUtils';

const featureFlags = {
  sharing_tunnel: true,
  collaboration: true,
  sharing_fileio: true,
};

vi.mock('../hooks/useFeatureFlags', () => ({
  useFeatureFlags: () => ({
    isEnabled: (flag: string) => Boolean(featureFlags[flag as keyof typeof featureFlags]),
  }),
}));

const fetchMock = vi.fn<typeof fetch>();

type TunnelStatus = {
  active: boolean;
  url: string | null;
  started_at: string | null;
  share_url: string | null;
  message: string;
};

function getUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

describe('SharePanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it('starts live remote access and refreshes the displayed tunnel URL', async () => {
    let tunnelStatus: TunnelStatus = {
      active: false,
      url: null,
      started_at: null,
      share_url: null,
      message: 'Tunnel not active',
    };

    fetchMock.mockImplementation(async (input, init) => {
      const url = getUrl(input);

      if (url === '/api/v1/tunnel/status') {
        return jsonResponse(tunnelStatus);
      }
      if (url === '/api/v1/collab/status') {
        return jsonResponse({ mode: 'download', connected_users: [], user_count: 0 });
      }
      if (url === '/api/v1/tunnel/start' && init?.method === 'POST') {
        tunnelStatus = {
          active: true,
          url: 'https://release-check.trycloudflare.com',
          started_at: '2025-01-01T00:00:00Z',
          share_url: 'https://release-check.trycloudflare.com/api/v1/share',
          message: 'Sharing via https://release-check.trycloudflare.com',
        };
        return jsonResponse(tunnelStatus);
      }

      throw new Error(`Unhandled fetch: ${url}`);
    });

    renderWithNotifications(<SharePanel />);

    await screen.findByText('Live Remote Access');
    fireEvent.click(screen.getByRole('button', { name: 'Start Tunnel' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/v1/tunnel/start', expect.objectContaining({ method: 'POST' }));
    });

    await screen.findByText('Live remote access started');
    await screen.findByText('https://release-check.trycloudflare.com');
  });

  it('updates collaboration mode for the active live session', async () => {
    let collabStatus = { mode: 'co-pilot', connected_users: [], user_count: 0 };

    fetchMock.mockImplementation(async (input, init) => {
      const url = getUrl(input);

      if (url === '/api/v1/tunnel/status') {
        return jsonResponse({
          active: true,
          url: 'https://release-check.trycloudflare.com',
          started_at: '2025-01-01T00:00:00Z',
          share_url: 'https://release-check.trycloudflare.com/api/v1/share',
          message: 'Sharing via https://release-check.trycloudflare.com',
        });
      }
      if (url === '/api/v1/collab/status') {
        return jsonResponse(collabStatus);
      }
      if (url === '/api/v1/collab/mode' && init?.method === 'PUT') {
        const payload = JSON.parse(String(init.body));
        collabStatus = { ...collabStatus, mode: payload.mode };
        return jsonResponse({ ...collabStatus, shared_state: { active_tab: 'sessions', active_sub_tab: null, nav: null, last_action: null, last_action_by: null, last_action_at: null } });
      }

      throw new Error(`Unhandled fetch: ${url}`);
    });

    renderWithNotifications(<SharePanel />);

    await screen.findByText('Live Collaboration');
    fireEvent.click(screen.getByRole('button', { name: 'Download Only' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/collab/mode',
        expect.objectContaining({
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });

    const modeCall = fetchMock.mock.calls.find((call) => getUrl(call[0]) === '/api/v1/collab/mode');
    expect(JSON.parse(String(modeCall?.[1]?.body))).toEqual({ mode: 'download' });

    await screen.findByText('Collaboration mode set to Download Only');
  });
});
