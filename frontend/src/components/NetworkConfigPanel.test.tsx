import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import NetworkConfigPanel from './NetworkConfigPanel';
import { jsonResponse, renderWithNotifications } from '../test/testUtils';

const fetchMock = vi.fn<typeof fetch>();

function getUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

describe('NetworkConfigPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it('shows an error state when config cannot be loaded', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = getUrl(input);
      if (url === '/api/v1/network-config/current') {
        throw new Error('network down');
      }
      if (url === '/api/v1/wifi-impairments/capabilities') {
        return jsonResponse({ features: {} });
      }
      if (url === '/api/v1/network-config/profiles') {
        return jsonResponse([]);
      }
      throw new Error(`Unhandled fetch: ${url}`);
    });

    renderWithNotifications(<NetworkConfigPanel />);

    await screen.findByText('Network Config Unavailable');
    expect(screen.getByText('Unable to load network settings right now.')).toBeInTheDocument();
  });

  it('applies edited network configuration and shows success feedback', async () => {
    let currentConfig = {
      wifi_ap: {
        ssid: 'WiFry',
        password: 'wifry1234',
        channel: 6,
        band: '2.4GHz',
        channel_width: 20,
        hidden: false,
        ip: '192.168.4.1',
        netmask: '255.255.255.0',
        dhcp_start: '192.168.4.100',
        dhcp_end: '192.168.4.200',
        country_code: 'US',
      },
      ethernet: {
        mode: 'dhcp',
        static_ip: '',
        static_netmask: '',
        static_gateway: '',
        static_dns: '',
      },
      fallback: {
        enabled: true,
        ip: '169.254.42.1',
        netmask: '255.255.0.0',
      },
      first_boot: false,
    };

    fetchMock.mockImplementation(async (input, init) => {
      const url = getUrl(input);

      if (url === '/api/v1/network-config/current' && (!init || !init.method)) {
        return jsonResponse(currentConfig);
      }
      if (url === '/api/v1/wifi-impairments/capabilities') {
        return jsonResponse({ features: { band_5ghz: { supported: true, reason: '' } } });
      }
      if (url === '/api/v1/network-config/profiles') {
        return jsonResponse([]);
      }
      if (url === '/api/v1/network-config/apply' && init?.method === 'PUT') {
        currentConfig = JSON.parse(String(init.body));
        return jsonResponse(currentConfig);
      }

      throw new Error(`Unhandled fetch: ${url}`);
    });

    renderWithNotifications(<NetworkConfigPanel />);

    await screen.findByText('Supported setup workflow');

    fireEvent.change(screen.getByDisplayValue('WiFry'), {
      target: { value: 'ReleaseNet' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Configuration' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/network-config/apply',
        expect.objectContaining({
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });

    const applyCall = fetchMock.mock.calls.find((call) => getUrl(call[0]) === '/api/v1/network-config/apply');
    expect(JSON.parse(String(applyCall?.[1]?.body))).toMatchObject({
      wifi_ap: expect.objectContaining({ ssid: 'ReleaseNet' }),
      fallback: expect.objectContaining({ ip: '169.254.42.1' }),
      first_boot: false,
    });

    await screen.findByText('Configuration applied successfully');
  });
});
