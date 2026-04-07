import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SessionPanel from './SessionPanel';
import { jsonResponse, renderWithNotifications } from '../test/testUtils';

const featureFlags = {
  sharing_fileio: true,
};

vi.mock('../hooks/useFeatureFlags', () => ({
  useFeatureFlags: () => ({
    isEnabled: (flag: string) => Boolean(featureFlags[flag as keyof typeof featureFlags]),
  }),
}));

const fetchMock = vi.fn<typeof fetch>();

function getUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

describe('SessionPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('creates a session from the supported workflow entry point', async () => {
    let sessions = [
      {
        id: 'session-1',
        name: 'Existing Session',
        status: 'active',
        device_model: '',
        device_ip: '',
        tags: [],
        artifact_count: 0,
        created_at: '2025-01-01T00:00:00Z',
        updated_at: '2025-01-01T00:00:00Z',
      },
    ];
    let activeSessionId: string | null = null;

    fetchMock.mockImplementation(async (input, init) => {
      const url = getUrl(input);

      if (url === '/api/v1/sessions' && (!init || !init.method)) {
        return jsonResponse(sessions);
      }
      if (url === '/api/v1/sessions/active') {
        return jsonResponse({ active_session_id: activeSessionId });
      }
      if (url === '/api/v1/sessions' && init?.method === 'POST') {
        const payload = JSON.parse(String(init.body));
        sessions = [
          ...sessions,
          {
            id: 'session-2',
            name: payload.name,
            status: 'active',
            device_model: '',
            device_ip: '',
            tags: payload.tags,
            artifact_count: 0,
            created_at: '2025-01-01T00:05:00Z',
            updated_at: '2025-01-01T00:05:00Z',
          },
        ];
        activeSessionId = 'session-2';
        return jsonResponse({ id: 'session-2' }, { status: 201 });
      }

      throw new Error(`Unhandled fetch: ${url}`);
    });

    renderWithNotifications(<SessionPanel />);

    await screen.findByText('Test Sessions');

    fireEvent.change(
      screen.getByPlaceholderText("Session name (e.g. 'STB-123 Buffering Test')"),
      { target: { value: 'Release Verification' } },
    );
    fireEvent.change(screen.getByPlaceholderText('Tags (comma-separated)'), {
      target: { value: 'release,critical' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'New Session' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/sessions',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });

    const postCall = fetchMock.mock.calls.find((call) => getUrl(call[0]) === '/api/v1/sessions' && call[1]?.method === 'POST');
    expect(postCall).toBeDefined();
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      name: 'Release Verification',
      tags: ['release', 'critical'],
      device_serial: '',
    });

    await screen.findByText('Release Verification', { selector: 'strong' });
    expect(screen.getByText(/all new artifacts will auto-link here/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Session name (e.g. 'STB-123 Buffering Test')")).toHaveValue('');
    expect(screen.getByPlaceholderText('Tags (comma-separated)')).toHaveValue('');
    expect(screen.getByPlaceholderText('ADB serial (optional)')).toHaveValue('');
  });

  it('loads session detail and exposes bundle sharing for the supported path', async () => {
    const session = {
      id: 'session-1',
      name: 'Release Session',
      status: 'active',
      device_model: 'Model-X',
      device_ip: '192.168.4.10',
      tags: ['release'],
      artifact_count: 1,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    };

    fetchMock.mockImplementation(async (input, init) => {
      const url = getUrl(input);

      if (url === '/api/v1/sessions' && (!init || !init.method)) {
        return jsonResponse([session]);
      }
      if (url === '/api/v1/sessions/active') {
        return jsonResponse({ active_session_id: 'session-1' });
      }
      if (url === '/api/v1/sessions/session-1') {
        return jsonResponse({
          id: 'session-1',
          name: 'Release Session',
          description: 'Critical regression pass',
          status: 'active',
          tags: ['release'],
          notes: '',
          device: {
            serial: 'abc',
            model: 'Model-X',
            manufacturer: 'Acme',
            android_version: '14',
            ip_address: '192.168.4.10',
          },
          impairment_log: [],
          artifact_count: 1,
          total_size_bytes: 1024,
          created_at: '2025-01-01T00:00:00Z',
          completed_at: '',
        });
      }
      if (url === '/api/v1/sessions/session-1/artifacts') {
        return jsonResponse([
          {
            id: 'artifact-1',
            session_id: 'session-1',
            type: 'report',
            name: 'Smoke Report',
            description: '',
            file_path: null,
            tags: ['release'],
            created_at: '2025-01-01T00:01:00Z',
            size_bytes: 1024,
          },
        ]);
      }

      throw new Error(`Unhandled fetch: ${url}`);
    });

    renderWithNotifications(<SessionPanel />);

    const sessionListName = (await screen.findAllByText('Release Session')).find((element) => element.closest('.cursor-pointer'));
    expect(sessionListName).toBeDefined();
    fireEvent.click(sessionListName!);

    await screen.findByText(/Supported sharing workflow/);
    expect(screen.getByRole('button', { name: 'Bundle + Share' })).toBeInTheDocument();
    expect(screen.getByText('Smoke Report')).toBeInTheDocument();
  });
});
